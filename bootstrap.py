# bootstrap.py
from enum import Enum
import sys
import time
import zipfile
import urllib.request
from pathlib import Path
import os
import re

BASE_DIR = Path(__file__).parent
PACKAGES_DIR = BASE_DIR / "packages"
APP_ROOT_DIR: Path = Path(__file__).parent.resolve()

# GitHub release URLs
RELEASE_URL = "https://api.github.com/repos/herlegon/rehost/releases/latest"


def is_installed(app: str) -> bool:
    # if folder exists
    return False


def download_file(url: str, dest: str):
    """Download file with progress"""
    print(f"Downloading from {url}...")

    with urllib.request.urlopen(url) as response:
        total_size = int(response.headers.get('content-length', 0))

        with open(dest, 'wb') as f:
            downloaded = 0
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)

                if total_size:
                    percent = (downloaded / total_size) * 100
                    print(f"\rProgress: {percent:.1f}%", end='')



def get_version_from_init(package_name: str):
    """Extract __version__ from package's __init__.py"""
    init_file: Path = APP_ROOT_DIR / package_name / "__init__.py"

    if not init_file.exists():
        return None

    try:
        content = init_file.read_text(encoding='utf-8')

        # Look for __version__ = "x.y.z" or __version__ = 'x.y.z'
        # Single line only, case-sensitive
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('__version__'):
                # Extract the version string
                if '=' in line:
                    value = line.split('=', 1)[1].strip()
                    # Remove quotes (single or double)
                    value = value.strip('"').strip("'")
                    return value

        return None

    except Exception as e:
        print(f"Warning: Could not read version from {init_file}: {e}")
        return None


def get_local_version(server_name='hwss'):
    """Get currently installed version from package __init__.py"""
    version = get_version_from_init(server_name)
    return version if version else "0.0.0"


def get_latest_release_url():
    """Get download URL from GitHub releases"""
    if "yourrepo" in RELEASE_URL:
        raise Exception("Invalid repository URL (placeholder detected)")

    import json

    with urllib.request.urlopen(RELEASE_URL) as response:
        data = json.loads(response.read())

    for asset in data['assets']:
        if asset['name'] == 'packages.zip':
            return asset['browser_download_url'], data['tag_name'].lstrip('v')

    raise Exception("No packages.zip found in latest release")



def packages_exist():
    """Check if packages are installed"""
    return PACKAGES_DIR.exists() and any(PACKAGES_DIR.glob("*"))


def check_for_updates(server_name='hwss'):
    """Check if newer version available"""
    if "yourrepo" in RELEASE_URL:
        return False, "0.0.0"

    import json

    local_version = get_local_version(server_name)

    with urllib.request.urlopen(RELEASE_URL) as response:
        data = json.loads(response.read())

    remote_version = data['tag_name'].lstrip('v')

    return remote_version != local_version, remote_version


def download_and_extract_packages():
    """Download and extract all packages"""
    temp_zip = BASE_DIR / "packages_temp.zip"
    try:
        # Get download URL and version
        download_url, version = get_latest_release_url()

    except Exception as e:
        print(f"Error: {str(e)}")
        return False

    try:
        # Download
        download_file(download_url, temp_zip)

        print("Extracting packages...")

        # Create packages directory
        PACKAGES_DIR.mkdir(exist_ok=True)

        # Extract to packages/
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(PACKAGES_DIR)

        print(f"Installation complete! (v{version})")
        return True

    except Exception as e:
        print(f"Error: {str(e)}")
        return False

    finally:
        if temp_zip.exists():
            temp_zip.unlink()
            return True

    return False

def is_github_reachable() -> bool:
    try:
        # urllib.request.urlopen('https://github.com', timeout=5)
        urllib.request.urlopen('https://www.google.com', timeout=5)
        return True
    except:
        return False

APP_API_VERSION = 1

class SM(Enum):
    INIT = 'init'
    INSTALL = 'install'
    UPDATE = 'update'


    ENDED = 'ended'
    CRITICAL = 'critical'



def get_api_version(app_name: str, app_dir: Path | None = None) -> tuple[int, int] | None:
    """Extract __api_version__ from app's __init__.py
    """
    # Look for __api_version__ = "x.y" or __api_version__ = 'x.y'
    # with X major and Y minor: major is non backward compatible
    # Single line only, case-sensitive
    if app_dir is None:
        init_file: Path = APP_ROOT_DIR / app_name / "__init__.py"
    else:
        init_file: Path = app_dir / "__init__.py"
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



def get_installed_apps():
    """List all available applications installed: they all have a wss
    """

    # Find all directories that contains a websocket server
    apps: dict[str, tuple[int, int] | None] = {}
    for item in APP_ROOT_DIR.iterdir():
        if (
            item.is_dir()
            and (item / "wss.py").exists()
            and (item / "__init__.py").exists()
        ):
            app_name = item.name
            api_version = get_api_version(app_name=app_name)
            if api_version is not None:
                apps[app_name] = api_version

    return apps



