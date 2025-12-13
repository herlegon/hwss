import os
import signal
import sys
import logging
import logging.handlers
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from logger import setup_server_logging, setup_queue_listener
import logging
from websockets import (
    ServerConnection,
    serve,
    Server,
)
ws_logger = logging.getLogger("websockets")
ws_logger.setLevel(logging.WARNING)

import asyncio
# remove 'DEBUG Using proactor: IocpProactor' log messa ge on Windows
asyncio_logger = logging.getLogger("asyncio")
asyncio_logger.setLevel(logging.WARNING)


from client_connection import ClientConnectionHandler
from hytils import red, yellow
import multiprocessing as mp
import uuid
import time


main_log = logging.getLogger(__name__)


class BackendServer:
    def __init__(
        self,
        host="127.0.0.1",
        port=49990,
        shutdown_event: asyncio.Event = None,
        shutdown_for_inactivity: bool = True,
        log_queue: mp.Queue = None,
        devmode: bool = False,
    ):
        # Server
        self.host = host
        self.port = port
        self._server: Server = None
        self.clients: dict[str, ClientConnectionHandler] = {}

        # Log
        self.devmode: bool = devmode
        self.log_queue: mp.Queue = log_queue

        # Setup server logging
        self.log: logging.Logger = setup_server_logging(
            log_queue=log_queue,
            devmode=devmode,
        )

        # Shutdown logic tracking
        self.shutdown_event = shutdown_event
        self._shutdown_future: asyncio.Future = None
        self._shutting_down: bool = False
        self.start_time = time.time()
        self.last_activity_time = time.time()
        self.has_ever_connected = False
        self.last_client_disconnect_time = None

        # Monitor inactivity to properly shutdown
        self.shutdown_for_inactivity: bool = shutdown_for_inactivity
        self.has_ever_connected_timeout = 5
        self.no_new_client_timeout = 5
        self.inactive_client_timeout = 5


    def register_client(self, server_connection: ServerConnection) -> str | None:
        """Register a new client connection, returns the uuid"""
        if self._shutting_down:
            self.log.warning("Refusing new connection - server is shutting down")
            return None

        self.has_ever_connected = True
        self.update_activity()

        client_id = str(uuid.uuid4())
        handler = ClientConnectionHandler(
            server_connection,
            client_id=client_id,
            server=self,
            log_queue=self.log_queue,
            devmode=self.devmode,
        )
        self.clients[client_id] = handler
        self.log.info(f"Client registerd: {client_id}")
        return client_id


    async def unregister_client(self, client_id: str) -> None:
        """Unregister client connection and clean up.
        """
        handler = self.clients.pop(client_id, None)
        if handler:
            self.log.debug(f"[Server] unregister_client: closing handler")
            await handler.close()

        if not self.clients:
            self.last_client_disconnect_time = time.time()

        self.log.debug(f"[Server] Client {client_id} disconnected (total={len(self.clients)})")


    async def handle_new_client(self, server_connection: ServerConnection):
        """Called by websockets.serve() for each new connection.
        """
        # Check if we're shutting down before accepting
        if self._shutting_down:
            self.log.info("Rejecting connection - server is shutting down")
            await server_connection.close(code=1001, reason="Server shutting down")
            return

        client_id = self.register_client(server_connection=server_connection)

        if client_id is None:
            await server_connection.close(code=1001, reason="Server shutting down")
            return

        self.log.info(f"[Server] Client connected: {client_id} (total={len(self.clients)})")
        handler: ClientConnectionHandler = self.clients[client_id]
        try:
            await handler.handle()
        except Exception as e:
            self.log.error(f"[Server] Client {client_id} error: {e}")
        finally:
            await self.unregister_client(client_id)


    async def broadcast(self, message):
        """Broadcast message to all connected clients
        """
        if not self.clients:
            return

        # Use gather to send to all clients concurrently
        handlers = list(self.clients.values())
        await asyncio.gather(
            *[handler.to_client_queue.put(message) for handler in handlers],
            return_exceptions=True
        )


    def update_activity(self):
        """Update the last activity timestamp."""
        self.last_activity_time = time.time()


    async def _monitor_shutdown_task(self):
        self.log.info("Starting shutdown monitor")
        while not self._shutting_down:
            try:
                await asyncio.wait_for(self.shutdown_event.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
            now = time.time()
            client_count = len(self.clients)

            # 1. No client ever connected: shutdown after 10s
            if self.has_ever_connected_timeout and not self.has_ever_connected:
                if now - self.start_time > self.has_ever_connected_timeout:
                    self.log.warning("Shutdown monitor: No client connected within 10s")
                    if self.shutdown_event:
                        self.shutdown_event.set()
                    return

            # 2. Client was connected: shutdown after 5s if no client anymore
            if (
                self.no_new_client_timeout
                and self.has_ever_connected
                and client_count == 0
            ):
                if (
                    self.last_client_disconnect_time
                    and now - self.last_client_disconnect_time > self.no_new_client_timeout
                ):
                     self.log.warning("Shutdown monitor: No clients after previous connection")
                     if self.shutdown_event:
                        self.shutdown_event.set()
                     return

            # 3. Client is connected but no message received within 8s
            if (
                self.inactive_client_timeout
                and client_count > 0
            ):
                if now - self.last_activity_time > self.inactive_client_timeout:
                    self.log.warning(f"Shutdown monitor: Inactive client (last activity: {now - self.last_activity_time:.1f}s ago)")
                    if self.shutdown_event:
                        self.shutdown_event.set()
                    return


    async def run(self):
        """Start the websocket server.
        """
        if self.shutdown_for_inactivity:
            asyncio.create_task(self._monitor_shutdown_task())
        self.log.info(f"Starting WebSocket server on {self.host}:{self.port}")
        self._server = await serve(
            self.handle_new_client,
            self.host,
            self.port,
        )
        self.log.info(f"Server listening on {self.host}:{self.port}")
        print("READY", file=sys.stdout, flush=True)

        # Create a future that can be set to stop the server
        self._shutdown_future = asyncio.Future()

        # Wait until shutdown is requested
        try:
            await self._shutdown_future
        except asyncio.CancelledError:
            self.log.info("Server run task cancelled")
            raise
        finally:
            self.log.info("Server run loop ended")


    async def shutdown(self) -> None:
        """Initiate graceful shutdown sequence
        """
        if self._shutting_down:
            self.log.info("Shutdown already in progress")
            return
        self._shutting_down = True

        self.log.info("Shutting down server...")

        # Signal the run() loop to stop gracefully
        if self._shutdown_future and not self._shutdown_future.done():
            self._shutdown_future.set_result(None)

        # Close all client connections
        if self.clients:
            self.log.info(f"Notifying {len(self.clients)} client(s) of shutdown...")
            handlers = list(self.clients.values())

            # Stop all client handlers (they will notify clients and stop workers)
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *[handler.close() for handler in handlers],
                        return_exceptions=True
                    ),
                    timeout=20
                )
            except asyncio.TimeoutError:
                self.log.warning("Timeout while closing client handlers")

            self.clients.clear()
            self.log.info("All clients disconnected")

        # Stop accepting new connections
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.log.info("Server shutdown")

        # Terminate remaining child processes if any
        active_children = mp.active_children()
        if active_children:
            self.log.warning(f"Still have {len(active_children)} active child processes:")
            for child in active_children:
                self.log.warning(f"  - {child.name} (PID: {child.pid})")
                self.log.warning(f"  Terminating child process {child.name} (PID {child.pid})")
                child.terminate()

            # Wait for children to actually exit
            for child in active_children:
                child.join(timeout=1.0)
                if child.is_alive():
                    self.log.error(f"  Child {child.name} (PID {child.pid}) failed to terminate")

        # Cancel remaining asyncio tasks (except current)
        current_task = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not current_task and not t.done()]
        if pending:
            self.log.warning(f"Cancelling {len(pending)} pending tasks...")
            for t in pending:
                self.log.warning(f"  Cancelling task: {t.get_coro().__name__}")
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        self.log.info("Shutdown complete")



