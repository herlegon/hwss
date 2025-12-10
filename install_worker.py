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
from api import InstallProgress, WorkerResponse
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
        enable_stdout: bool = False,
    ):
        super().__init__(
            name=worker_name
        )
        self.worker_name: str = worker_name

        self.task_queue: mp.Queue = task_queue
        self.result_queue: mp.Queue = result_queue
        self.stop_event: Event = stop_event
        self.log_queue: mp.Queue = log_queue
        self.enable_stdout: bool = enable_stdout

        # Logger will be set up in run() after process starts
        # otherwise, it's not running in the process
        self.log = None

        self.daemon = True

        self.app: str = "hconvert"
        self.cache: bool = True
        self.reinstall: bool = False
        self.use_local_host: bool = True
        self.local_host: str = ""
        self.keep_up_to_date: bool = False
        self.packages_cfg : dict[str, str] = {}
        self.py_packages: PyPackages = None


    def run(self):
        # Ignore KeyboardInterrupt inside the worker
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        # Setup worker logger (must be done inside run(), after process starts)
        self.log, self.hinstall_ws_handler = setup_worker_logger(
            worker_name=self.worker_name,
            emit_queue=self.result_queue,
            log_queue=self.log_queue,
            enable_stdout=self.enable_stdout
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

                    if stage_no == 1:
                        self.handle_install_1st_stage(install_task)

                    elif stage_no == 2:
                        self.handle_install_2nd_stage(install_task)

                    else:
                        self.send({
                            'result': "error",
                            'msg': f"Not supported stage no: {stage_no}"
                        })

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
        toml_cfg = json.loads(task.cfg)

        self.local_backend: bool = task.local_backend
        self.reinstall: bool = task.reinstall
        self.use_local_host: bool = task.use_local_host
        self.local_host: str = task.local_host
        self.cache = task.cache

        self.log.info(f"Backend python: {str(g_backend_dirs.python_exe)}")
        self.packages_cfg = parse_config_(toml_cfg)

        # for i in range(10):
        #     self.log.progress(
        #         InstallProgress(
        #             task_id=task.task_id,
        #             type='progress',
        #             progress=10.*i
        #         )
        #     )
        #     time.sleep(0.5)


        self.send({
            'task_id': task.task_id,
            'status': "parsed"
        })



    def handle_install_ext_packages(self, task: InstallTask) -> None:
        # Install the external packages if not local
        if self.local_backend:
            return


        if self.use_local_host:
            g_backend_dirs.local_host = (
                self.local_host if self.local_host
                else self.get_rehost_dir()
            )

        # All packages except python
        ext_packages = ExtPackages(self.packages_cfg, sys.platform)
        packages_to_install = ext_packages.get_all_except('python')

        # Install external packages
        if packages_to_install:
            installed: bool = download_install_ext_packages(
                packages=packages_to_install,
                reinstall=self.reinstall,
                threads=1,
                use_local_host=self.use_local_host
            )
            if installed:
                self.log.info(lightgreen("All packages installed"))
            else:
                self.log.error(red("Error: missing package(s)"))
        else:
            self.log.error(lightgreen("No packages to install"))

        self.send({
            'task_id': task.task_id,
            'stage': task.stage,
            'status': 'installed',
            'restart': False
        })

        # Todo: verify


    def handle_install_1st_stage(self, task: InstallTask) -> None:
        # Install the packages of the 1st stage: mandatory to select
        #   the correct ones of the 2nd stage
        status = 'failed'
        restart_required = False
        try:
            restart_required = self.handle_install_py_packages_1st_stage()
            status = 'installed'

        except Exception as e:
            self.log.critical(f"Exception: {str(e)}")
            return

        self.send({
            'task_id': task.task_id,
            'stage': task.stage,
            'status': status,
            'restart': restart_required
        })



    def handle_install_py_packages_1st_stage(self) -> bool:
        self.py_packages = PyPackages(
            self.packages_cfg,
            sys.platform,
            keep_up_to_date=self.keep_up_to_date
        )

        cpu_count = mp.cpu_count()
        cpu_count = max(cpu_count - 1, int(cpu_count * 4 / 5))

        # List all packages that are required before installing the AI computation resources
        initial_pkgs = self.py_packages.get_initial()
        to_install_pkgs = initial_pkgs.get_not_installed()
        if self.keep_up_to_date:
            self.log.debug(f"TODO: keep_up_to_date")

        # If all packages already installed, no need to restart
        if not to_install_pkgs:
            self.log.debug(f"All packages installed")
            return False

        # Use multithreading to update the packages info that are not installed
        # Connection to the internet for that
        start_time = time.time()
        with ThreadPoolExecutor(
            max_workers=min(cpu_count, len(to_install_pkgs))
        ) as executor:
            executor.map(lambda pkg: pkg.update_info(), to_install_pkgs)
        elapsed = time.time() - start_time
        # TODO: what if fails to connect?

        # For debug
        for pkg in to_install_pkgs:
            pkg: PyPackage
            self.log.info(f"Installing: {pkg.name} {pkg.version}")
            message: list[str] = "\n".join([
                f"{lightcyan(pkg.name)}:\n    latest version: {pkg.latest_version}\n    selected: {pkg.version}",
                f"    variant: {pkg.variant}",
                f"    installed version: {pkg.installed_version}",
                f"    wheel: {pkg.wheel}",
                f"    wheel url: {pkg.wheel_url}",
                f"    size: {pkg.size // 1024}kB",
            ])
            self.log.debug(message)
        self.log.debug(f"updated package list in {elapsed:.02f}s")

        # Download wheels
        start_time = time.time()
        failed_packages: list[str] = []
        for pkg in to_install_pkgs:
            # Cache packages with size > 80MB
            if pkg.size > 80000 and self.cache:
                pkg.do_cache = True

            if pkg.do_cache:
                start_time = time.time()
                downloaded = pkg.download_wheel(force=False, use_pip=False)
                elapsed = time.time() - start_time
                if downloaded:
                    self.log.debug(f"{pkg.name} downloaded in {elapsed:.02f}s")
                else:
                    self.log.debug(f"{pkg.name} failed to download")

        elapsed = time.time() - start_time
        if failed_packages:
            self.log.critical(f"Failed to download package(s): {', '.join(failed_packages)}")
            return True
        else:
            self.log.info(f"Packages downloaded in {elapsed:.02f}s")

        # Install wheels
        start_time = time.time()
        failed_packages: list[str] = []
        for pkg in to_install_pkgs:
            self.log.debug(f"Install {pkg.name} (reinstall={self.reinstall})")
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
            to_install_pkgs.update_installed_versions()
            for pkg in to_install_pkgs:
                pkg.install(recover=True)
                if not pkg.installed:
                    self.log.critical(f"Failed to install package {pkg.name}")

        return True




    def handle_install_2nd_stage(self) -> bool:
        if self.py_packages is None:
            self.py_packages = PyPackages(
                self.packages_cfg,
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

        start_time = time.time()

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

        cpu_count = mp.cpu_count()
        cpu_count = max(cpu_count - 1, int(cpu_count * 4 / 5))
        with ThreadPoolExecutor(
            max_workers=min(cpu_count, len(supported_pkgs))
        ) as executor:
            executor.map(lambda pkg: pkg.update_info(), supported_pkgs)
        elapsed = time.time() - start_time
        self.log.info(f"Fetch package versions in {elapsed:.02f}s")

        for pkg in supported_pkgs:
            pkg: PyPackage
            self.log.debug(f"{lightcyan(pkg.name)}:\n    latest version: {pkg.latest_version}\n    selected: {pkg.version}")
            self.log.debug(f"    installed: {pkg.installed}")
            self.log.debug(f"    variant: {pkg.variant}")
            self.log.debug(f"    wheel: {pkg.wheel}")
            self.log.debug(f"    wheel url: {pkg.wheel_url}")
            self.log.debug(f"    size: {pkg.size // 1024}kB")
            self.log.debug(f"    do cache: {pkg.do_cache}")

        # print("Packages to install: ", lightcyan(", ".join((pkg.name for pkg in to_install_pkgs))))
        to_install_pkgs = [pkg for pkg in supported_pkgs if not pkg.installed]
        if len(to_install_pkgs) == 0:
            return False

        # Download
        start_time = time.time()
        failed_packages: list[str] = []
        for pkg in to_install_pkgs:
            if pkg.installed or not pkg.do_cache:
                continue

            if not pkg.download_wheel(force=False, use_pip=False):
                failed_packages.append(pkg.name)

        elapsed = time.time() - start_time
        if failed_packages:
            self.log.error(f"Failed to download package(s): {', '.join(failed_packages)}")
            return True

        else:
            self.log.info(f"Packages downloaded in {elapsed:.02f}s")

        # Install packages
        start_time = time.time()
        failed_packages: list[str] = []
        for pkg in to_install_pkgs:
            if not pkg.install(reinstall=False):
                failed_packages.append(pkg.name)

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
            to_install_pkgs.update_installed_versions()
            for pkg in supported_pkgs:
                pkg.install(recover=True)
                if not pkg.installed:
                    self.log.critical(f"Failed to install package(s): {', '.join(failed_packages)}")

        return True
