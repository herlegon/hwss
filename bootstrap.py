from enum import Enum
from http import client
from pprint import pprint
import shutil
import sys
import tarfile
import tempfile
import time
import zipfile
import urllib.request
from pathlib import Path
import os
import requests
from urllib.error import (
    URLError,
    HTTPError,
)
import re
import runpy



class FSM(Enum):
    INIT = 'init'
    UPDATE_HBASE = 'update_hbase'
    INSTALL_APP = 'install_app'
    UPDATE_APP = 'update_backend'


    ENDED = 'ended'
    CRITICAL = 'critical'



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
        print(f"Error: platform not supported: {sys.platform}")
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
    print(f"search {app_name} version {init_file}")

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
        print(f"Warning: Could not read version from {init_file}: {e}")
        return None



def get_installed_apps(app_install_dir: Path):
    """List all available applications installed: they all have a wss
    """

    # Find all directories that contains a websocket server
    apps: dict[str, tuple[int, int] | None] = {}
    for item in app_install_dir.iterdir():
        if (
            item.is_dir()
            and (item / "wss.py").exists()
            and (item / "__init__.py").exists()
        ):
            app_name = item.name
            api_version = get_api_version(app_name=app_name, app_install_dir=app_install_dir)
            if api_version is not None:
                apps[app_name] = api_version

    return apps



def find_latest_hbase_for_api_major(api_major: str = "") -> dict[str, int | str] | None:
    """Find latest hbase package for specific API major version (any minor/patch)"""
    print("find latest hbase version")

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
    print(f"Downloading from {url}...")
    try:
        response: client.HTTPResponse
        with urllib.request.urlopen(url) as response:
            total_size = int(response.headers.get('content-length', 0))
            if total_size == 0:
                print("Failed to retrieve content size from the server.")
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
            print(f"Download incomplete. Expected {total_size} bytes, but got {downloaded} bytes.")
            return False

    except (URLError, HTTPError) as e:
        print(f"Download failed: {e}")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return False

    return True




