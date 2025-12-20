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


def get_versions(
    app_name: str,
    app_install_dir: Path,
    hwss_dir: Path,
) -> tuple[tuple[int,...] | None, tuple[int, int] | None, tuple[int, int] | None]:
    """Returns application version, app api version and hwss api version"""
    app_version = None
    app_api_version = None
    hwss_api_version = None

    app_version_fp: Path = app_install_dir / app_name / "__init__.py"
    logger.debug(f"search {app_name} versions in {app_version_fp}")
    hwss_api_version_fp: Path = hwss_dir.parent / app_name / "__init__.py"
    logger.debug(f"search {app_name} version in {app_version_fp}")

    for version_fp in (app_version_fp, hwss_api_version_fp):
        if not version_fp.exists():
            continue
        try:
            content = version_fp.read_text(encoding='utf-8')
            for line in content.split('\n'):
                if line.strip().startswith('__version__') and '=' in line:
                    value = line.split('=', 1)[1].strip().strip('"\'')
                    # Match major.minor (x.y) or major.minor.patch (x.y.z) or just major (x)
                    if match := re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value):
                        major = int(match.group(1))
                        minor = int(match.group(2)) if match.group(2) else 0
                        patch = int(match.group(3)) if match.group(3) else 0
                        app_version = (major, minor, patch)

                if line.strip().startswith('__api_version__') and '=' in line:
                    value = line.split('=', 1)[1].strip().strip('"\'')
                    if match := re.search(r"(\d+)\.(\d+)", value):
                        major = int(match.group(1))
                        minor = int(match.group(2))
                        _api_version = (major, minor)
                        if version_fp == app_version_fp:
                            app_api_version = _api_version
                        elif version_fp == hwss_api_version_fp:
                            hwss_api_version = _api_version

        except Exception as e:
            logger.warning(f"Warning: Could not read version from {version_fp}: {e}")

    return app_version, app_api_version, hwss_api_version


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



def prepare_bootstrap_for_fresh_install(python_dir: Path):
    """
    Check if bootstrap files are symlinks
    and remove them to prepare for fresh installation.
    """
    if not python_dir.exists():
        logger.warning(f"Python directory doesn't exist: {python_dir}")
        return

    # Find all files starting with 'bootstrap_'
    symlinks_found = []
    for file_path in python_dir.iterdir():
        if file_path.is_file() and file_path.name.startswith('bootstrap_'):
            if file_path.is_symlink():
                symlinks_found.append(file_path)

    if symlinks_found:
        logger.info(f"Dev mode bootstrap detected: found {len(symlinks_found)} symlinked bootstrap file(s)")
        for symlink in symlinks_found:
            logger.info(f"  Removing symlink: {symlink.name} -> {symlink.resolve()}")
            symlink.unlink()
    else:
        logger.info("No bootstrap symlinks detected.")



def prepare_modules_for_fresh_install(modules_dir: Path):
    """
    Remove module symlinks and prepare directories for fresh installation.
    This allows switching from dev mode to prod mode.
    """
    if not modules_dir.exists():
        logger.info(f"Modules directory doesn't exist, creating: {modules_dir}")
        modules_dir.mkdir(parents=True, exist_ok=True)
        return

    # Check for symlinks in modules directory
    symlinks_found = []
    for item in modules_dir.iterdir():
        if item.is_symlink():
            symlinks_found.append(item)

    if symlinks_found:
        logger.info(f"Dev mode detected: found {len(symlinks_found)} module symlink(s)")
        for symlink in symlinks_found:
            logger.info(f"  Removing symlink: {symlink.name} -> {symlink.resolve()}")
            symlink.unlink()
    else:
        logger.info("No module symlinks detected, proceeding with installation.")



def prepare_for_fresh_install(python_dir: Path):
    """
    Complete preparation for fresh installation:
    removes both bootstrap and module symlinks.
    """
    logger.info("Preparing for fresh installation...")
    prepare_bootstrap_for_fresh_install(python_dir)
    prepare_modules_for_fresh_install(python_dir / "modules")
    logger.info("Preparation complete. Ready for fresh installation.")