def setup_signal_handlers(
    shutdown_event: asyncio.Event,
    force_kill_after: int = 5,
    loop: asyncio.AbstractEventLoop | None = None,
):
    signal_count = 0

    def handler(signum, frame):
        nonlocal signal_count
        signal_count += 1

        # Determine signal name safely
        try:
            sig_name = signal.Signals(signum).name
        except Exception:
            sig_name = f"Signal {signum}"

        if signal_count < force_kill_after:
            main_log.info(f"Received {sig_name} ({signal_count}/{force_kill_after}) — graceful shutdown")
            shutdown_event.set()  # trigger shutdown in main

        else:
            main_log.error(f"Received {sig_name} {signal_count} times — forcing immediate termination!")
            if os.name == "nt":
                # Windows: exit immediately
                os._exit(1)
            else:
                # Unix: kill with SIGKILL
                os.kill(os.getpid(), signal.SIGKILL)

    # Register signals depending on platform
    if sys.platform == "win32":
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGBREAK, handler)

    elif sys.platform == 'linux':
        if loop is None:
            raise ValueError("loop must be the AbstractEventLoop")
        loop.add_signal_handler(signal.SIGINT, handler, signal.SIGINT, None)
        loop.add_signal_handler(signal.SIGTERM, handler, signal.SIGTERM, None)



