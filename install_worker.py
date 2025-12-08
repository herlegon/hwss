from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from pprint import pprint
import queue
import signal
import sys
import time
from hytils import lightcyan, lightgreen, purple, red, yellow
from logger import slog
from api import WorkerResponse
import multiprocessing as mp
from typing import Literal

try:
    from hinstall import __version__

except:
    dev_dir: str = str(Path(__file__).resolve().parent.parent / "hinstall")
    slog.warning(f"Import hinstall from dev directory: {dev_dir}")
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
    slog.critical(f"Failed to import hinstall package: {str(e)}")


InstallWorkerTask = Literal[
    'shutdown',
    'packages_cfg'
]
worker_task_list = list(InstallWorkerTask.__args__)



class InstallWorker(mp.Process):
    """Worker process that executes long-running tasks"""
    def __init__(
        self,
        task_queue: mp.Queue,
        result_queue: mp.Queue,
        stop_event: mp.Event
    ):
        super().__init__()
        self.task_queue: mp.Queue = task_queue
        self.result_queue: mp.Queue = result_queue
        self.stop_event: mp.Event = stop_event
        self.daemon = True

        self.product_name: str = "hconvert"
        self.reinstall: bool = False
        self.use_local_host: bool = True
        self.local_host: str = ""
        self.keep_up_to_date: bool = False

        self.packages_cfg : dict[str, str] = {}
        self.py_packages: PyPackages = None


    def run(self):
        # Ignore KeyboardInterrupt inside the worker
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        slog.info(purple(f"[{self.pid}] ℹ️  worker process started"))

        while not self.stop_event.is_set():

            try:
                msg: dict = self.task_queue.get(timeout=0.2)
                task_name: InstallWorkerTask = msg['cmd']
                payload: dict | None = msg.get('payload', {})

                # Route to appropriate task handler
                if task_name == 'shutdown':
                    slog.info(purple(f"[{self.pid}] ℹ️  received shutdown"))
                    break

                elif task_name == 'parse':
                    self.handle_parse_cfg(payload)

                elif task_name == 'install':
                    stage_no = payload.get('stage', -1)
                    if stage_no == 0:
                        self.handle_install_ext_packages()

                    if stage_no == 1:
                        self.handle_install_1st_stage(payload)

                    elif stage_no == 2:
                        self.handle_install_2nd_stage(payload)

                    else:
                        self.send_result(
                            WorkerResponse(
                                type="error",
                                payload=f"Not supported stage no: {stage_no}"
                            )
                        )

                    # if 'hinstall' not in sys.modules:
                    #     try:
                    #         from hinstall import (
                    #             ExtPackages,
                    #             PyPackages,
                    #             download_install_ext_packages,
                    #             g_backend_dirs,
                    #             generate_backend_env,
                    #             get_python_version,
                    #             parse_config_,
                    #             get_pypackage_list,
                    #             get_pip_versions,
                    #         )
                    #     except Exception as e:
                    #         slog.critical("Failed to import hinstall package")

                    # slog.info(purple(f"[{self.pid}] parse {payload}"))



                # else:
                #     self.send_result(
                #         WorkerResponse(
                #             type="error",
                #             payload=f"Unknown task: {task_name}"
                #         )
                #     )

            except queue.Empty:
                continue

            except Exception as e:
                print(purple(f"[{self.pid}] ❌ uncaught exception: {str(e)}"))
                self.send_result(
                    WorkerResponse(
                        type="exception",
                        payload=f"exception: {str(e)}"
                    )
                )

        slog.info(purple(f"[{self.pid}] ℹ️ terminated"))



    def do_stop(self) -> bool:
        """Check if task should stop"""
        return self.stop_event.is_set()


    def send_result(self, response: WorkerResponse):
        """Send result back to server"""
        self.result_queue.put(response)


    def get_rehost_dir(self, organization: str = "herlegon") -> Path:
        local_package_dir: Path

        if sys.platform == "win32":
            local_package_dir = Path("A:\\") / organization / "rehost"

        elif sys.platform == "linux":
            local_package_dir = Path("/opt") / organization / "rehost"

        elif sys.platform == "darwin":
            local_package_dir = Path.home() / organization / "rehost"

        return local_package_dir



    def handle_parse_cfg(self, payload: dict) -> None:
        toml_cfg = json.loads(payload.get("cfg"))

        self.product_name: str = payload.get("product", "hconvert")
        self.is_local_backend: bool = payload.get("local_backend", True)
        self.reinstall: bool = payload.get("reinstall", False)
        self.use_local_host: bool = payload.get("use_local_host", False)
        self.local_host: str = payload.get("local_host", "")

        self.packages_cfg = parse_config_(toml_cfg)
        # try:
        #     packages_cfg = parse_config_(payload)
        # except Exception as e:
        #     exception: str = str(e)
        #     self.send_result(
        #         WorkerResponse(type="exception", payload=exception)
        #     )
        #     return

        self.send_result(
            WorkerResponse(
                type="status",
                payload={
                    'state': "parsed",
                }
            )
        )


    def handle_install_1st_stage(self, payload: dict) -> None:


        # Install the packages of the 1st stage: mandatory to select
        #   the correct ones of the 2nd stage
        print("start 1st stage")
        restart_required = self.handle_install_py_packages_1st_stage()
        if restart_required:
            print("restart to install delayed")
            print("\nPackages installed successfully. Restarting server...")

            # Restart this script
            os.execv(sys.executable, [sys.executable] + sys.argv)
            return

        else:
            print("start 2nd stage")

            restart_required = self.handle_install_2nd_stage()

        if restart_required:
            print("restart to install delayed")
            print("\nPackages installed successfully. Restarting server...")
            # Restart this script
            os.execv(sys.executable, [sys.executable] + sys.argv)
            return
        else:
            print(red("READY"))



    def handle_install_ext_packages(self) -> None:

        # Install the external packages if not local
        if self.is_local_backend:
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
                print(lightgreen("All packages installed"))
            else:
                print(red("Error: missing package(s)"))
        else:
            print(lightgreen("No packages to install"))

        self.send_result(
            WorkerResponse(
                type="status",
                payload={
                    'type': "external",
                    'state': "installed",
                }
            )
        )

        # Todo: verify



    def handle_install_py_packages_1st_stage(self) -> bool:
        self.py_packages = PyPackages(
            self.packages_cfg,
            sys.platform,
            keep_up_to_date=self.keep_up_to_date
        )

        cpu_count = mp.cpu_count()
        cpu_count = max(cpu_count - 1, int(cpu_count * 4 / 5))


        initial_pkgs = self.py_packages.get_initial()

        to_install_pkgs = initial_pkgs.get_not_installed()
        if self.keep_up_to_date:
            print(f"TODO add packages to update")

        if not to_install_pkgs:
            return False

        start_time = time.time()
        with ThreadPoolExecutor(
            max_workers=min(cpu_count, len(to_install_pkgs))
        ) as executor:
            executor.map(lambda pkg: pkg.update_info(), to_install_pkgs)
        elapsed = time.time() - start_time
        for pkg in to_install_pkgs:
            pkg: PyPackage
            print(f"{lightcyan(pkg.name)}:\n    latest version: {pkg.latest_version}\n    selected: {pkg.version}")
            print(f"    variant: {pkg.variant}")
            print(f"    installed version: {pkg.installed_version}")
            print(f"    wheel: {pkg.wheel}")
            print(f"    wheel url: {pkg.wheel_url}")
            print(f"    size: {pkg.size // 1024}kB")
        print(f"updated in {elapsed:.02f}s")

        for pkg in to_install_pkgs:
            # Cache packages with size > 80MB
            if pkg.size > 80000:
                pkg.do_cache = True

            if pkg.do_cache:
                start_time = time.time()
                downloaded = pkg.download_wheel(force=False, use_pip=False)
                elapsed = time.time() - start_time
                if downloaded:
                    slog.info(f"{pkg.name} downloaded in {elapsed:.02f}s")
                else:
                    slog.error(f"{pkg.name} failed to download")

            pkg.install(force=False)

        to_install_pkgs.update_installed_versions()
        for pkg in to_install_pkgs:
            if not pkg.installed:
                slog.critical(f"{pkg.name} not installed")
                pkg.install(recover=True)

        # Now restart
        return True


    def handle_install_2nd_stage(self) -> bool:
        if self.py_packages is None:
            self.py_packages = PyPackages(
                self.packages_cfg,
                sys.platform,
                keep_up_to_date=self.keep_up_to_date
            )

        pkgs = self.py_packages.get_delayed()

        from hsys import is_feature_supported

        cuda = is_feature_supported('cuda')
        tensorrt = is_feature_supported('tensorrt')
        directml = is_feature_supported('directml')
        rocm = is_feature_supported('rocm')

        print(f"CUDA: {'✅' if cuda else '❌'}")
        print(f"TensorRT: {'✅' if tensorrt else '❌'}")
        print(f"direct ML: {'✅' if directml else '❌'}")
        print(f"RocM: {'✅' if rocm else '❌'}")

        start_time = time.time()

        for pkg in pkgs.get_by_execution_provider('cuda'):
            pkg.skip = not cuda
            pkg.supported = cuda

        for pkg in pkgs.get_by_execution_provider('rocm'):
            pkg.skip = not rocm
            pkg.supported = rocm

        for pkg in pkgs.get_by_execution_provider('directml'):
            pkg.skip = not directml
            pkg.supported = directml

        cpu_fallback = all([x is False for x in (cuda, tensorrt, rocm)])
        for pkg in pkgs.get_by_execution_provider('cpu'):
            pkg.skip = not cpu_fallback
            pkg.supported = cpu_fallback


        print("supported packages")
        supported_pkgs = pkgs.get_delayed(supported_only=True)
        for pkg in supported_pkgs:
            print(lightcyan(pkg.pretty_name))
            pprint(pkg)

        cpu_count = mp.cpu_count()
        cpu_count = max(cpu_count - 1, int(cpu_count * 4 / 5))
        with ThreadPoolExecutor(
            max_workers=min(cpu_count, len(supported_pkgs))
        ) as executor:
            executor.map(lambda pkg: pkg.update_info(), supported_pkgs)
        elapsed = time.time() - start_time

        for pkg in supported_pkgs:
            pkg: PyPackage
            print(f"{lightcyan(pkg.name)}:\n    latest version: {pkg.latest_version}\n    selected: {pkg.version}")
            print(f"    installed: {pkg.installed}")
            print(f"    variant: {pkg.variant}")
            print(f"    wheel: {pkg.wheel}")
            print(f"    wheel url: {pkg.wheel_url}")
            print(f"    size: {pkg.size // 1024}kB")
            print(f"    do cache: {pkg.do_cache}")
        slog.info(f"updated in {elapsed:.02f}s")


        # print("Packages to install: ", lightcyan(", ".join((pkg.name for pkg in to_install_pkgs))))
        pkgs = [pkg for pkg in supported_pkgs if not pkg.installed]
        if len(pkgs) == 0:
            return False

        # Download
        for pkg in pkgs:
            if pkg.installed or not pkg.do_cache:
                continue

            start_time = time.time()
            downloaded = pkg.download_wheel(force=False, use_pip=False)
            if downloaded:
                slog.info(f"{pkg.name} downloaded in {elapsed:.02f}s")
            else:
                slog.error(f"{pkg.name} failed to download")

            elapsed = time.time() - start_time
            slog.info(f"{pkg.name} downloaded in {elapsed:.02f}s")
            # print(lightcyan("-" * 80))

        # install
        for pkg in pkgs:
            pkg.install(reinstall=False)


        pkgs.update_installed_versions()
        for pkg in supported_pkgs:
            if not pkg.installed:
                slog.critical(f"{pkg.name} not installed")
                pkg.install(recover=True)
        return True
