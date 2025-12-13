# bootstrap.py
import sys
import zipfile
import urllib.request
from pathlib import Path
import os
import re

BASE_DIR = Path(__file__).parent
PACKAGES_DIR = BASE_DIR / "packages"

# GitHub release URLs
RELEASE_URL = "https://api.github.com/repos/youruser/yourrepo/releases/latest"


def download_file(url, dest):
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

    print()


def get_version_from_init(package_name: str):
    """Extract __version__ from package's __init__.py"""
    init_file: Path = PACKAGES_DIR / package_name / "__init__.py"

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
    import json

    with urllib.request.urlopen(RELEASE_URL) as response:
        data = json.loads(response.read())

    for asset in data['assets']:
        if asset['name'] == 'packages.zip':
            return asset['browser_download_url'], data['tag_name'].lstrip('v')

    raise Exception("No packages.zip found in latest release")


def get_available_app():
    """List all available server packages in packages/ directory"""
    if not PACKAGES_DIR.exists():
        return []

    # Find all directories that contains a websocket server
    apps: list[str] = []
    for item in PACKAGES_DIR.iterdir():
        if item.is_dir() and (item / "wss.py").exists():
            apps.append(item.name)

    return sorted(apps)


def packages_exist():
    """Check if packages are installed"""
    return PACKAGES_DIR.exists() and any(PACKAGES_DIR.glob("*"))


def check_for_updates(server_name='hwss'):
    """Check if newer version available"""
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

        # Download
        download_file(download_url, temp_zip)

        print("Extracting packages...")

        # Create packages directory
        PACKAGES_DIR.mkdir(exist_ok=True)

        # Extract to packages/
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            zip_ref.extractall(PACKAGES_DIR)

        print(f"Installation complete! (v{version})")

    finally:
        if temp_zip.exists():
            temp_zip.unlink()


def check_internet():
    """Quick check if internet is available"""
    try:
        urllib.request.urlopen('https://github.com', timeout=5)
        return True
    except:
        return False


def main():
    # Parse bootstrap-specific args first
    import argparse
    parser = argparse.ArgumentParser(description='Bootstrap and start server')

    # Bootstrap-specific arguments
    parser.add_argument('--app', type=str, default='hwss')
    parser.add_argument('--skip-update', action='store_true')
    parser.add_argument('--list-apps', action='store_true')

    # Server arguments (will be passed through)
    parser.add_argument('--host', default="127.0.0.1")
    parser.add_argument('--port', type=int, default=49990)
    parser.add_argument('--keep-alive', action='store_true')
    parser.add_argument('--devmode', action='store_true')
    parser.add_argument('--log-file', type=str, default=None)

    args, unknown = parser.parse_known_args()

    # List servers and exit if requested
    if args.list_apps:
        available = get_available_app()
        if available:
            print("Available servers:")
            for server in available:
                version = get_version_from_init(server)
                version_str = f" (v{version})" if version else ""
                print(f"  - {server}{version_str}")
        else:
            print("No servers found. Packages may not be installed yet.")
        return

    app: str = args.app
    print("=" * 50)
    print(f"Bootstrap starting ({app})...")
    print("=" * 50)


    # Check if packages exist
    if not packages_exist():
        print("\nFirst run detected. Downloading packages...")

        if not check_internet():
            print("ERROR: No internet connection and packages not installed.")
            print("Please connect to internet and try again.")
            sys.exit(1)

        download_and_extract_packages()

        print("\nRestarting to load packages...")
        # Preserve original arguments when restarting
        os.execv(sys.executable, [sys.executable] + sys.argv)
        return

    # Show current version
    current_version = get_local_version(app)
    print(f"Current {app} version: v{current_version}")

    # Check for updates (unless skipped or in devmode)
    if not args.skip_update and not args.devmode and check_internet():
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
        available = get_available_app()
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
