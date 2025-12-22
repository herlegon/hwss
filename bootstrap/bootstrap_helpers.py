from enum import Enum
from http import client
import logging
import os
from packaging.version import Version
from pathlib import Path
from pprint import pprint
import re
import subprocess
import tarfile
import tempfile
import time
import requests
import sys
import urllib
from urllib.error import (
    URLError,
    HTTPError,
)

logger = logging.getLogger("bootstrap")


def get_local_versions(
    hbase_dir: Path,
    module_dir: Path,
    app_install_dir: Path,
    app_name: str,
) -> tuple[tuple[int, int, int | tuple[int, int]] | None, ...]:
    """Returns hbase_version, app_api_version, app_version
        - hbase version:
            x.y.zzz with
                x = __api_version__ in hwss/api.py
                y = __api_version__ in ./bootstrap.py
                zzz = __version__ in hinstall/api.py
        - application API version
            x.r.ttt = __api_version__ in app_install_dir/app/__init__.py
        - application version
            a.b.c = __version__ in app_install_dir/app/__init__.py

        in bootstrap/hbase: we don't care of "r, ttt, a, b, c"
        application versions are just for debug
    """
    hbase_version = None
    api_version = None
    hinstall_version = None
    app_hbase_version = None
    app_version = None

    api_version_fp: Path = module_dir / "hwss" / "api.pyx"
    if not api_version_fp.exists():
        api_version_fp: Path = module_dir / "hwss" / "api.py"

    bootstrap_version_fp: Path = hbase_dir / "bootstrap.py"
    hinstall_version_fp: Path = module_dir / "hinstall" / "__init__.py"
    app_version_fp: Path = app_install_dir / app_name / "__init__.py"
    # logger.debug(f"search {app_name} versions in {app_version_fp}")
    # logger.debug(f"search API version in {api_version_fp}")
    # logger.debug(f"search boostrap version in {bootstrap_version_fp}")
    # logger.debug(f"search hinstall version in {hinstall_version_fp}")
    # logger.debug(f"search app / app API version in {app_version_fp}")

    for version_fp in (
        api_version_fp,
        bootstrap_version_fp,
        hinstall_version_fp,
        app_version_fp
    ):
        if not version_fp.exists():
            continue
        try:
            content = version_fp.read_text(encoding='utf-8')
            for line in content.split('\n'):
                for version_str in ('__version__', '__api_version__'):
                    if line.strip().startswith(version_str) and '=' in line:
                        value = line.split('=', 1)[1].strip().strip('"\'')
                        if match := re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", value):
                            major = int(match.group(1))
                            minor = int(match.group(2)) if match.group(2) else 0
                            build = int(match.group(3)) if match.group(3) else 0
                            if version_fp == api_version_fp:
                                api_version = major
                                break
                            elif version_fp == bootstrap_version_fp:
                                bootstrap_version = major
                                break
                            elif version_fp == hinstall_version_fp:
                                hinstall_version = 100 * major + minor
                                break
                            elif version_fp == app_version_fp:
                                if version_str == '__version__':
                                    app_version = (major, minor, build)
                                elif version_str == '__api_version__':
                                    app_hinstall_major, app_hinstall_minor = build // 100, build %100
                                    # api, bootstrap, hinstall
                                    app_hbase_version = (
                                        major, minor, (app_hinstall_major, app_hinstall_minor)
                                    )

        except Exception as e:
            print(f"Warning: Could not read version from {version_fp}: {e}")

    hbase_version: tuple = (api_version, bootstrap_version, hinstall_version)

    return hbase_version, app_hbase_version, app_version



def get_glibc_version():
    try:
        output = subprocess.check_output(
            ["ldd", "--version"],
            stderr=subprocess.STDOUT,
            text=True
        )
    except Exception as e:
        raise RuntimeError(f"Failed to run ldd: {e}")

    # Extract version number (e.g., 2.35)
    match = re.search(r"(\d+\.\d+)", output)
    if not match:
        raise RuntimeError("Could not determine GLIBC version")

    return Version(match.group(1))



def get_installed_apps(app_install_dir: Path) -> dict[str, tuple[int, int]]:
    """List all available applications installed: they all have a wss
    """
    apps = None
    # # Find all directories that contains a websocket server
    # apps: dict[str, tuple[int, int]] = {}
    # for item in app_install_dir.iterdir():
    #     if (
    #         item.is_dir()
    #         and (item / "wss.py").exists()
    #         and (item / "__init__.py").exists()
    #     ):
    #         app_name = item.name
    #         hbase_version, app_api_version, app_version = get_local_versions(
    #             app_name=app_name,
    #             app_install_dir=app_install_dir,
    #             hinstall_dir=app_install_dir / "python" / "modules" / "hinstall",
    #             hwss_dir=app_install_dir / "python" / "modules" / "hwss",
    #         )
    #         if app_version is not None:
    #             apps[app_name] = (hbase_version, app_api_version, app_version)

    return apps



