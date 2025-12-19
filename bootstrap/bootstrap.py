import argparse
from enum import IntEnum
from pprint import pprint
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path
import os
import re
import runpy

from bootstrap_helpers import (
    download_file,
    find_latest_hbase_for_api_major,
    get_api_version,
    get_install_dir,
    get_installed_apps,
    is_github_alive,
    extract_filtered_lib,
)


class _FSM(IntEnum):
    INIT = 0
    UPDATE_HBASE = 1
    INSTALL_APP = 2
    UPDATE_APP = 3
    ENDED = 4
    CRITICAL = 5



def main():
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
        sys.stdout.flush()
        sys.exit(-1)

    if args.restart_iter > 1:
        time.sleep(1)

    # devmode
    devmode: bool = args.devmode

    # --- PATH DETECTION LOGIC MODIFIED FOR CYTHON ---
    # Determine if we are running as a compiled binary or a script
    # If compiled via cython --embed, sys.executable points to the binary
    # If standard python, sys.executable points to /usr/bin/python3
    is_compiled = (sys.executable == os.path.abspath(sys.argv[0]))

    if is_compiled:
        # We are running as a binary. The "this_dir" is where the binary sits.
        this_dir = Path(sys.executable).resolve().parent
    else:
        # Standard script execution
        this_dir = Path(__file__).resolve().parent

    # Installation directory
    # This won't work in dev mode
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
        available: dict = get_installed_apps()
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
    fsm_state = _FSM.INIT
    while fsm_state != _FSM.ENDED:
        print(_FSM(fsm_state))

        if fsm_state == _FSM.INIT:
            # Compare frontend api version vs backend

            be_api_version = get_api_version(app, app_install_dir=app_install_dir)
            print(f"{app}: be_api_version: {be_api_version}")
            print(f"{app}: fe_api_version: {fe_api_version}")
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
                print("Not compatible API version. Update frontend.")
                sys.exit(-2)

            else:
                print("unknow event")
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
                    extract_filtered_lib(archive_path=archive_path, hbase_dir=hbase_dir)
                except:
                    print("failed to install hbase")
                    sys.exit(-1)

                # Because a new version has been installed, restart
                restart = True
                fsm_state = _FSM.ENDED


        elif fsm_state == _FSM.ENDED:
            break

        # Restart or launch the webserver
        if restart:
            # Preserve original arguments when restarting
            # TODO: this has to be handled by the frontend
            # if devmode, it's safe to restart

            # Filter out existing restart-iter to avoid stacking
            current_args = [arg for arg in sys.argv[1:] if not arg.startswith('--restart-iter')]
            if is_compiled:
                # Running as standalone binary (./bootstrap)
                executable = sys.executable
                cmd_args = [executable] + current_args
            else:
                # Running as script (python bootstrap.py)
                executable = sys.executable
                cmd_args = [executable, sys.argv[0]] + current_args

            cmd_args.extend(["--restart-iter", str(args.restart_iter + 1)])

            print(f"Restarting with args: {cmd_args}")
            sys.stdout.flush()
            sys.stdout.flush()
            os.execv(executable, cmd_args)

        else:
            if not app_entry.exists():
                print(f"\nERROR: Server file not found: {app_entry}")
                sys.exit(1)

            # Use run_path, and convert Path to str for compatibility
            runpy.run_path(str(app_entry), run_name='__main__')


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    main()
