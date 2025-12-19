from http import client
import os
from pathlib import Path
import re
import tarfile
import requests
import sys
import urllib
from urllib.error import (
    URLError,
    HTTPError,
)


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


def extract_filtered_lib(archive_path: Path, hbase_dir: Path):
    """
    Extract platform-specific files from the tar.gz archive to the target directory.
    Filters out files that don't match the current platform.

    Args:
        archive_path (str): Path to the tar.gz archive.
        hbase_dir (str): Directory to extract the files to.
    """
    # Define platform-specific file extensions (you can adjust this as needed)
    platform_files = {
        'linux': '.so',
        'darwin': '.dylib',
        'win32': '.pyd',
    }

    # Detect current platform
    platform = sys.platform.lower()
    if platform.startswith('linux'):
        platform_name = 'linux'
    elif platform.startswith('darwin'):
        platform_name = 'darwin'
    elif platform.startswith('win'):
        platform_name = 'win32'
    else:
        print(f"Unsupported platform: {platform}")
        sys.exit(-1)

    # Extract files
    with tarfile.open(archive_path, 'r:gz') as tar_file:
        for member in tar_file.getmembers():
            # Only extract files that match the platform's expected file extension
            if member.name.endswith(platform_files[platform_name]):
                tar_file.extract(member, path=hbase_dir)
                print(f"Extracted {member.name} to {hbase_dir}")


