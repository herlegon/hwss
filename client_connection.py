from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
from pprint import pprint
import queue
import sys
import websockets
from api import RequestMessage, ResponseMessage, WssIdentity, deserialize, serialize
from install_worker import InstallWorker
from hytils import lightblue, lightcyan, purple, red, yellow
from websockets import (
    ServerConnection,
    connect,
    ConnectionClosed,
    ConnectionClosedOK,
    ConnectionClosedError,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wss import BackendServer


# --- SAFE IMPORT BLOCK ---
try:
    from messages import WorkerResponse
    from worker import Worker, worker_task_list
    WORKER_AVAILABLE = True

except ImportError:
    # This happens during the first run (Setup Mode).
    # We define dummy variables so the code below doesn't crash with NameError.
    Worker = None
    worker_task_list = []  # An empty list makes "if cmd in list" safe!
    WORKER_AVAILABLE = False



class ClientConnectionHandler:
    def __init__(
        self,
        server_connection: ServerConnection,
        client_id: str,
        server: BackendServer,
        enable_wss_stdout: bool = False,
        log_file: str | None = None,
    ):
        """
        websocket: the connected websocket object
        client_id: unique id for this client
        server: reference to the backend server (optional, for broadcasts, etc.)
        """
        from logger import setup_client_logger, slog

        # Control flags
        self.closing = False

        # List of asyncio tasks for send/recv loops
        self.tasks = []

        # websocket
        self.server_connection = server_connection
        self.client_id = f"{client_id[:7]}"
        self.server = server

        # Async queues for websocket I/O
        self.to_client = asyncio.Queue()
        self.from_client = asyncio.Queue()


        # Setup client-specific logger
        self.clog = setup_client_logger(
            self.client_id,
            self.to_client,
            log_file=log_file,
            enable_stdout=enable_wss_stdout
        )

        # Worker management
        self.workers: dict[str, dict[str, 'Worker']] = {}
        self.stop_event: mp.Event = mp.Event()

        self.install_worker_name = "hinstall"

        if WORKER_AVAILABLE:
            self.worker_name = "nnlib"
            self.start_worker(self.worker_name)



    async def route_message(self, msg):
        """
        Decide whether to forward to a worker or handle as control message.
        Expecting `msg` as a dict with at least a 'type' field.
        """
        data = deserialize(msg)
        if data is None:
            slog.warning(f"⚠️ Received invalid JSON: {msg}")
            return

        try:
            request = RequestMessage(**data)
        except Exception as e:
            slog.warning(f"exception: {str(e)}")
            return

        request_type = request.type
        if request_type == 'heartbeat':
            await self.to_client.put(ResponseMessage(type='pong'))


        elif request_type == 'shutdown':
            # Allow shutdown only if there is a single client
            if len(self.server.clients) > 1:
                await self.to_client.put(
                    ResponseMessage(type='shutdown', payload="denied")
                )
                return

            slog.debug("route shutdown message")
            if self.server and self.server.shutdown_event:
                await self.to_client.put(
                    ResponseMessage(type='shutdown', payload="allowed")
                )
                self.server.shutdown_event.set()

            else:
                slog.warning("No server or shutdown_event reference, force closing client")
                await self.close()


        elif request_type == 'identify':
            response = ResponseMessage(
                type='identity',
                payload=WssIdentity(
                    organization="herlegon",
                    app="hinstall",
                    clients=len(self.server.clients) if self.server else 0
                )
            )
            await self.to_client.put(response)


        elif request_type == 'restart':
            os.execv(sys.executable, [sys.executable] + sys.argv)
            return


        elif request_type == 'stop':
            slog.info(f"[{self.client_id}] Received stop command")
            if self.server:
                # Schedule shutdown on the event loop to avoid blocking current handler
                asyncio.create_task(self.server.shutdown())


        # Setup/Install Messages
        elif request_type == 'setup':
            # Create a worker if not already done
            if self.install_worker_name not in self.workers.keys():
                self.start_worker(self.install_worker_name)

            # Forward to the worker
            self.submit_task_to_worker(
                self.install_worker_name, request.payload
            )


        elif request_type in worker_task_list:
            if WORKER_AVAILABLE:
                self.submit_task_to_worker(self.worker_name, request.payload)
            else:
                slog.error("Cannot execute task: System is in Setup Mode.")


        else:
            slog.warning(lightblue(f"[{self.client_id}] ⚠️ Unknown message type: {request_type}"))



    async def reception_task(self):
        """
        Receive messages from the client websocket and route them.
        """
        try:
            async for msg in self.server_connection:
                if self.server:
                    self.server.update_activity()
                await self.route_message(msg)

        except asyncio.CancelledError:
            slog.debug(f"[{self.client_id}] Reception task cancelled")
            raise

        except websockets.ConnectionClosedOK:
            slog.info(lightblue(f"[{self.client_id}] connection closed"))

        except websockets.ConnectionClosedError as e:
            slog.warning(lightblue(f"[{self.client_id}] ⚠️  disconnected with error: {e}"))

        except Exception as e:
            slog.warning(lightblue(f"[{self.client_id}] ⚠️  exception while running reception handler: {e}"))

        finally:
            slog.info(lightblue(f"[{self.client_id}] ℹ️  Reception task ended"))


    async def send_message_task(self):
        """
        asyncio task used to send messages that are in a queue filled by workers
        """
        while not self.closing:
            try:
                message = await asyncio.wait_for(
                    self.to_client.get(),
                    timeout=0.5
                )
                msg = (
                    serialize(message)
                    if not isinstance(message, str)
                    else message
                )
                await self.server_connection.send(msg)

            except asyncio.TimeoutError:
                # No message in queue, check closing and continue
                continue

            except asyncio.CancelledError:
                slog.debug(lightblue(f"[{self.client_id}] Sending task cancelled"))
                break

            except websockets.ConnectionClosed:
                slog.info(lightblue(f"[{self.client_id}] Connection closed while sending"))
                break

            except Exception as e:
                slog.error(lightblue(f"❌  [{self.client_id}] Failed to send message: {e}"))

        slog.info(lightblue(f"[{self.client_id}] ℹ️  Send task ended"))



    async def handle(self):
        """
        Start the send/recv loops for this client.
        Returns when the client disconnects or stop() is called.
        """
        slog.info(lightblue(f"[{self.client_id}] ℹ️  handler started"))

        # Start websocket loops
        reception_task = asyncio.create_task(self.reception_task())
        send_task = asyncio.create_task(self.send_message_task())

        self.tasks = [reception_task, send_task]

        # Start worker result loop(s)
        # for name in self.workers.keys():
        #     worker_task = asyncio.create_task(self.worker_result_loop(name))
        #     self.tasks.append(worker_task)

        try:
            # Wait for any task to complete (likely due to disconnect or error)
            done, pending = await asyncio.wait(
                self.tasks,
                return_when=asyncio.FIRST_COMPLETED
            )

            slog.info(lightblue(f"[{self.client_id}] First task completed, stopping others"))

        except asyncio.CancelledError:
            slog.info(lightblue(f"[{self.client_id}] Handler tasks cancelled"))

        except Exception as e:
            slog.error(lightblue(f"❌  [{self.client_id}] Exception in handler: {e}"))

        finally:
            if not self.closing:
                await self.close()

        slog.info(lightblue(f"[{self.client_id}] ℹ️  handler ended"))



    async def shutdown_websocket(self):
        """Stop all tasks and workers for this client."""
        if self.closing:
            slog.info(lightblue(f"[{self.client_id}] ⚠️ Already closing"))
            return

        # Optional: notify client of shutdown
        # try:
        #     shutdown_msg = WorkerResponse(
        #         type='shutdown',
        #         payload="Server is shutting down"
        #     )
        #     await asyncio.wait_for(
        #         self.server_connection.send(json.dumps({
        #             "type": shutdown_msg.type,
        #             "payload": shutdown_msg.payload
        #         })),
        #         timeout=1.0
        #     )
        #     slog.info(f"[{self.client_id}] Sent shutdown notification to client")
        # except (websockets.ConnectionClosed, asyncio.TimeoutError):
        #     slog.info(f"[{self.client_id}] Client already disconnected")
        # except Exception as e:
        #     slog.warning(f"[{self.client_id}] Failed to send shutdown message: {e}")

        # Close the websocket connection
        try:
            await asyncio.wait_for(
                self.server_connection.close(code=1000, reason="Server shutting down"),
                timeout=1.0
            )
            slog.info(lightblue(f"[{self.client_id}] ⚠️ shutdown_websocket: WebSocket closed"))

        except asyncio.TimeoutError:
            slog.warning(lightblue(f"[{self.client_id}] ⚠️ shutdown_websocket: WebSocket close timed out"))

        except Exception as e:
            slog.error(lightblue(f"[{self.client_id}] ❌  shutdown_websocket: Error closing WebSocket: {e}"))

        await asyncio.sleep(0.05)

        # Cancel all running tasks
        if self.tasks:
            for t in self.tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks.clear()

        # Cancel async tasks individually with error handling
        cancelled_tasks = []
        for i, task in enumerate(self.tasks):
            if not task.done():
                try:
                    task.cancel()
                    cancelled_tasks.append(task)
                except Exception as e:
                    slog.warning(f"[{self.client_id}] ⚠️ Error cancelling task {i}: {e}")

        # Wait for cancelled tasks with timeout
        if cancelled_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*cancelled_tasks, return_exceptions=True),
                    timeout=1.0
                )
            except asyncio.TimeoutError:
                slog.warning(f"[{self.client_id}] ⚠️ Task cancellation timed out")
            except Exception as e:
                slog.warning(f"[{self.client_id}] ⚠️ Error gathering tasks: {e}")

            slog.info(lightblue(f"[{self.client_id}] ℹ️  All async tasks stopped"))

        slog.info(lightblue(f"[{self.client_id}] ℹ️  Stop sequence complete"))


    def start_worker(self, name: str):
        """
        Create and start a worker process.
        """
        if name in self.workers and self.workers[name]['worker'].is_alive():
            slog.warning(lightblue(f"[{self.client_id}] ⚠️ Worker {name} already running"))
            return

        task_queue = mp.Queue()
        result_queue = mp.Queue()
        if name == 'hinstall':
            try:
                worker = InstallWorker(
                    task_queue=task_queue,
                    result_queue=result_queue,
                    stop_event=self.stop_event
                )
                worker.start()
            except Exception as e:
                slog.error(f"[{self.client_id}] ❌  Failed to start worker \'{name}\'")
                return

        self.workers[name] = {
            'worker': worker,
            'task_queue': task_queue,
            'result_queue': result_queue,
        }

        # Start async loop to forward results from this worker
        self.tasks.append(asyncio.create_task(self.worker_result_loop(name)))
        slog.info(lightblue(f"[{self.client_id}] ℹ️  Worker {name} started: {worker.pid}"))


    def submit_task_to_worker(self, name: str, task):
        """
        Put a task into the worker's task queue.
        """
        if not name:
            # Get the first key from the dictionary if 'name' is not provided
            name = next(iter(self.workers), "")

        if (
            name
            and name in self.workers
            and task is not None
        ):
            try:
                task_queue: mp.Queue = self.workers[name]['task_queue']
                task_queue.put(task, block=False)

            except Exception as e:
                slog.error(lightblue(
                    f"[{self.client_id}] ❌  failed to submit task to worker {name}: {str(e)}"
                ))


    async def worker_result_loop(self, name: str):
        """
        Async loop to forward worker results to the to_client queue.
        """
        slog.info(lightblue(f"[{self.client_id}] ℹ️  start a worker result loop for {name}"))

        loop = asyncio.get_running_loop()
        result_queue: mp.Queue = self.workers[name]['result_queue']

        if not result_queue:
            slog.error(lightblue(f"[{self.client_id}] ❌  No result queue for worker {name}"))
            return

        while not self.closing:
            try:
                # Use a short timeout to allow checking self.running
                # Run blocking get() in a thread, with short timeout
                result = await loop.run_in_executor(None, result_queue.get, True, 0.5)

                if self.closing:
                    break

                await self.to_client.put(result)

            except queue.Empty:
                # Normal, no message to process
                continue

            except asyncio.TimeoutError:
                # Normal timeout, continue loop
                continue

            except asyncio.CancelledError:
                slog.warning(lightblue(f"[{self.client_id}] ⚠️  worker result loop cancelled for {name}"))
                break

            except Exception as e:
                if not self.closing:
                    slog.error(lightblue(f"❌  [{self.client_id}] Error in worker result loop: {str(e)}"))
                break

        slog.info(lightblue(f"[{self.client_id}] ℹ️  worker result loop for {name} ended"))


    def stop_worker(self, name: str, timeout: float = 2.0):
        """
        Attempt to gracefully stop a single worker process.
        Blocks for up to `timeout` seconds.
        """
        slog.info(f"Stopping worker {name}...")

        w = self.workers.get(name)
        if not w:
            return f"{name}: no such worker"

        worker: Worker = w['worker']
        worker.join(timeout=timeout)

        # If it's still alive, kill it hard
        if worker.is_alive():
            slog.warning(lightblue(f"[{self.client_id}] ⚠️ Force killing worker {name}"))
            worker.terminate()
            worker.join(timeout=timeout + 1)

            if worker.is_alive():
                import signal
                slog.warning(lightblue(f"[{self.client_id}] ⚠️ SIGKILLing stubborn worker {name}"))
                os.kill(worker.pid, signal.SIGKILL)

        del self.workers[name]

        # Cleanup
        try:
            worker.close()
        except Exception:
            pass


    async def stop_workers(self):
        """Stop all worker processes gracefully"""
        if not self.workers:
            slog.info(lightblue(f"[{self.client_id}] No worker"))
            return

        slog.info(lightblue(f"[{self.client_id}] Stopping {len(self.workers)} worker(s)"))
        # Immediately set the shared event
        self.stop_event.set()

        # Send shutdown to all queues quickly (non-blocking)
        for w in self.workers.values():
            try:
                w['task_queue'].put_nowait({'cmd': 'shutdown'})
            except Exception:
                pass

        # Stop each worker in parallel (force kill if needed)
        timeout: float = 3.
        loop = asyncio.get_running_loop()
        worker_names = list(self.workers.keys())
        tasks = [
            loop.run_in_executor(None, self.stop_worker, name, timeout)
            for name in worker_names
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                slog.error(lightblue(f"[{self.client_id}] ❌  worker stop error: {res}"))
            else:
                slog.debug(lightblue(f"[{self.client_id}] {res}"))

        slog.info(lightblue(f"[{self.client_id}] ℹ️  all workers stopped."))


    async def close(self):
        # Run websocket shutdown and worker stop in parallel
        if not self.closing:
            self.closing = True
            slog.info(lightblue(f"[{self.client_id}] ℹ️  close handler"))
            await asyncio.gather(
                self.shutdown_websocket(),
                self.stop_workers(),
                return_exceptions=True
            )

            slog.info(lightblue(f"[{self.client_id}] ℹ️  handler fully closed"))
















