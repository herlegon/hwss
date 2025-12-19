from enum import Enum
import logging

from http import client
import os
from pathlib import Path
from pprint import pprint
import re
import tarfile
import tempfile
import time
import requests
import shutil
import sys
import urllib
from urllib.error import (
    URLError,
    HTTPError,
)

logger = logging.getLogger("bootstrap")


def get_install_dir(
    organization: str = "herlegon"
) -> Path:
    """Get platform-specific backend directory"""

    if sys.platform == "win32":
        # Windows: Use AppData\Local
        base = Path(
            os.environ.get('LOCALAPPDATA', Path.home() / "AppData" / "Local")
        )

    elif sys.platform == "linux":
        # Linux: Use XDG Base Directory
        base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / ".local" / "share"))

    elif sys.platform == "darwin":
        # macOS: Use Application Support
        base = Path.home() / "Library" / "Application Support"

    else:
        logger.error(f"Error: platform not supported: {sys.platform}")
        sys.exit(-1)

    return base.resolve() / organization


def get_api_version(
    app_name: str,
    app_install_dir: Path
) -> tuple[int, int] | None:
    """Extract __api_version__ from app's __init__.py
    """
    # Look for __api_version__ = "x.y" or __api_version__ = 'x.y'
    # with X major and Y minor: major is non backward compatible
    # Single line only, case-sensitive
    init_file: Path = app_install_dir / app_name / "__init__.py"
    logger.debug(f"search {app_name} version {init_file}")

    if not init_file.exists():
        return None

    try:
        content = init_file.read_text(encoding='utf-8')
        for line in content.split('\n'):
            if line.strip().startswith('__api_version__') and '=' in line:
                value = line.split('=', 1)[1].strip().strip('"\'')
                if match := re.search(r"(\d+)\.(\d+)", value):
                    return (int(match.group(1)), int(match.group(2)))

    except Exception as e:
        logger.warning(f"Warning: Could not read version from {init_file}: {e}")
        return None



def get_installed_apps(app_install_dir: Path) -> dict[str, tuple[int, int]]:
    """List all available applications installed: they all have a wss
    """

    # Find all directories that contains a websocket server
    apps: dict[str, tuple[int, int]] = {}
    for item in app_install_dir.iterdir():
        if (
            item.is_dir()
            and (item / "wss.py").exists()
            and (item / "__init__.py").exists()
        ):
            app_name = item.name
            api_version = get_api_version(
                app_name=app_name,
                app_install_dir=app_install_dir
            )
            if api_version is not None:
                apps[app_name] = api_version

    return apps



def find_latest_hbase_for_api_major(api_major: str = "") -> dict[str, int | str] | None:
    """Find latest hbase package for specific API major version (any minor/patch)"""

    # Get all releases
    url = "https://api.github.com/repos/herlegon/hbase/releases"
    response = requests.get(url)
    releases = response.json()

    # Pattern: hbase-{major}.{minor}.{patch}.tar.gz
    if not api_major:
        pattern = r"hbase-(\d+)\.(\d+)\.(\d+)\.tar\.gz"
        compatible = []
        for release in releases:
            for asset in release['assets']:
                match = re.match(pattern, asset['name'])
                if match:
                    major = int(match.group(1))
                    minor = int(match.group(2))
                    patch = int(match.group(3))
                    full_version = f"{major}.{minor}.{patch}"
                    compatible.append({
                        'version': full_version,
                        'api_major': major,
                        'api_minor': minor,
                        'patch': patch,
                        'url': asset['browser_download_url']
                    })

        if not compatible:
            return None

        # Sort by major, minor, and patch (desc) to get the latest overall release
        compatible.sort(key=lambda x: (x['api_major'], x['api_minor'], x['patch']), reverse=True)
        return compatible[0]

    else:
        pattern = rf"hbase-{api_major}\.(\d+)\.(\d+)\.tar\.gz"
        compatible = []
        for release in releases:
            for asset in release['assets']:
                match = re.match(pattern, asset['name'])
                if match:
                    minor = int(match.group(1))
                    patch = int(match.group(2))
                    full_version = f"{api_major}.{minor}.{patch}"
                    compatible.append({
                        'version': full_version,
                        'api_major': api_major,
                        'api_minor': minor,
                        'patch': patch,
                        'url': asset['browser_download_url']
                    })

        if not compatible:
            return None
        # Sort by minor (desc), then patch (desc) to get latest
        compatible.sort(key=lambda x: (x['api_minor'], x['patch']), reverse=True)
        return compatible[0]