async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default="127.0.0.1")
    parser.add_argument('--port', type=int, default=49990)
    parser.add_argument('--keep-alive', action='store_true')
    parser.add_argument('--devmode', action='store_true')
    parser.add_argument('--log-file', type=str, default=None)
    args = parser.parse_args()

    log_file = args.log_file
    devmode: bool = args.devmode
    host, port = args.host, args.port

    # Log file
    if devmode:
        log_file = ""

    elif log_file is None:
        log_file = 'server.log'  # Default production log file

    # Create centralized logging queue and listener
    log_queue = mp.Queue(-1)
    queue_listener = setup_queue_listener(
        log_queue=log_queue,
        log_file=log_file,
        devmode=devmode,
    )
    queue_listener.start()

    # Setup module-level logger with queue handler
    main_log.handlers.clear()
    main_log.addHandler(logging.handlers.QueueHandler(log_queue))
    main_log.setLevel(logging.DEBUG if devmode else logging.INFO)


    shutdown_event = asyncio.Event()
    server = BackendServer(
        host=host,
        port=port,
        shutdown_event=shutdown_event,
        shutdown_for_inactivity=not args.keep_alive,
        log_queue=log_queue,
        devmode=devmode
    )

    loop: asyncio.AbstractEventLoop | None = None
    if sys.platform == 'linux':
        loop = asyncio.get_event_loop()

    setup_signal_handlers(shutdown_event, force_kill_after=5, loop=loop)

    # Start server in background
    server_task = asyncio.create_task(server.run())

    try:
        # Wait for shutdown signal
        await shutdown_event.wait()
        main_log.info("Shutdown event triggered, starting server shutdown...")

        # Perform graceful shutdown
        await server.shutdown()

        # Wait for server task to complete naturally
        if not server_task.done():
            try:
                await asyncio.wait_for(server_task, timeout=15.0)
            except asyncio.TimeoutError:
                main_log.warning("Server task did not complete in time, cancelling...")
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    main_log.info("Server task cancelled successfully")

    except Exception as e:
        main_log.error(f"Error during shutdown: {str(e)}", exc_info=True)
        if not server_task.done():
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                main_log.info("Server task cancelled due to error")

    main_log.info("Main exiting")

    # Stop the queue listener
    queue_listener.stop()



if __name__ == "__main__":
    mp.set_start_method('spawn')
    try:
        asyncio.run(main())
    except Exception as e:
        main_log.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    main_log.info("Process exit")




