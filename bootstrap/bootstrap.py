import argparse
import os
from pathlib import Path
import re
import runpy
import signal
import sys
import time

from bootstrap_helpers import (
    get_install_dir,
    get_installed_apps,
    fsm,
    remove_restart_iter,
)

def main():
    parser = argparse.ArgumentParser()

    # Bootstrap-specific arguments
    parser.add_argument('--app', type=str, default='hwss')
    parser.add_argument('--skip-update', action='store_true')
    parser.add_argument('--list-apps', action='store_true')
    parser.add_argument('--api-version', type=str, default="")
    parser.add_argument('--restart-iter', type=int, default=0)
    parser.add_argument('--default-install-dir', action='store_true')

    # Server arguments (will be passed through)
    parser.add_argument('--host', default="127.0.0.1")
    parser.add_argument('--port', type=int, default=49990)
    parser.add_argument('--keep-alive', action='store_true')
    parser.add_argument('--devmode', action='store_true')
    parser.add_argument('--log-file', type=str, default=None)

    args = parser.parse_args()

    # When restarting
    if args.restart_iter >= 3:
        sys.stdout.flush()
        sys.exit(1)

    if args.restart_iter > 1:
        time.sleep(1)

    # devmode
    devmode: bool = args.devmode

    # Installation directory
    # This won't work in dev mode
    this_dir: Path = Path(__file__).resolve().parent
    app_install_dir: Path = this_dir.parent
    hbase_dir = this_dir
    hwss_dir = hbase_dir / "modules" / "hwss"
    if devmode:
        # Use the local repos
        print("devmode")
        app_install_dir = this_dir.parent.parent
        hwss_dir = this_dir.parent / "hwss"
        hbase_dir = get_install_dir() / "python"

    elif args.default_install_dir:
        print("User defined installation path (debug only)")
        org_install_dir = get_install_dir()
        app_install_dir = org_install_dir
        hbase_dir = org_install_dir / "python"
        hwss_dir = org_install_dir / "python" / "modules" / "hwss"

    # Application
    app: str = args.app
    app_entry: Path = (
        app_install_dir / app / "wss.py"
        if app != 'hwss'
        else hwss_dir / "wss.py"
    )

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
        sys.exit(1)

    # List applications and exit
    if args.list_apps:
        available: dict = get_installed_apps()
        if available:
            print("Available app:")
            for app_name, api_version in available.items():
                print(f"  - {app_name}: {'.'.join(api_version)}")
        else:
            print("No servers found. Packages may not be installed yet.")
        return

    print(f"Bootstrap starting: app={app}")
    print("Installation directories:")
    print(f"  app_install_dir: {app_install_dir}")
    print(f"  hbase: {hbase_dir}")
    print(f"  hwss: {hwss_dir}")
    print(f"  FrontEnd API version: {fe_api_version}")

    try:
        restart = fsm(
            app=app,
            app_install_dir=app_install_dir,
            fe_api_version=fe_api_version,
            hbase_dir=hbase_dir,
            hwss_dir=hwss_dir,
            devmode=devmode,
        )
    except Exception as e:
        print(f"Exception while running fsm: {str(e)}")
        sys.exit(1)

    # Restart or launch the webserver
    if restart:
        # Preserve original arguments when restarting
        # TODO: this has to be handled by the frontend
        # if devmode, it's safe to restart
        executable = sys.executable
        cmd_args = (
            [executable, sys.argv[0]]
            + remove_restart_iter(sys.argv[1:])
        )
        cmd_args.extend(["--restart-iter", str(args.restart_iter + 1)])

        print(f"Restarting with args: {cmd_args}")
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
