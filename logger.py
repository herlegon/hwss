

import asyncio
from collections.abc import Callable
from dataclasses import asdict
import logging
import queue
import sys
from typing import Literal

from api import EventMessage, MessageType
import multiprocessing as mp



# Server logger
slog: logging.Logger = None




class WebSocketHandler(logging.Handler):
    """Handler that sends log messages as WebSocket EventMessages to a specific client"""

    def __init__(self, client_queue: asyncio.Queue):
        """
        Args:
            client_queue: The to_client queue for a specific ClientConnectionHandler
        """
        super().__init__()
        self.client_queue = client_queue

    def emit(self, record: logging.LogRecord):
        try:
            msg_type = self._levelname_to_message_type(record.levelname)
            event_msg = EventMessage(
                type='msg',
                payload={'type': msg_type, 'text': self.format(record)}
            )
            # Put message in the client's queue (non-blocking)
            try:
                self.client_queue.put_nowait(event_msg)
            except asyncio.QueueFull:
                # Queue is full, skip this message
                pass
        except Exception:
            self.handleError(record)

    @staticmethod
    def _levelname_to_message_type(levelname: str) -> MessageType:
        mapping: dict[str, MessageType] = {
            'CRITICAL': 'critical',
            'ERROR': 'error',
            'WARNING': 'warning',
            'INFO': 'info',
            'DEBUG': 'debug',
        }
        return mapping.get(levelname, 'info')



class MultiprocessingHandler(logging.Handler):
    """Handler that sends log messages from worker processes via mp.Queue"""

    def __init__(self, mp_queue: mp.Queue):
        super().__init__()
        self.mp_queue = mp_queue

    def emit(self, record: logging.LogRecord):
        try:
            msg_type = self._levelname_to_message_type(record.levelname)
            event_msg = EventMessage(
                type='msg',
                payload={'type': msg_type, 'text': self.format(record)}
            )
            # Send to main process via multiprocessing queue
            try:
                self.mp_queue.put_nowait(asdict(event_msg))
            except queue.Full:
                # Queue is full, skip this message
                pass
        except Exception:
            self.handleError(record)

    @staticmethod
    def _levelname_to_message_type(levelname: str) -> MessageType:
        mapping: dict[str, MessageType] = {
            'CRITICAL': 'critical',
            'ERROR': 'error',
            'WARNING': 'warning',
            'INFO': 'info',
            'DEBUG': 'debug',
        }
        return mapping.get(levelname, 'info')





def setup_server_logging(
    mode: Literal['dev', 'prod'] = 'dev',
    log_file: str | None = None,
    enable_stdout: bool = True,
) -> logging.Logger:
    """
    Setup logging for server events (startup, shutdown, connections).
    Called once at server startup.

    Args:
        mode: 'dev' or 'prod'
        log_file: Path to log file
        enable_stdout: Whether to print to stdout

    Returns:
        Server logger instance
    """

    # Determine log file path
    if log_file is None:
        if mode == 'prod':
            log_file = 'server.log'
        elif not enable_stdout:
            log_file = 'server_dev.log'

    # Create formatters
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    simple_formatter = logging.Formatter('%(levelname)s: %(message)s')

    # ===== SERVER LOGGER =====
    server_logger = logging.getLogger('server')
    server_logger.setLevel(logging.DEBUG)
    server_logger.handlers.clear()
    server_logger.propagate = False  # Don't propagate to root logger

    # File handler for server logs (if specified)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        server_logger.addHandler(file_handler)

    # Stdout handler for server logs (dev mode)
    if mode == 'dev' and enable_stdout:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
        server_logger.addHandler(console_handler)

    return server_logger




def setup_client_logger(
    client_id: str,
    client_queue: asyncio.Queue,
    log_file: str | None = None,
    enable_stdout: bool = False,
) -> logging.Logger:
    """
    Setup a client-specific logger that sends messages to that client's queue.
    Called once per client connection.

    Args:
        client_id: Unique client identifier
        client_queue: The to_client asyncio.Queue for this specific client
        log_file: Optional log file path
        enable_stdout: Whether to also print to stdout (for debugging)

    Returns:
        Client-specific logger instance
    """

    # Create a unique logger for this client
    logger_name = f'wss.client.{client_id}'
    client_logger = logging.getLogger(logger_name)
    client_logger.setLevel(logging.DEBUG)
    client_logger.handlers.clear()
    client_logger.propagate = False  # Don't propagate to parent loggers

    # WebSocket handler (sends to this specific client's queue)
    # Only send INFO and above to client (DEBUG is for server-side debugging only)
    wss_handler = WebSocketHandler(client_queue)
    wss_handler.setLevel(logging.INFO)
    wss_handler.setFormatter(logging.Formatter('%(message)s'))
    client_logger.addHandler(wss_handler)

    # Optional stdout for debugging (shows ALL levels including DEBUG)
    if enable_stdout:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            logging.Formatter(f'[WSS-{client_id[:7]}] %(levelname)s: %(message)s')
        )
        client_logger.addHandler(console_handler)

    # Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(f'%(asctime)s - {logger_name} - %(levelname)s - %(message)s')
        )
        client_logger.addHandler(file_handler)

    return client_logger


def setup_worker_logger(
    worker_name: str,
    mp_queue: mp.Queue,
    enable_stdout: bool = False,
) -> logging.Logger:
    """
    Setup logging for a worker process.
    Called inside each worker process after it starts.

    Args:
        worker_name: Name of the worker
        mp_queue: Multiprocessing queue to send messages back to main process
        enable_stdout: Whether to also print to stdout

    Returns:
        Worker logger instance
    """

    logger_name = f'worker.{worker_name}'
    worker_logger = logging.getLogger(logger_name)
    worker_logger.setLevel(logging.DEBUG)
    worker_logger.handlers.clear()
    worker_logger.propagate = False

    # Multiprocessing handler (sends messages via mp.Queue)
    mp_handler = MultiprocessingHandler(mp_queue)
    mp_handler.setLevel(logging.DEBUG)
    mp_handler.setFormatter(logging.Formatter('%(message)s'))
    worker_logger.addHandler(mp_handler)

    # Optional stdout for debugging
    if enable_stdout:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(
            logging.Formatter(f'[WORKER-{worker_name}] %(levelname)s: %(message)s')
        )
        worker_logger.addHandler(console_handler)

    return worker_logger
