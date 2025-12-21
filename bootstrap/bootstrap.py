import argparse
import logging
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
    parser.add_argument('--list-apps', action='store_true')
    parser.add_argument('--api-version', type=int, default=0)
    parser.add_argument('--restart-iter', type=int, default=0)
    parser.add_argument('--default-install-dir', action='store_true')
    parser.add_argument('--to-prod', action='store_true')

    # Server arguments (will be passed through)
    parser.add_argument('--host', default="127.0.0.1")
    parser.add_argument('--port', type=int, default=49990)
    parser.add_argument('--keep-alive', action='store_true')
    parser.add_argument('--devmode', action='store_true')
    parser.add_argument('--log-file', type=str, default=None)
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Set the logging level'
    )

    args = parser.parse_args()

    # Setup logging
    logging.addLevelName(logging.DEBUG, "[D]")
    logging.addLevelName(logging.INFO, "[I]")
    logging.addLevelName(logging.WARNING, "[W]")
    logging.addLevelName(logging.ERROR, "[E]")
    logging.addLevelName(logging.CRITICAL, "[C]")

    log_kwargs = {
        "level": getattr(logging, args.log_level.upper()),
        "format": '%(asctime)s - %(name)s - %(levelname)s %(message)s',
        "datefmt": '%Y-%m-%d %H:%M:%S',
    }

    if args.log_file:
        log_kwargs["filename"] = args.log_file
        log_kwargs["filemode"] = "a"
    else:
        log_kwargs["stream"] = sys.stderr

    logging.basicConfig(**log_kwargs)
    logger = logging.getLogger("bootstrap")

    # When restarting
    if args.restart_iter >= 3:
        sys.stdout.flush()
        sys.exit(1)

    if args.restart_iter > 1:
        time.sleep(1)

    # Installation directory
    this_dir: Path = Path(__file__).parent
    hbase_dir = this_dir
    module_dir = hbase_dir / "modules"
    app_install_dir: Path = this_dir.parent

    # Application
    app: str = args.app
    app_entry: Path = (
        app_install_dir / app / "wss.py"
        if app != 'hwss'
        else module_dir / "hwss" / "wss.py"
    )

    # Frontend specifies its api version.
    # if not provided, we will use the installed one.
    # if hbase not installed, use the latest available
    fe_api_version: int | None = args.api_version

    # List applications and exit
    if args.list_apps:
        available: dict = get_installed_apps()
        if available:
            logger.info("Available app:")
            for app_name, api_version in available.items():
                logger.info(f"  - {app_name}: {'.'.join(map(str, api_version))}")
        else:
            logger.info("No servers found. Packages may not be installed yet.")
        return

    logger.info(f"Bootstrap starting: app={app}")
    logger.info(f"Dev to production: {args.to_prod}")
    logger.info("Installation directories:")
    logger.info(f"  hbase dir: {hbase_dir}")
    logger.info(f"  Modules: {module_dir}")
    logger.info(f"  App install dir: {app_install_dir}")
    logger.info(f"  FrontEnd API version: {fe_api_version}")

    # try:
    restart = fsm(
        app_name=app,
        app_install_dir=app_install_dir if app != 'hwss' else module_dir.parent,
        fe_api_version=fe_api_version,
        hbase_dir=hbase_dir,
        module_dir=module_dir,
        to_prod=args.to_prod,
    )
    # except Exception as e:
    #     logger.error(f"Exception while running fsm: {str(e)}")
    #     sys.exit(1)

    # Restart or launch the webserver
    if restart:
        # Preserve original arguments when restarting
        # TODO: this has to be handled by the frontend
        # if devmode, it's safe to restart[1:]
        executable = sys.executable
        cmd_args = (
            [executable, sys.argv[0]]
            + remove_restart_iter(sys.argv[1:])
        )
        cmd_args.extend(["--restart-iter", str(args.restart_iter + 1)])

        logger.info(f"Restarting with args: {cmd_args}")
        sys.stdout.flush()
        os.execv(executable, cmd_args)

    else:
        if not app_entry.exists():
            logger.error(f"Server file not found: {app_entry}")
            sys.exit(1)

        try:
            sys.argv.remove("--to-prod")
        except:
            pass

        # Use run_path, and convert Path to str for compatibility

        # Add modules/ to sys.path (not hwss/)
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
        logger.info(f"module_dir: {module_dir}")
        logger.info(f"sys.path:\n  {'\n  '.join(map(str, sys.path))}")

        logger.info(f"Starting app: {app_entry}")
        logger.info(f"Starting app with args: {sys.argv[1:]}")
        runpy.run_module('hwss.wss', run_name='__main__')

        # runpy.run_path(str(app_entry), run_name='__main__')


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    main()