def main():
    # Parse bootstrap-specific args first
    import argparse
    parser = argparse.ArgumentParser(description='Bootstrap and start server')

    # Bootstrap-specific arguments
    parser.add_argument('--app', type=str, default='hwss')
    parser.add_argument('--install-dir', type=str, default="")
    parser.add_argument('--skip-update', action='store_true')
    parser.add_argument('--list-apps', action='store_true')
    parser.add_argument('--api-version', type=str, default="")
    parser.add_argument('--restart-iter', type=int, default=0)

    # Server arguments (will be passed through)
    parser.add_argument('--host', default="127.0.0.1")
    parser.add_argument('--port', type=int, default=49990)
    parser.add_argument('--keep-alive', action='store_true')
    parser.add_argument('--devmode', action='store_true')
    parser.add_argument('--log-file', type=str, default=None)


    args, unknown = parser.parse_known_args()

    # When restarting
    if args.restart_iter >= 3:
        print(f"Too many restart")
        sys.exit()

    if args.restart_iter > 1:
        time.sleep(1)

    # devmode
    devmode: bool = args.devmode

    # Installation directory
    # This won't work in dev mode
    this_dir: Path = Path(__file__).resolve().parent
    app_install_dir: Path = this_dir.parent
    hbase_dir = this_dir
    if devmode:
        # Use the local repos
        hwss_dir = this_dir / "hwss"
        hbase_dir = get_install_dir() / "python"

    elif not args.install_dir and this_dir.name == 'herlegon':
        print("use this script to get the installation dir")
        # The installation directory is the grand-parent of this script
        app_install_dir = this_dir.parent.parent
        hwss_dir = this_dir / "modules" / "hwss"

    else:
        print("use the default installation path")
        try:
            app_install_dir = get_install_dir()
            hwss_dir = app_install_dir / "python" / "modules" / "hwss"
            hbase_dir = app_install_dir / "python"
        except:
            print(f"Erroneous installation directory {app_install_dir}")
            sys.exit(-1)

    # Application
    app: str = args.app
    app_entry: Path = app_install_dir / app / "wss.py"

    # Frontend specifies its api version.
    # if not provided, we will use the installed one.
    # if hbase not installed, use the latest available
    fe_api_version_str: str = args.api_version
    if not fe_api_version_str:
        fe_api_version = None
    elif match := re.search(r"(\d+)\.(\d+)", args.api_version):
        fe_api_version = (int(match.group(1)), int(match.group(2)))
    else:
        fe_api_version = None
        print("erroneous api version")
        sys.exit(-1)


    # List servers and exit if requested
    if args.list_apps:
        available = get_installed_apps()
        if available:
            print("Available app:")
            for app_name, api_version in available.items():
                print(f"  - {app_name}: {'.'.join(api_version)}")
        else:
            print("No servers found. Packages may not be installed yet.")
        return

    print("=" * 50)
    print(f"Bootstrap starting ({app})...")
    print("=" * 50)

    print("installation directories:")
    print(f"  app_install_dir: {app_install_dir}")
    print(f"  hwss: {hwss_dir}")
    print(f"  hbase: {hbase_dir}")


    restart: bool = False
    fsm_state = FSM.INIT
    while fsm_state != FSM.ENDED:
        print(FSM(fsm_state))

        if fsm_state == FSM.INIT:
            # Compare frontend api version vs backend

            be_api_version = get_api_version(app, app_install_dir=app_install_dir)
            print(f"{app}: be_api_version: {be_api_version}")
            print(f"{app}: fe_api_version: {fe_api_version}")
            if be_api_version is None:
                # Backend for the application is not installed yet,
                # start the hwss, let's first update it
                fsm_state = FSM.UPDATE_HBASE
                continue

            elif fe_api_version is None:
                # Not specified, because the backend is not installed
                # use current api
                fsm_state = FSM.ENDED
                if devmode:
                    fsm_state = FSM.UPDATE_HBASE

            elif fe_api_version == be_api_version:
                # Installed with same API version, no need to update
                # neither the bootstrap&hinstall, nor the appli
                fsm_state = FSM.ENDED

            # Not compatible API
            elif fe_api_version[0] > be_api_version[0]:
                # Force update the backend to match frontend
                # It will automatically update the bootstrap if required
                fsm_state = FSM.UPDATE_HBASE

            elif fe_api_version[0] < be_api_version[0]:
                # The user must install latest frontend version
                fsm_state = FSM.ENDED
                print("Not compatible API version. Update frontend.")
                sys.exit(-2)

            else:
                print("unknow event")
                sys.exit(-1)

        elif fsm_state == FSM.UPDATE_APP:
            # (?)
            # remove the __init__ to force reinstall
            fsm_state = FSM.INSTALL_APP


        elif fsm_state == FSM.UPDATE_HBASE:

            # First, get the api version of the hbase (bootstrap + hwss + hinstall)
            hbase_api_version = get_api_version(
                app_name="hwss",
                app_install_dir=hwss_dir.parent
            )
            if hbase_api_version is None:
                # No webserver
                print("no hbase installed, huh?")

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
                    print(f"GitHub API is not reachable")
                    sys.exit(-1)
                retry -= 1

            if hbase_release is None:
                print("error: release not found")
                sys.exit(-1)

            pprint(hbase_release)


            # Download and extract archive
            archive_url = hbase_release['url']
            archive_filename = os.path.basename(archive_url)

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_dir_path = Path(temp_dir)
                temp_dir_path.mkdir(exist_ok=True)
                archive_path = temp_dir_path / archive_filename

                # Verify if the destination path is accessible
                if not temp_dir_path.exists():
                    print(f"Temporary directory {temp_dir_path} does not exist.")
                    return False

                # Download
                retry: int = 3
                success: bool = False
                while not success and retry:
                    try:
                        success = download_file(url=archive_url, filepath=archive_path)
                    except:
                        print(f"retry")
                        pass
                if not success:
                    print(f"Failed to download {archive_url}")
                    sys.exit(-1)

                # Remove the modules that will be installed: hwss, hinstall
                for module in ("hwss", "hinstall"):
                    module_dir = hbase_dir / "modules" / module
                    print(f"remove: {module_dir}")
                    try:
                        shutil.rmtree(module_dir)
                    except:
                        pass

                # Extract
                try:
                    with tarfile.open(archive_path, 'r:gz') as tar_file:
                        tar_file.extraction_filter = (lambda member, path: member)
                        tar_file.extractall(path=hbase_dir)
                except:
                    print("failed to install hbase")
                    sys.exit(-1)

                # Because a new version has been installed, restart
                restart = True
                fsm_state = FSM.ENDED


        elif fsm_state == FSM.ENDED:
            break

        # Restart or launch the webserver
        if restart:
            # Preserve original arguments when restarting
            # TODO: this has to be handled by the frontend
            # if devmode, it's safe to restart
            if args.restart_iter > 0:
                argv = sys.argv[:-2]
            else:
                argv = sys.argv

            argv = (
                [sys.executable]
                + argv
                + [f"--restart-iter", f"{args.restart_iter + 1}"]
            )
            print(f"restart with argv: {argv}")
            os.execv(sys.executable, argv)

        else:
            if not app_entry.exists():
                print(f"\nERROR: Server file not found: {app_entry}")
                sys.exit(1)

            runpy.run_module(app_entry, run_name='__main__')


if __name__ == "__main__":
    main()