def main():
    # Parse bootstrap-specific args first
    import argparse
    parser = argparse.ArgumentParser(description='Bootstrap and start server')

    # Bootstrap-specific arguments
    parser.add_argument('--app', type=str, default='hwss')
    parser.add_argument('--skip-update', action='store_true')
    parser.add_argument('--list-apps', action='store_true')
    parser.add_argument('--api-version', type=int, default=1)

    # Server arguments (will be passed through)
    parser.add_argument('--host', default="127.0.0.1")
    parser.add_argument('--port', type=int, default=49990)
    parser.add_argument('--keep-alive', action='store_true')
    parser.add_argument('--devmode', action='store_true')
    parser.add_argument('--log-file', type=str, default=None)

    args, unknown = parser.parse_known_args()

    if match := re.search(r"(\d+)\.(\d+)", args.api_version):
        fe_api_version = (int(match.group(1)), int(match.group(2)))
    else:
        print("erroneous api version")
        sys.exit(-1)

    app: str = args.app

    sm_state = SM.INIT


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

    app: str = args.app
    print("=" * 50)
    print(f"Bootstrap starting ({app})...")
    print("=" * 50)


    while sm_state != SM.ENDED:
        if sm_state == SM.INIT:

            be_api_version = get_api_version(app)
            if be_api_version is None:
                # Application is not installed yet,
                # start the hwss, let's first update it
                sm_state = SM.INSTALL
                continue

            else:

                # Installed with same API version, no need to update
                # neither the bootstrap&hinstall, nor the appli
                if fe_api_version == be_api_version:
                    sm_state = SM.ENDED
                    break

                # Not compatible API
                if fe_api_version[0] > be_api_version[0]:
                    # Force update this backend to match frontend
                    # It will automatically update the bootstrap if required
                    sm_state = SM.UPDATE

                elif fe_api_version[0] < be_api_version[0]:
                    # The user must install latest frontend version
                    sm_state = SM.ENDED
                    sys.exit(-2)

        elif sm_state == SM.UPDATE:
            # (?)
            # remove the __init__ to force reinstall
            sm_state = SM.INSTALL


        elif sm_state == SM.INSTALL:
            # First, get the api version of the bootstrap
            hbase_api_version = get_api_version(
                "hwss", Path(__file__).resolve() / "modules" / "hwss"
            )
            if hbase_api_version is None:
                # No webserver
                print("no hwss installed, huh?")

            else:
                # Get latest version of the same major version


            # Is Repo available
            # if not exit with critical

            # download the latest compatible archive

            # Update without reinstalling pip packages:
            #   hbase-x.y.tar.gz
            #   - hwss
            #   - hinstall (backend)
            #   - bootstrap

            # update hboot if latest version > current version:





        elif sm_state == SM.ENDED:
            break

    #   no -> install

    # 2.



















    # Check if packages exist
    retry = 3
    if not packages_exist():
        # Check for local source fallback
        if (BASE_DIR / app).exists() and (BASE_DIR / app / "wss.py").exists():
            print(f"Local source detected for '{app}'. Running from {BASE_DIR}.")
            global PACKAGES_DIR
            PACKAGES_DIR = BASE_DIR
        else:
            print("\nFirst run detected. Downloading packages...")

            if not is_github_reachable():
                print("ERROR: No internet connection and packages not installed.")
                print("Please connect to internet and try again.")
                sys.exit(1)

            extracted: bool = False
            try:
                extracted = download_and_extract_packages()
            except:
                retry -= 1
                print(f"retry: {retry}")
            time.sleep(2)

            try:
                print("\nRestarting to load packages...")
            except:
                sys.exit(1)

            if retry:
                # Preserve original arguments when restarting
                os.execv(sys.executable, [sys.executable] + sys.argv)
                return

    # Show current version
    current_version = get_local_version(app)
    print(f"Current {app} version: v{current_version}")

    # Check for updates (unless skipped or in devmode)
    if not args.skip_update and not args.devmode and is_github_reachable():
        print("\nChecking for updates...")
        try:
            has_update, new_version = check_for_updates(app)

            if has_update:
                print(f"Update available: v{current_version} -> v{new_version}")
                print("Downloading update...")

                download_and_extract_packages()

                print("\nRestarting with new version...")
                # Preserve original arguments when restarting
                os.execv(sys.executable, [sys.executable] + sys.argv)
                return
            else:
                print("Already up to date!")

        except Exception as e:
            print(f"Update check failed: {e}")
            print("Continuing with current version...")
    else:
        if args.skip_update:
            print("Skipping update check (--skip-update)")
        elif args.devmode:
            print("Skipping update check (devmode)")
        else:
            print("No internet - skipping update check")

    # Check if requested server exists
    app_dir = PACKAGES_DIR / app
    server_module = f"{app}.server"

    if not app_dir.exists():
        available = get_installed_apps()
        print(f"\nERROR: Server '{app}' not found!")
        print(f"Looking for: {app_dir}")

        if available:
            print(f"\nAvailable servers:")
            for server in available:
                version = get_version_from_init(server)
                version_str = f" (v{version})" if version else ""
                print(f"  - {server}{version_str}")
            print(f"\nUsage: python bootstrap.py --server {available[0]}")
        else:
            print("\nNo servers found in packages directory.")

        sys.exit(1)

    entry_file = app_dir / "wss.py"
    if not entry_file.exists():
        print(f"\nERROR: Server file not found: {entry_file}")
        print(f"Expected: {app}/wss.py")
        sys.exit(1)

    # Add packages directory to path
    sys.path.insert(0, str(PACKAGES_DIR))

    # Start server
    print(f"\nStarting {app} server v{current_version}...")
    print("=" * 50)

    # Use runpy to execute the server module
    import runpy
    runpy.run_module(server_module, run_name='__main__')


if __name__ == "__main__":
    main()
