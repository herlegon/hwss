from enum import Enum
from http import client
import logging
import os
import socket
import threading
from packaging.version import Version
from pathlib import Path
from pprint import pprint
import re
import subprocess
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
import urllib.request
from hytils import red

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



def get_releases(timeout: float = 4.) -> list[dict[str, str | tuple]]:
    url = "https://api.github.com/repos/herlegon/hbase/releases"
    retry: int = 3

    response = [None]
    def _get_response():
        try:
            response[0] = requests.get(url, timeout=timeout)
        except Exception as e:
            logger.debug(f"Github nor reachable. {str(e)}")

    while retry:
        thread = threading.Thread(target=_get_response, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        if response[0] is not None:
            break
        logger.debug(f"Retry")
        retry -= 1
        time.sleep(0.5)

    if response[0] is None:
        logger.warning(f"failed to fetch the list of release.")
        return []

    response_releases: dict = response[0].json()

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
                    'version': (api, bootstrap, (hinstall//100, hinstall%100)),
                    'url': asset['browser_download_url']
                })

    return releases



def find_latest_hbase_for_api(
    releases: list,
    api: int = 0,
    major: int = 0,
) -> dict[str, str | tuple[int]] | None:
    # Helper to extract components for sorting/filtering
    # Returns (api, major, minor, bootstrap)
    def get_components(r):
        v = r['version']
        return (v[0], v[2][0], v[2][1], v[1])

    # Filter by API
    if api != 0:
        releases = [r for r in releases if r['version'][0] == api]
        if not releases:
            return None
    else:
        # Find latest API
        max_api = max(releases, key=lambda r: r['version'][0])['version'][0]
        releases = [r for r in releases if r['version'][0] == max_api]

    # Filter by Major
    if major != 0:
        releases = [r for r in releases if r['version'][2][0] == major]
        if not releases:
            return None
    else:
        # Find latest Major within the filtered releases
        max_major = max(releases, key=lambda r: r['version'][2][0])['version'][2][0]
        releases = [r for r in releases if r['version'][2][0] == max_major]

    # Sort by (api, major, minor, bootstrap) descending.
    # This prioritizes minor version over bootstrap version.
    return max(releases, key=get_components)



def is_connected(timeout: float = 1.2):
    result = [False]
    def _check():
        try:
            socket.getaddrinfo("www.google.com", 80)
            result[0] = True
        except:
            pass
    thread = threading.Thread(target=_check, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    return result[0]



def is_github_alive(
    timeout: float = 1,
    sleep_duration: float=0.5,
) -> bool:
    url = "https://api.github.com"
    retry: int = 3

    result = [False]
    def _check():
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            result[0] = True
        except Exception as e:
            logger.debug(f"Github nor reachable. {str(e)}")

    while retry:
        thread = threading.Thread(target=_check, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        if result[0]:
            return True
        retry -= 1
        time.sleep(sleep_duration)

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



def install_hbase(
    archive_path: Path,
    hbase_dir: Path,
    is_in_dev: bool,
    to_prod: bool = False
):
    platform_lib_ext = {
        'linux': '.so',
        'darwin': '.dylib',
        'win32': '.pyd',
    }

    # Detect current platform
    platform = sys.platform.lower()
    if platform.startswith('linux'):
        lib_ext = platform_lib_ext['linux']
    elif platform.startswith('darwin'):
        lib_ext = platform_lib_ext['darwin']
    elif platform.startswith('win'):
        lib_ext = platform_lib_ext['win32']
    else:
        logger.error(f"Unsupported platform: {platform}")
        sys.exit(-1)

    do_install: bool = to_prod or not is_in_dev

    # Remove hbase_dir / bootstrap*:
    if hbase_dir.exists():
        for item in hbase_dir.iterdir():
            if item.name.startswith("bootstrap"):
                if not do_install:
                    logger.debug(f"Remove {item.name}")
                    continue

                if item.is_symlink():
                    logger.debug(f"Removing symlink {item.name}")
                    item.unlink()

                elif not is_in_dev:
                    logger.debug(f"Removing file {item.name}")
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()

    modules = ("hwss", "hinstall")
    modules_dir = hbase_dir / "modules"

    if modules_dir.exists():
        for m in modules:
            module_path = modules_dir / m
            if module_path.exists():
                if not do_install:
                    logger.debug(f"(dry-run) remove {module_path}")
                    continue

                if module_path.is_symlink():
                    logger.debug(f"Removing symlink {module_path}")
                    module_path.unlink()

                elif not is_in_dev:
                    logger.debug(f"Removing directory {module_path}")
                    if module_path.is_dir():
                        shutil.rmtree(module_path)
                    else:
                        module_path.unlink()

    # Install hbase_dir / bootstrap*:
    # Extract the bootstrap* and modules from the archive: filter by platform
    logger.info(f"Extracting {archive_path} to {hbase_dir}")

    # Define extensions to exclude (other platforms)
    excluded_exts = {ext for p, ext in platform_lib_ext.items() if ext != lib_ext}

    def should_extract(member: tarfile.TarInfo) -> bool:
        if member.isdir():
            return True

        name = member.name.lower()
        # Check if it ends with an excluded extension
        for ext in excluded_exts:
            if name.endswith(ext):
                return False
        return True

    with tarfile.open(archive_path, "r:gz") as tar:
        members = [m for m in tar.getmembers() if should_extract(m)]

        bootstrap_members: list[tarfile.TarInfo] = []
        modules_members: list[tarfile.TarInfo] = []

        for m in members:
            if os.path.basename(m.name).startswith("bootstrap"):
                bootstrap_members.append(m)
            else:
                modules_members.append(m)

        # Extract non-bootstrap files first
        if modules_members:
            if not do_install:
                logger.debug(f"(dry-run) install:\n  {"\n  ".join([m.name for m in modules_members])}")
            else:
                tar.extractall(path=hbase_dir, members=modules_members)

        # Extract bootstrap files last (as a completion flag)
        if bootstrap_members:
            if not do_install:
                logger.debug(f"(dry-run) install:\n  {"\n  ".join([m.name for m in bootstrap_members])}")
            else:
                tar.extractall(path=hbase_dir, members=bootstrap_members)



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
    is_in_dev: bool = False,
    keep_up_to_date: bool = True,
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
        hinstall_version = hbase_version[2]
    app_api_version: int = 0
    if app_hbase_version:
        app_api_version = app_hbase_version[0]
    logger.info(f"hbase version: {hbase_version}")
    logger.info(f"hbase API version: {hbase_api_version}")
    logger.info(f"{app_name}: requested API version by frontend: {fe_api_version}")
    logger.info(f"{app_name}: installed API version: {app_api_version}")
    logger.info(f"{app_name}: installed app version: {app_version}")

    is_hbase_installed: bool = all([x is not None for x in hbase_version])
    logger.debug(f"hbase installed: {is_hbase_installed}")

    # If not connected to the internet
    if not is_connected():
        logger.warning(f"Failed to ping an internet website, offline")
        # Check that frontend and backend are compatible:
        # same API, same hinstall major
        if not is_hbase_installed:
            logger.critical(f"Install is corrupted")
            sys.exit()

        if not fe_api_version:
            logger.info(f"update: no frontend API version specified and no internet")
            sys.exit()

        if fe_api_version == app_api_version == hbase_api_version:
            logger.debug("No internet, API is compatible, ok to start")
            return restart

    # If not release found: when github is down or wrong server
    releases = get_releases(timeout=2)
    if not releases:
        logger.error("No release found")
        if not is_hbase_installed:
            logger.critical(f"Install is corrupted")
            sys.exit()

        if fe_api_version == app_api_version == hbase_api_version:
            # Let's start
            logger.debug("No release found, API is compatible, ok to start")
            return restart

    do_update: bool = False
    if app_name == 'hwss':
        logger.debug(f"update: requested app is hwss")
        do_update = True

    elif not app_api_version:
        logger.debug(f"update: {app_name} is not installed")
        do_update = True

    elif fe_api_version == 0:
        logger.info(f"update: no frontend API version specified")
        do_update = True

    else:
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
        elif app_api_version > hbase_api_version:
            logger.info(f"App use an older API version.")
            logger.warning("Not compatible API version. hbase will be updated first")
            do_update = True

        # Application use an older API version
        # if app_api_version[0] < hbase_api_version:
        #     logger.info(f"App use an older API version.")
        #     fsm_state = _FSM.UPDATE_HBASE
        #     continue

        logger.info("Start application because API is compatible")

    if do_update:
        logger.debug(f"releases:\n    {"\n    ".join(repr(r) for r in releases)}")
        if to_prod:
            hbase_release = find_latest_hbase_for_api(releases)
        else:
            hbase_release = find_latest_hbase_for_api(releases, api=fe_api_version)

        if hbase_release is None:
            logger.warning(f"Failed to find the latest version for api={fe_api_version}")
            if fe_api_version == app_api_version == hbase_api_version:
                # Let's start
                logger.debug("No release found, API is compatible, ok to start")
                return False
            sys.exit()

        logger.debug(f"Release for api={fe_api_version}: {hbase_release}")

        r_api, r_bootstrap, _r_hinstall = hbase_release['version']
        r_hinstall = _r_hinstall[0] * 100 + _r_hinstall[1]
        # Not need to update if already on the latest version
        if (
            r_api == hbase_api_version
            and r_hinstall == hinstall_version
        ):
            # no need to update if already on the latest version
            if r_bootstrap == hbase_version[1]:
                logger.debug("Already on latest released version.")
                return False

    # Download and extract archive
    if do_update:
        archive_url = hbase_release['url']
        archive_filename = os.path.basename(archive_url)
        if not archive_url:
            logger.critical("Not a valid file to download")
            sys.exit()

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
                logger.critical(f"Failed to download {archive_url}")
                sys.exit(-1)

            # Install
            try:
                install_hbase(
                    archive_path=archive_path,
                    hbase_dir=hbase_dir,
                    is_in_dev=is_in_dev,
                    to_prod=to_prod
                )
            except Exception as e:
                logger.error(f"failed to install hbase. {str(e)}")
                sys.exit(-1)

            # Do not restart if in dev mode
            if is_in_dev and not to_prod:
                logger.debug("in in dev mode and not switching to prod")
                return False

            # Because a new version has been installed, restart
            restart = True

    return restart
