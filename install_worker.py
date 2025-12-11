from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
from pprint import pprint
import queue
import signal
import sys
import time
from hytils import lightcyan, lightgreen, purple, red, yellow
from logger import setup_worker_logger, slog
from api import InstallProgress, InstallTaskResult, WorkerResponse
import multiprocessing as mp
from multiprocessing.synchronize import Event
from typing import Literal

try:
    from hinstall import __version__

except:
    dev_dir: str = str(Path(__file__).resolve().parent.parent / "hinstall")
    # slog.warning(f"Import hinstall from dev directory: {dev_dir}")
    sys.path.append(dev_dir)

try:
    from hinstall import (
        ExtPackages,
        PyPackages,
        PyPackage,
        download_install_ext_packages,
        g_backend_dirs,
        parse_config_,
    )
except Exception as e:
    print(red(f"Failed to import hinstall package: {str(e)}"))




from api import (
    EventMessage,
    InstallTaskId,
    ParseTask,
    InstallTask,
    ResponseMessage,
    MessageType,
)


class InstallWorker(mp.Process):
    """Worker process that executes long-running tasks"""
    def __init__(
        self,
        task_queue: mp.Queue,
        result_queue: mp.Queue,
        stop_event: Event,
        log_queue: mp.Queue,
        worker_name: str = "install",
        devmode: bool = False,
    ):
        super().__init__(
            name=worker_name
        )
        self.worker_name: str = worker_name

        self.task_queue: mp.Queue = task_queue
        self.result_queue: mp.Queue = result_queue
        self.stop_event: Event = stop_event
        self.log_queue: mp.Queue = log_queue

        # Logger will be set up in run() after process starts
        # otherwise, it's not running in the process
        self.log: logging.Logger = None
        self.devmode: bool = devmode

        self.daemon = True

        self.cache: bool = True
        self.reinstall: bool = False
        self.use_local_rehost: bool = True
        self.local_rehost: str = ""
        self.keep_up_to_date: bool = False
        self.app_packages : dict[str, str] = {}
        self.py_packages: PyPackages = None


    def run(self):
        # Ignore KeyboardInterrupt inside the worker
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        # Setup worker logger (must be done inside run(), after process starts)
        self.log, self.hinstall_ws_handler = setup_worker_logger(
            worker_name=self.worker_name,
            emit_queue=self.result_queue,
            log_queue=self.log_queue,
            devmode=self.devmode
        )

        self.log.debug(purple(f"[{self.pid}] worker process started"))

        while not self.stop_event.is_set():

            try:
                data: dict = self.task_queue.get(timeout=0.2)
                task_id: InstallTaskId = data['task_id']

                # Route to appropriate task handler
                if task_id == 'stop':
                    self.log.debug(purple(f"[{self.pid}] received stop command"))
                    break

                elif task_id == 'parse':
                    task: ParseTask = ParseTask(**data)
                    self.log.debug(f"Parse toml for {task.app_name}")
                    self.handle_parse_cfg(task)

                elif task_id == 'install':
                    install_task: InstallTask = InstallTask(**data)
                    stage_no = install_task.stage
                    if stage_no == 0:
                        self.handle_install_ext_packages(install_task)

                    elif stage_no in (1, 2):
                        self.handle_install_py_packages(install_task)

                    else:
                        self.send(
                            InstallTaskResult(
                                task_id=task_id,
                                stage=-1,
                                status='error',
                                restart=False,
                            )
                        )

            except queue.Empty:
                continue

            except Exception as e:
                self.log.error(purple(f"[{self.pid}] uncaught exception: {str(e)}, data={data}"))
                self.log.critical(f"worker: {str(e)}")

        # Cleanup hinstall WebSocket handler
        if hasattr(self, 'hinstall_ws_handler') and self.hinstall_ws_handler:
            try:
                from hinstall.logger import ilog
                ilog.removeHandler(self.hinstall_ws_handler)
                self.log.debug(f"[{self.pid}] Removed WebSocket handler from hinstall logger")
            except Exception as e:
                self.log.warning(f"[{self.pid}] Failed to remove hinstall handler: {e}")

        self.log.debug(purple(f"[{self.pid}] ℹ️ terminated"))



    def do_stop(self) -> bool:
        """Check if task should stop"""
        return self.stop_event.is_set()


    def send(self, data: EventMessage | dict) -> None:
        """Send result back to server
        """
        if isinstance(data, EventMessage):
            self.result_queue.put(data)
        else:
            self.result_queue.put(
                ResponseMessage(type='install', payload=data)
            )



    def get_rehost_dir(self, organization: str = "herlegon") -> Path:
        local_package_dir: Path

        if sys.platform == "win32":
            local_package_dir = Path("A:\\") / organization / "rehost"

        elif sys.platform == "linux":
            local_package_dir = Path("/opt") / organization / "rehost"

        elif sys.platform == "darwin":
            local_package_dir = Path.home() / organization / "rehost"

        return local_package_dir



    def handle_parse_cfg(self, task: ParseTask) -> None:
        self.local_backend: bool = task.local_backend
        self.reinstall: bool = task.reinstall
        self.use_local_rehost: bool = task.use_local_rehost
        self.cache = task.cache

        self.log.info(f"Backend python: {str(g_backend_dirs.python_exe)}")
        toml_cfg = json.loads(task.cfg)
        self.app_packages = parse_config_(toml_cfg)

        msg: str = "\n  ".join([
            f"Install settings:"
            f"Local backend: {self.local_backend}",
            f"Reinstall: {self.reinstall}",
            f"Use local rehost for dl: {self.use_local_rehost}",
            f"Local rehost: {task.local_rehost}",
            f"Cache downloaded files: {self.cache}",
        ])
        self.log.debug(msg)

        if self.use_local_rehost:
            g_backend_dirs.local_rehost = (
                task.local_rehost if task.local_rehost
                else self.get_rehost_dir()
            )
        self.log.info(f"Use local rehost: {g_backend_dirs.local_rehost}")

        self.send({
            'task_id': task.task_id,
            'status': "parsed"
        })


    def handle_install_ext_packages(self, task: InstallTask) -> None:
        # Install the external packages if not local
        if self.local_backend:
            return

        # All packages except python
        ext_packages = ExtPackages(self.app_packages, sys.platform)
        packages_to_install = ext_packages.get_all_except('python')

        # Install external packages
        if packages_to_install:
            installed: bool = download_install_ext_packages(
                packages=packages_to_install,
                reinstall=self.reinstall,
                threads=1,
                use_local_rehost=self.use_local_rehost
            )
            if installed:
                self.log.info(lightgreen("All packages installed"))
            else:
                self.log.error(red("Error: missing package(s)"))
        else:
            self.log.error(lightgreen("No packages to install"))

        self.send(
            InstallTaskResult(
                task_id=task.task_id,
                stage=task.stage,
                status='installed' if installed else 'failed',
                restart=False,
            )
        )


    def handle_install_py_packages(self, task: InstallTask) -> None:
        success = False
        restart = False
        try:
            if task.stage == 1:
                success, restart = self.handle_install_py_packages_1st_stage()

            elif task.stage == 2:
                success, restart = self.handle_install_py_packages_2nd_stage()

        except Exception as e:
            self.log.critical(f"Exception: {str(e)}")

        self.send(
            InstallTaskResult(
                task_id=task.task_id,
                stage=task.stage,
                status='installed' if success else 'failed',
                restart=restart,
            )
        )


    def handle_install_py_packages_1st_stage(self) -> tuple[bool, bool]:
        # returns success & restart required
        self.py_packages = PyPackages(
            self.app_packages,
            sys.platform,
            keep_up_to_date=self.keep_up_to_date
        )

        # List all packages that are required before installing the AI computation resources
        initial_pkgs = self.py_packages.get_initial()
        to_install_pkgs = initial_pkgs.get_not_installed()
        if self.keep_up_to_date:
            self.log.debug(f"TODO: keep_up_to_date")

        # If all packages already installed, no need to restart
        if not to_install_pkgs:
            self.log.debug(f"Stage 1: all packages installed")
            return True, False

        return self._process_python_packages(to_install_pkgs, stage_no=1)


    def handle_install_py_packages_2nd_stage(self) -> tuple[bool, bool]:
        if self.py_packages is None:
            self.py_packages = PyPackages(
                self.app_packages,
                sys.platform,
                keep_up_to_date=self.keep_up_to_date
            )

        to_install_pkgs = self.py_packages.get_delayed()

        from hsys import is_feature_supported

        cuda = is_feature_supported('cuda')
        tensorrt = is_feature_supported('tensorrt')
        directml = is_feature_supported('directml')
        rocm = is_feature_supported('rocm')

        self.log.debug(f"CUDA: {'✅' if cuda else '❌'}")
        self.log.debug(f"TensorRT: {'✅' if tensorrt else '❌'}")
        self.log.debug(f"direct ML: {'✅' if directml else '❌'}")
        self.log.debug(f"RocM: {'✅' if rocm else '❌'}")

        for pkg in to_install_pkgs.get_by_execution_provider('cuda'):
            pkg.skip = not cuda
            pkg.supported = cuda

        for pkg in to_install_pkgs.get_by_execution_provider('rocm'):
            pkg.skip = not rocm
            pkg.supported = rocm

        for pkg in to_install_pkgs.get_by_execution_provider('directml'):
            pkg.skip = not directml
            pkg.supported = directml

        cpu_fallback = all([x is False for x in (cuda, tensorrt, rocm)])
        for pkg in to_install_pkgs.get_by_execution_provider('cpu'):
            pkg.skip = not cpu_fallback
            pkg.supported = cpu_fallback


        self.log.debug("supported packages")
        supported_pkgs = to_install_pkgs.get_delayed(supported_only=True)
        for pkg in supported_pkgs:
            self.log.debug(lightcyan(pkg.pretty_name))
            self.log.debug(f"Package details: {pkg}")

        return self._process_python_packages(supported_pkgs, stage_no=2)


    def _process_python_packages(self, packages: list[PyPackage], stage_no: int) -> tuple[bool, bool]:
        """
        Common logic to update info, download, and install a list of packages.
        """
        if not packages:
            return True, False

        # Use multithreading to update the packages info
        start_time = time.time()
        cpu_count = mp.cpu_count()
        cpu_count = max(cpu_count - 1, int(cpu_count * 4 / 5))
        with ThreadPoolExecutor(
            max_workers=min(cpu_count, len(packages))
        ) as executor:
            executor.map(lambda pkg: pkg.update_info(), packages)
        elapsed = time.time() - start_time
        self.log.info(f"Fetch package versions in {elapsed:.02f}s")

        # For debug
        self.log.info(f"Packages to process: {', '.join([p.name for p in packages])}")
        for pkg in packages:
            message: list[str] = "\n".join([
                f"{lightcyan(pkg.name)}:",
                f"    installed: {pkg.installed}",
                f"    latest version: {pkg.latest_version}",
                f"    selected: {pkg.version}",
                f"    variant: {pkg.variant}",
                f"    installed version: {pkg.installed_version}",
                f"    wheel: {pkg.wheel}",
                f"    wheel url: {pkg.wheel_url}",
                f"    size: {pkg.size // 1024}kB",
                f"    cache: {pkg.do_cache}",
            ])
            self.log.debug(message)
        self.log.debug(f"updated package list in {elapsed:.02f}s")

        # Filter packages that need installation
        to_install_pkgs = [pkg for pkg in packages if not pkg.installed]
        if not to_install_pkgs:
            return True, False

        # Download wheels
        dl_start_time = time.time()
        failed_packages: list[str] = []
        for pkg in to_install_pkgs:
            # Cache packages with size > 80MB
            if pkg.size > 80000 and self.cache:
                pkg.do_cache = True

            if pkg.do_cache:
                start_time = time.time()
                downloaded = pkg.download_wheel(
                    force=False,
                    use_pip=True if stage_no == 1 else False,
                    use_local_rehost=self.use_local_rehost
                )

                elapsed = time.time() - start_time
                if downloaded:
                    self.log.debug(f"Downloaded {pkg.name} in {elapsed:.02f}s")
                else:
                    failed_packages.append(pkg.name)
                    self.log.debug(f"Failed to download {pkg.name}")

        elapsed = time.time() - dl_start_time
        if failed_packages:
            self.log.critical(f"Failed to download package(s): {', '.join(failed_packages)}")
            return False, True
        else:
            self.log.info(f"Packages downloaded in {elapsed:.02f}s")

        # Install python packages
        self.log.progress(
            InstallProgress(
                package_name="",
                type='indet',
                progress=0,
            )
        )
        start_time = time.time()
        failed_packages: list[str] = []
        for pkg in to_install_pkgs:
            self.log.debug(f"Install {pkg.name} (reinstall={self.reinstall})")
            self.log.progress(InstallProgress(
                package_name=pkg.pretty_name, type='indet', progress=0
            ))
            pkg.install(reinstall=self.reinstall)

        elapsed = time.time() - start_time
        if failed_packages:
            self.log.error(f"Failed to install package(s): {', '.join(failed_packages)}")
            time.sleep(1.)
        else:
            self.log.info(f"Packages installed in {elapsed:.02f}s")

        # Retry packages
        if failed_packages:
            failed_packages: list[str] = []
            self.log.info(f"Retry installing missing packages.")
            # Update installed versions for all packages to check if retry is needed
            # (Wait, update_installed_versions is a method on PyPackages, but here we have a list)
            # We can just check pkg.installed after install(recover=True)
            to_install_pkgs.update_installed_versions()
            for pkg in to_install_pkgs:
                self.log.progress(InstallProgress(
                    package_name=pkg.pretty_name, type='indet', progress=0
                ))
                pkg.install(recover=True)
                if not pkg.installed:
                    failed_packages.append(pkg.pretty_name)
                    self.log.critical(f"Failed to install package {pkg.name}")

        success: bool = not failed_packages
        self.log.progress(InstallProgress(
            package_name="",
            type='indet',
            status='success' if success else 'failed',
            progress=100,
        ))

        return success, True