def extract_filtered_lib(
    archive_path: Path,
    hbase_dir: Path,
    force_prod: bool = False
):
    """
    Extract files from the tar.gz archive to the target directory,
    skipping files that are specific to other platforms.
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

    # Check if we're in dev mode (symlink detected) and not forcing prod install
    bootstrap_script: Path = hbase_dir / "bootstrap.py"
    is_dev_mode: bool = bootstrap_script.is_symlink() and not force_prod
    if is_dev_mode:
        # Extract to a separate binaries directory instead
        python_root = hbase_dir.parent.parent
        extraction_dir = python_root / "Modules_prod" / hbase_dir.name
        extraction_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Dev mode detected (symlink): extracting binaries to {extraction_dir}")

        # Add this directory to sys.path if not already there
        if str(extraction_dir.parent) not in sys.path:
            sys.path.insert(0, str(extraction_dir.parent))
            logger.debug(f"Added {extraction_dir.parent} to sys.path")

    else:
        # Prod mode: extract directly to the target
        extraction_dir = hbase_dir
        extraction_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Prod mode: extracting to {extraction_dir}")

    # Extract files, skipping other platform-specific files
    with tarfile.open(archive_path, 'r:gz') as tar_file:
        for member in tar_file.getmembers():
            print(member)
            # Skip files that match platform extensions of other platforms
            skip: bool = False
            for ext in platform_files.values():
                if ext != current_ext and member.name.endswith(ext):
                    skip = True
                    logger.debug(f"Skipping {member.name} (not for this platform)")
                    break

            if not skip:
                tar_file.extract(member, path=extraction_dir)



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
    ENDED = 'ended'


def fsm(
    app_name: str,
    app_install_dir: Path,
    fe_api_version: tuple[int, int] | None,
    hbase_dir: Path,
    hwss_dir: Path,
    devmode: bool = False,
) -> bool:

    restart: bool = False
    fsm_state = _FSM.INIT
    while fsm_state != _FSM.ENDED:

        if fsm_state == _FSM.INIT:
            # Compare frontend api version vs backend
            app_version, app_api_version, hbase_api_version = get_versions(
                app_name,
                app_install_dir=app_install_dir,
                hwss_dir=hwss_dir
            )
            logger.info(f"{app_name}: hbase API version: {hbase_api_version}")
            logger.info(f"{app_name}: requested API version by frontend: {fe_api_version}")
            logger.info(f"{app_name}: installed API version: {app_api_version}")
            logger.info(f"{app_name}: application version: {app_version}")

            is_hbase_installed = all([
                Path(hbase_dir / "modules" / m / "__init__.py").exists()
                for m in ('hwss', 'hinstall')
            ])
            logger.info(f"hbase installed: {is_hbase_installed}")
            if not is_hbase_installed or hbase_api_version is None:
                # hwss is not installed yet
                fsm_state = _FSM.UPDATE_HBASE
                continue

            # Verify just the application API version to be sure that the hwss version is
            #   up-to-date
            # hinstall/hwss must be up-to-date to communicate with frontend
            if app_api_version is not None:
                if app_api_version[0] < hbase_api_version[0]:
                    # Not compatible version -> backend has to be updated
                    # will start the hwss to update it
                    fsm_state = _FSM.ENDED
                    logger.info(f"Not compatible API version. {app_name} will be installed")

                if app_api_version[0] > hbase_api_version[0]:
                    # Not compatible version -> hwss to be updated
                    logger.warning("Not compatible API version. hwss will be updated first")
                    fsm_state = _FSM.UPDATE_HBASE
                    continue

            if fe_api_version is None:
                # whatever, use the latest hwss version
                logger.info(f"Not API version specified. Update to the latest")
                fsm_state = _FSM.UPDATE_HBASE
                continue


        elif fsm_state == _FSM.UPDATE_HBASE:

            # First, get the api version of the hbase (bootstrap + hwss + hinstall)
            hbase_api_version = get_versions(
                app_name=app_name,
                app_install_dir=app_install_dir,
                hwss_dir=hwss_dir
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
                try:
                    if fe_api_version:
                        fe_major_api_version = fe_api_version[0]
                        hbase_release = find_latest_hbase_for_api_major(api_major=fe_major_api_version)
                    else:
                        # Use the latest release
                        hbase_release = find_latest_hbase_for_api_major(api_major="")

                    if hbase_release is not None:
                        break
                except Exception as e:
                    logger.warning(f"failed to retrieve latest hbase version. {str(e)}")

                time.sleep(1)
                if not is_github_alive():
                    logger.error(f"GitHub API is not reachable")
                    sys.exit(-1)
                retry -= 1

            if hbase_release is None:
                logger.error("hbase release not found")
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
                # for module in ("hwss", "hinstall"):
                #     module_dir = hbase_dir / "modules" / module
                #     try:
                #         shutil.rmtree(module_dir)
                #     except:
                #         pass

                # Extract
                try:
                    extract_filtered_lib(
                        archive_path=archive_path,
                        hbase_dir=hbase_dir,
                        force_prod=not devmode
                    )
                except Exception as e:
                    logger.error(f"failed to install hbase. {str(e)}")
                    sys.exit(-1)

                # Because a new version has been installed, restart
                restart = True
                fsm_state = _FSM.ENDED


        elif fsm_state == _FSM.ENDED:
            break

    return restart