def get_releases() -> list[dict[str, str | tuple]]:
    """Find latest hbase package for specific API major version (any minor/patch)"""

    # Get all releases
    url = "https://api.github.com/repos/herlegon/hbase/releases"
    try:
        response = requests.get(url, timeout=10)
    except Exception as e:
        logger.warning(f"failed to fetch the list of release. {str(e)}")
        return []

    response_releases = response.json()

    # Pattern: hbase-{api}.{hinstall_major}.{hinstall_minor}.tar.gz
    pattern = r"hbase-(\d+)\.(\d+)\.(\d+)\.tar\.gz"
    releases: list[dict] = []
    for release in response_releases:
        for asset in release['assets']:
            match = re.match(pattern, asset['name'])
            if match:
                api = int(match.group(1))
                bootstrap = int(match.group(2))
                hinstall = int(match.group(3))
                releases.append({
                    'version': (api, bootstrap, (hinstall//100, hinstall%100)
                    ),
                    'url': asset['browser_download_url']
                })

    return releases





def find_latest_hbase_for_api(api: int = 0) -> dict[str, int | str | tuple] | None:
    """Find latest hbase package for specific API major version (any minor/patch)"""

    # Get all releases
    url = "https://api.github.com/repos/herlegon/hbase/releases"
    try:
        response = requests.get(url, timeout=10)
    except Exception as e:
        logger.warning(f"failed to fetch the list of release. {str(e)}")
        return None

    releases = response.json()

    # Pattern: hbase-{api}.{hinstall_major}.{hinstall_minor}.tar.gz
    if not api:
        logger.debug(f"find latest version")
        pattern = r"hbase-(\d+)\.(\d+)\.(\d+)\.tar\.gz"
        compatible = []
        for release in releases:
            for asset in release['assets']:
                match = re.match(pattern, asset['name'])
                if match:
                    api = int(match.group(1))
                    major = int(match.group(2))
                    minor = int(match.group(3))
                    compatible.append({
                        'version': (api, major, minor),
                        'api': api,
                        'hinstall': (major, minor),
                        'url': asset['browser_download_url']
                    })

        if not compatible:
            return None

        # Sort by major, minor, and patch (desc) to get the latest overall release
        compatible.sort(key=lambda x: (x['api'], *x['hinstall']), reverse=True)
        return compatible[0]

    else:
        logger.debug(f"find latest version for api={api}")
        pattern = rf"hbase-{api}\.(\d+)\.(\d+)\.tar\.gz"
        compatible = []
        for release in releases:
            for asset in release['assets']:
                match = re.match(pattern, asset['name'])
                if match:
                    api = int(match.group(1))
                    major = int(match.group(2))
                    minor = int(match.group(3))
                    full_version = f"{api}.{major}.{minor}"
                    compatible.append({
                        'version': full_version,
                        'api': api,
                        'hinstall': (major, minor),
                        'url': asset['browser_download_url']
                    })

        if not compatible:
            return None
        # Sort by minor (desc), then patch (desc) to get latest
        compatible.sort(key=lambda x: x['hinstall'], reverse=True)
        return compatible[0]



def is_github_alive() -> bool:
    url = "https://api.github.com"
    retry: int = 3
    while retry:
        try:
            response = requests.get(url, timeout=1)
            response.raise_for_status()
            return True

        except requests.exceptions.RequestException as e:
            logger.debug(f"Github nor reachable. {str(e)}")
        retry -= 1
        time.sleep(1)

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
        logger.error(f"Download failed: {str(e)}")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {str(e)}")
        return False

    logger.info(f"Successfully downloaded")
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
        extraction_dir = hbase_dir / "tmp"
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
        if (
            args[i] == '--restart-iter'
            and i + 1 < len(args)
            and args[i + 1].isdigit()
        ):
            i += 2
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
    fe_api_version: int,
    hbase_dir: Path,
    module_dir: Path,
    to_prod: bool = False,
    is_in_dev: bool = False
) -> bool:
    restart: bool = False

    # First, get the api version of the hbase (bootstrap + hwss + hinstall)
    (
        hbase_version,
        app_hbase_version,
        app_version,
    ) = get_local_versions(
        hbase_dir=hbase_dir,
        module_dir=module_dir,
        app_install_dir=app_install_dir,
        app_name=app_name,
    )
    hbase_api_version: int = 0
    hbase_version: tuple[int, int, int]
    if hbase_version:
        hbase_api_version = hbase_version[0]
    app_api_version: int = 0
    if app_hbase_version:
        app_api_version = app_hbase_version[0]
    logger.info(f"hbase version: {hbase_version}")
    logger.info(f"hbase API version: {hbase_api_version}")
    logger.info(f"{app_name}: requested API version by frontend: {fe_api_version}")
    logger.info(f"{app_name}: installed API version: {app_api_version}")
    logger.info(f"{app_name}: installed app version: {app_version}")


    # If not connected to the internet
    if not is_github_alive():
        logger.warning(f"GitHub API is not reachable, offline")
        # Check that frontend and backend are compatible:
        # same API, same hinstall major
        if not fe_api_version:
            logger.info(f"update: no frontend API version specified and no internet")
            sys.exit()

        if (
            fe_api_version == app_api_version
            and fe_api_version == app_api_version
            and fe_api_version == app_api_version
        ):
        hinstall_version_major = app_hbase_version[2]




    fsm_state = _FSM.INIT
    while fsm_state != _FSM.ENDED:

        if fsm_state == _FSM.INIT:
            # default
            fsm_state = _FSM.ENDED

            is_hbase_installed: bool = all([x is not None for x in hbase_version])
            logger.debug(f"hbase installed: {is_hbase_installed}")
            if not is_hbase_installed:
                # At least a component is not installed yet (hwss, hinstall, bootstrap)
                fsm_state = _FSM.UPDATE_HBASE
                continue

            # If app is hwss, update it
            if app_name == 'hwss':
                logger.debug(f"update: requested app is hwss")
                fsm_state = _FSM.UPDATE_HBASE
                continue

            # Application is not installed
            if not app_api_version:
                logger.debug(f"update: {app_name} is not installed")
                fsm_state = _FSM.UPDATE_HBASE
                continue

            # No frontend API version
            if fe_api_version == 0:
                logger.info(f"update: no frontend API version specified")
                fsm_state = _FSM.UPDATE_HBASE
                continue

            logger.debug(f"{app_name} is installed")
            # Application use an older frontend, cannot continue because
            # downgrading is not allowed
            if (
                fe_api_version < hbase_api_version
                or fe_api_version < app_api_version
            ):
                logger.info(f"update: frontend is lower than hbase/app API version")
                logger.critical("Frontend is too old for installed backend.")
                sys.exit()

            # Application use a newer API version -> hbase to be updated
            if app_api_version > hbase_api_version:
                logger.info(f"App use an older API version.")
                logger.warning("Not compatible API version. hbase will be updated first")
                fsm_state = _FSM.UPDATE_HBASE
                continue

            # Application use an older API version
            # if app_api_version[0] < hbase_api_version:
            #     logger.info(f"App use an older API version.")
            #     fsm_state = _FSM.UPDATE_HBASE
            #     continue

            logger.info("Start application because API is compatible")


        elif fsm_state == _FSM.UPDATE_HBASE:
            retry = 3
            hbase_release: dict | None = None
            while retry:
                try:
                    if to_prod:
                        hbase_release = find_latest_hbase_for_api()
                    else:
                        hbase_release = find_latest_hbase_for_api(api=fe_api_version)

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


            r_api_version = hbase_release['version'][0]
            r_hinstall_version = (
                hbase_release['version'][2] // 100,
                hbase_release['version'][2] % 100,
            )



            logger.info(f"release version: {'.'.join(map(str, hbase_release['version']))}")
            logger.info(f"release API: {r_api_version}")
            logger.info(f"release hinstall: {r_hinstall_version}")

            # if not to_prod and hbase_version:
            #     # release version is higher
            #     if not hbase_release['version'] > hbase_version:
            #         logger.info("Already the latest version")
            #         fsm_state = _FSM.ENDED
            #         continue

            #     # release has a higher api version
            #     if not hbase_release['api'] > hbase_api_version:
            #         logger.info("")
            #         fsm_state = _FSM.ENDED
            #         continue

            #     # or higher hinstall version
            #     if not hbase_release['hinstall'] > tuple(hbase_version[1:]):
            #         fsm_state = _FSM.ENDED
            #         continue

            if to_prod or not is_in_dev:

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
                            force_prod=to_prod
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
