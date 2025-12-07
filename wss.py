import os
import signal
import sys
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

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__))))

from client_connection import ClientConnectionHandler
from hytils import red, yellow
from logger import slog
import multiprocessing as mp
import uuid


# logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


class BackendServer:
    def __init__(self, host="127.0.0.1", port=8442):
        self.host = host
        self.port = port
        self._server: Server = None
        self._shutting_down: bool = False
        self.clients: dict[str, ClientConnectionHandler] = {}


    def register_client(self, server_connection: ServerConnection) -> str | None:
        """Register a new client connection, returns the uuid"""
        if self._shutting_down:
            slog.warning("Refusing new connection - server is shutting down")
            return None

        client_id = str(uuid.uuid4())
        handler = ClientConnectionHandler(
            server_connection,
            client_id=client_id,
            server=self
        )
        self.clients[client_id] = handler
        slog.info(f"Client registerd: {client_id}")
        return client_id


    async def unregister_client(self, client_id: str) -> None:
        """Unregister client connection and clean up."""
        handler = self.clients.pop(client_id, None)
        if handler:
            print(f"[Server] unregister_client: closing handler")
            await handler.close()
        print(f"[Server] Client {client_id} disconnected (total={len(self.clients)})")


    async def handle_new_client(self, server_connection: ServerConnection):
        """Called by websockets.serve() for each new connection."""
        # Check if we're shutting down before accepting
        if self._shutting_down:
            slog.info("[S] Rejecting connection - server is shutting down")
            await server_connection.close(code=1001, reason="Server shutting down")
            return

        client_id = self.register_client(server_connection=server_connection)

        if client_id is None:
            await server_connection.close(code=1001, reason="Server shutting down")
            return

        print(f"[Server] Client connected: {client_id} (total={len(self.clients)})")
        handler: ClientConnectionHandler = self.clients[client_id]
        try:
            await handler.handle()
        except Exception as e:
            print(f"[Server] Client {client_id} error: {e}")
        finally:
            await self.unregister_client(client_id)


    async def broadcast(self, message):
        """Broadcast message to all connected clients"""
        if not self.clients:
            return

        # Use gather to send to all clients concurrently
        handlers = list(self.clients.values())
        await asyncio.gather(
            *[handler.to_client.put(message) for handler in handlers],
            return_exceptions=True
        )


    async def run(self):
        """Start the websocket server."""
        slog.info(f"Starting WebSocket server on {self.host}:{self.port}")
        self._server = await serve(
            self.handle_new_client,
            self.host,
            self.port,
        )
        slog.info(f"Server listening on {self.host}:{self.port}")

        #     # Wait indefinitely until shutdown is requested, but cancel is mandatory
        #     try:
        #         await asyncio.Future()
        #     finally:
        #         slog.info("[S] Server run loop ended")

        # Create a future that can be set to stop the server
        self._shutdown_future = asyncio.Future()

        # Wait until shutdown is requested
        try:
            await self._shutdown_future
        except asyncio.CancelledError:
            slog.info("[S] Server run task cancelled")
            raise
        finally:
            slog.info("[S] Server run loop ended")


    async def shutdown(self) -> None:
        """Initiate graceful shutdown sequence"""
        if self._shutting_down:
            slog.info("[S] Shutdown already in progress")
            return
        self._shutting_down = True

        slog.info("[S] Shutting down server...")

        # Signal the run() loop to stop gracefully
        if self._shutdown_future and not self._shutdown_future.done():
            self._shutdown_future.set_result(None)

        # Close all client connections
        if self.clients:
            slog.info(f"[S] Notifying {len(self.clients)} client(s) of shutdown...")
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
                slog.warning("[S] Timeout while closing client handlers")
            self.clients.clear()
            slog.info("[S] All clients disconnected")

        # Stop accepting new connections
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        slog.info("[S] Server shutdown complete.")

        # Terminate remaining child processes if any
        active_children = mp.active_children()
        if active_children:
            slog.warning(f"Still have {len(active_children)} active child processes:")
            for child in active_children:
                slog.warning(f"  - {child.name} (PID: {child.pid})")
                slog.warning(f"  Terminating child process {child.name} (PID {child.pid})")
                child.terminate()

        # Cancel remaining asyncio tasks (except current)
        current_task = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not current_task and not t.done()]
        if pending:
            slog.warning(f"Cancelling {len(pending)} pending tasks...")
            for t in pending:
                slog.warning(f"  Cancelling tasks {t}")
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        slog.info("[S] Shutdown complete")



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
            slog.info(f"Received {sig_name} ({signal_count}/{force_kill_after}) — graceful shutdown")
            shutdown_event.set()  # trigger shutdown in main

        else:
            slog.error(f"Received {sig_name} {signal_count} times — forcing immediate termination!")
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
    slog.info("[S] Server starting")
    host, port = "127.0.0.1", 8442

    server = BackendServer(host=host, port=port)
    shutdown_event = asyncio.Event()

    loop: asyncio.AbstractEventLoop | None = None
    if sys.platform == 'linux':
        loop = asyncio.get_event_loop()

    setup_signal_handlers(shutdown_event, force_kill_after=5, loop=loop)


    # Start server in background
    server_task = asyncio.create_task(server.run())

    try:
        # Wait for shutdown signal
        await shutdown_event.wait()
        slog.info("[S] Shutdown event triggered, starting server shutdown...")

        # Perform graceful shutdown
        await server.shutdown()

        # Wait for server task to complete naturally
        if not server_task.done():
            try:
                await asyncio.wait_for(server_task, timeout=15.0)
            except asyncio.TimeoutError:
                slog.warning("Server task did not complete in time, cancelling...")
                server_task.cancel()
                try:
                    await server_task
                except asyncio.CancelledError:
                    slog.info("[S] Server task cancelled successfully")

    except Exception as e:
        slog.error(f"Error during shutdown: {str(e)}", exc_info=True)
        if not server_task.done():
            server_task.cancel()
            try:
                await server_task
            except asyncio.CancelledError:
                slog.info("[S] Server task cancelled due to error")

    slog.info("[S] Main exiting")



if __name__ == "__main__":
    mp.set_start_method('spawn')
    try:
        asyncio.run(main())
    except Exception as e:
        slog.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    slog.info("[S] Process exit")