def is_github_alive() -> bool:
    url = "https://api.github.com"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return True

    except requests.exceptions.RequestException as e:
        pass

    return False



def download_file(url: str, filepath: Path) -> bool:
    logger.info(f"Downloading from {url}")
    try:
        response: client.HTTPResponse
        with urllib.request.urlopen(url) as response:
            total_size = int(response.headers.get('content-length', 0))
            if total_size == 0:
                logger.warning("Failed to retrieve content size from the server.")
                return False

            with open(filepath, 'wb') as f:
                downloaded = 0
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

        # Verify if the full file was downloaded
        if downloaded != total_size:
            logger.error(f"Download incomplete. Expected {total_size} bytes, but got {downloaded} bytes.")
            return False

    except (URLError, HTTPError) as e:
        logger.error(f"Download failed: {e}")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return False

    return True



def extract_filtered_lib(archive_path: Path, hbase_dir: Path):
    """
    Extract files from the tar.gz archive to the target directory,
    skipping files that are specific to other platforms.

    Args:
        archive_path (Path): Path to the tar.gz archive.
        hbase_dir (Path): Directory to extract the files to.
    """
    # Define platform-specific file extensions
    platform_files = {
        'linux': '.so',
        'darwin': '.dylib',
        'win32': '.pyd',
    }

    # Detect current platform
    platform = sys.platform.lower()
    if platform.startswith('linux'):
        current_ext = platform_files['linux']
    elif platform.startswith('darwin'):
        current_ext = platform_files['darwin']
    elif platform.startswith('win'):
        current_ext = platform_files['win32']
    else:
        logger.error(f"Unsupported platform: {platform}")
        sys.exit(-1)

    # Extract files, skipping other platform-specific files
    with tarfile.open(archive_path, 'r:gz') as tar_file:
        for member in tar_file.getmembers():
            # Skip files that match platform extensions of other platforms
            skip = False
            for ext in platform_files.values():
                if ext != current_ext and member.name.endswith(ext):
                    skip = True
                    logger.debug(f"Skipping {member.name} (not for this platform)")
                    break
            if not skip:
                tar_file.extract(member, path=hbase_dir)
                logger.debug(f"Extracted {member.name} to {hbase_dir}")



def remove_restart_iter(args) -> list[str]:
    # Create a new list to store the filtered arguments
    filtered_args = []

    i = 0
    while i < len(args):
        # Look for '--restart-iter' and remove it along with the next number
        if args[i] == '--restart-iter' and i + 1 < len(args) and args[i + 1].isdigit():
            i += 2  # Skip the '--restart-iter' and its following number
        else:
            filtered_args.append(args[i])
            i += 1

    return filtered_args


class _FSM(Enum):
    INIT = 'init'
    UPDATE_HBASE = 'update_hbase'
    INSTALL_APP = 'install_app'
    UPDATE_APP = 'update_app'
    ENDED = 'ended'


def fsm(
    app: str,
    app_install_dir: Path,
    fe_api_version: tuple[int, int],
    hbase_dir: Path,
    hwss_dir: Path,
    devmode: bool = False,
) -> bool:

    restart: bool = False
    fsm_state = _FSM.INIT
    while fsm_state != _FSM.ENDED:

        if fsm_state == _FSM.INIT:
            # Compare frontend api version vs backend
            be_api_version = get_api_version(
                app,
                app_install_dir=hwss_dir.parent if app == "hwss" else app_install_dir
            )
            logger.info(f"{app}: be_api_version: {be_api_version}")
            logger.info(f"{app}: fe_api_version: {fe_api_version}")
            if be_api_version is None:
                # Backend for the application is not installed yet,
                # start the hwss, let's first update it
                fsm_state = _FSM.UPDATE_HBASE
                continue

            elif fe_api_version is None:
                # Not specified, because the backend is not installed
                # use current api
                fsm_state = _FSM.ENDED
                if devmode:
                    fsm_state = _FSM.UPDATE_HBASE

            elif fe_api_version == be_api_version:
                # Installed with same API version, no need to update
                # neither the bootstrap&hinstall, nor the appli
                fsm_state = _FSM.ENDED

            # Not compatible API
            elif fe_api_version[0] > be_api_version[0]:
                # Force update the backend to match frontend
                # It will automatically update the bootstrap if required
                fsm_state = _FSM.UPDATE_HBASE

            elif fe_api_version[0] < be_api_version[0]:
                # The user must install latest frontend version
                fsm_state = _FSM.ENDED
                logger.error("Not compatible API version. Update frontend.")
                sys.exit(-2)

            else:
                logger.error("unknow event")
                sys.exit(-1)


        elif fsm_state == _FSM.UPDATE_APP:
            # (?)
            # remove the __init__ to force reinstall
            fsm_state = _FSM.INSTALL_APP


        elif fsm_state == _FSM.UPDATE_HBASE:

            # First, get the api version of the hbase (bootstrap + hwss + hinstall)
            hbase_api_version = get_api_version(
                app_name="hwss",
                app_install_dir=hwss_dir.parent
            )
            if hbase_api_version is None:
                # No webserver
                logger.warning("no hbase installed, huh?")

            # Get latest version of the same major version as the app
            # hbase-1.2.5.tar.gz
            # hbase-x.y.z.tar.gz
            #     ↑ ↑ ↑
            #     │ │ └─ Package version (patch)
            #     │ └─── API minor version
            #     └───── API major version
            # Content:
            #   - hwss
            #   - hinstall (backend)
            #   - bootstrap
            retry = 3
            hbase_release: dict | None = None
            while retry:
                if fe_api_version:
                    fe_major_api_version = fe_api_version[0]
                    hbase_release = find_latest_hbase_for_api_major(api_major=fe_major_api_version)
                else:
                    # Use the latest release
                    hbase_release = find_latest_hbase_for_api_major(api_major="")

                if hbase_release is not None:
                    break

                time.sleep(1)
                if not is_github_alive():
                    logger.error(f"GitHub API is not reachable")
                    sys.exit(-1)
                retry -= 1

            if hbase_release is None:
                logger.error("error: release not found")
                sys.exit(-1)

            # Download and extract archive
            archive_url = hbase_release['url']
            archive_filename = os.path.basename(archive_url)

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_dir_path = Path(temp_dir)
                temp_dir_path.mkdir(exist_ok=True)
                archive_path = temp_dir_path / archive_filename

                # Verify if the destination path is accessible
                if not temp_dir_path.exists():
                    logger.error(f"Temporary directory {temp_dir_path} does not exist.")
                    return False

                # Download
                retry: int = 3
                success: bool = False
                while not success and retry:
                    try:
                        success = download_file(url=archive_url, filepath=archive_path)
                    except:
                        logger.debug(f"retry")
                        pass
                if not success:
                    logger.error(f"Failed to download {archive_url}")
                    sys.exit(-1)

                # Remove the modules that will be installed: hwss, hinstall
                for module in ("hwss", "hinstall"):
                    module_dir = hbase_dir / "modules" / module
                    try:
                        shutil.rmtree(module_dir)
                    except:
                        pass

                # Extract
                try:
                    extract_filtered_lib(archive_path=archive_path, hbase_dir=hbase_dir)
                except:
                    logger.error("failed to install hbase")
                    sys.exit(-1)

                # Because a new version has been installed, restart
                restart = True
                fsm_state = _FSM.ENDED


        elif fsm_state == _FSM.ENDED:
            break

    return restart
