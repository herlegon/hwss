import asyncio
from dataclasses import asdict
import logging
import logging.handlers
import queue
import sys
from typing import Literal

from api import EventMessage, MessageType, InstallProgress
import multiprocessing as mp

from hytils import red

# Custom log level for progress updates
PROGRESS_LEVEL = 25  # Between INFO (20) and WARNING (30)
logging.addLevelName(PROGRESS_LEVEL, 'PROGRESS')

# Server logger
slog: logging.Logger = None


class WsLoggingHandler(logging.Handler):
    """Handler that sends log messages as WebSocket EventMessages
    to a specific client
    """

    def __init__(self, client_queue: asyncio.Queue):
        """
        Args:
            client_queue: The to_client queue for a specific ClientConnectionHandler
        """
        super().__init__()
        self.client_queue = client_queue


    def emit(self, record: logging.LogRecord):
        try:
            # Special handling for PROGRESS level
            if record.levelno == PROGRESS_LEVEL:
                # The message should be an InstallProgress object
                if hasattr(record, 'progress_data'):
                    event_msg = EventMessage(
                        type='progress',
                        payload=record.progress_data
                    )
                else:
                    # Fallback if progress_data not found
                    return
            else:
                # Regular log message
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


# Note: We'll use Python's standard logging.handlers.QueueHandler for workers
# This is safer and more standard than custom implementation

class StdOutLoggerFormatter(logging.Formatter):
    LEVEL_PREFIX = {
        logging.DEBUG: "[D]",
        5: "[V]",
        logging.INFO: "[I]",
        # STATUS_LEVEL: "",
        logging.WARNING: "[W]",
        logging.ERROR: "[E]",
        logging.CRITICAL: "[C]",
    }

    def format(self, record: logging.LogRecord) -> str:
        level_no: int = record.levelno
        prefix: str = self.LEVEL_PREFIX.get(level_no, f"{level_no}")
        return f"{prefix} {record.getMessage()}"



def setup_queue_listener(
    log_queue: mp.Queue,
    log_file: str | None = None,
    devmode: bool = True,
) -> logging.handlers.QueueListener:
    """
    Setup a QueueListener that processes log records from all processes.
    This runs in the main process and writes to the log file.
    """
    handlers = []

    # File handler (writes to server.log)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
        # Filter out PROGRESS level messages
        file_handler.addFilter(lambda record: record.levelno != PROGRESS_LEVEL)
        handlers.append(file_handler)

    # Console handler (optional)
    console_handler = logging.StreamHandler(sys.stdout)
    if devmode:
        console_handler.setLevel(logging.DEBUG)
    else:
        console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(StdOutLoggerFormatter())
    # Filter out PROGRESS level messages
    console_handler.addFilter(lambda record: record.levelno != PROGRESS_LEVEL)
    handlers.append(console_handler)

    # Create and return the listener
    listener = logging.handlers.QueueListener(
        log_queue,
        *handlers,
        respect_handler_level=True
    )

    return listener




def setup_server_logging(
    log_queue: mp.Queue,
    devmode: bool = False,
) -> logging.Logger:
    # Server logger: trace all messages, because there are not
    # so many messages

    server_logger = logging.getLogger('server')
    server_logger.setLevel(logging.DEBUG)
    server_logger.handlers.clear()
    # Don't propagate to root logger
    server_logger.propagate = False

    # Sends all logs to centralized listener
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.setLevel(logging.DEBUG)
    server_logger.addHandler(queue_handler)

    # Optional stdout handler for dev mode (in addition to queue)
    # Not needed because it's already done by the centralized listener (queue handler)
    # if devmode:
    #     console_handler = logging.StreamHandler(sys.stdout)
    #     console_handler.setLevel(logging.INFO)
    #     console_handler.setFormatter(logging.Formatter('[server] %(levelname)s: %(message)s'))
    #     server_logger.addHandler(console_handler)

    return server_logger





def setup_client_logger(
    client_id: str,
    emit_queue: asyncio.Queue,
    log_queue: mp.Queue,
    devmode: bool = False,
) -> logging.Logger:
    """
    Setup a client-specific logger that sends messages to that client's queue.
    Called once per client connection.
    """

    # Create a unique logger for this client
    logger_name = f'wss.client.{client_id}'
    client_logger = logging.getLogger(logger_name)
    client_logger.setLevel(logging.DEBUG)
    client_logger.handlers.clear()
    client_logger.propagate = False

    # WebSocket handler (sends to this specific client's queue)
    # Only send INFO and above to client (DEBUG is for server-side debugging only)
    ws_logging_handler = WsLoggingHandler(emit_queue)
    ws_logging_handler.setLevel(logging.INFO)
    ws_logging_handler.setFormatter(logging.Formatter('%(message)s'))
    client_logger.addHandler(ws_logging_handler)

    # Queue handler for centralized file logging
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.setLevel(logging.DEBUG)
    client_logger.addHandler(queue_handler)

    # Optional stdout for debugging (shows ALL levels including DEBUG)
    # if devmode:
    #     console_handler = logging.StreamHandler(sys.stdout)
    #     console_handler.setLevel(logging.DEBUG)
    #     console_handler.setFormatter(
    #         logging.Formatter(f'[WSS-{client_id[:7]}] %(levelname)s: %(message)s')
    #     )
    #     client_logger.addHandler(console_handler)

    return client_logger



def setup_worker_logger(
    worker_name: str,
    emit_queue: mp.Queue,
    log_queue: mp.Queue,
    setup_hinstall: bool = True,
    devmode: bool = False,
) -> tuple[logging.Logger, logging.Handler | None]:
    """
    Setup logging for a worker process.
    Called inside each worker process after it starts.
    """

    logger_name = f'worker.{worker_name}'
    worker_logger = logging.getLogger(logger_name)
    worker_logger.setLevel(logging.DEBUG)
    worker_logger.handlers.clear()
    worker_logger.propagate = False

    ws_logging_handler = WsLoggingHandler(emit_queue)
    ws_logging_handler.setLevel(logging.INFO)  # Will include PROGRESS (25)
    ws_logging_handler.setFormatter(logging.Formatter('%(message)s'))
    worker_logger.addHandler(ws_logging_handler)


    # Queue handler (sends all logs to centralized listener in main process)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    queue_handler.setLevel(logging.DEBUG)
    worker_logger.addHandler(queue_handler)

    # Optional stdout for debugging
    # if devmode:
    #     console_handler = logging.StreamHandler(sys.stdout)
    #     console_handler.setLevel(logging.DEBUG)
    #     console_handler.setFormatter(
    #         logging.Formatter(f'[WORKER-{worker_name}] %(levelname)s: %(message)s')
    #     )
    #     worker_logger.addHandler(console_handler)

    # Add custom progress() method to logger
    def progress(self, progress_data: InstallProgress):
        """Log a progress update that will be sent to WebSocket client"""
        if self.isEnabledFor(PROGRESS_LEVEL):
            package_name = getattr(progress_data, 'package_name', 'unknown')
            record = self.makeRecord(
                self.name, PROGRESS_LEVEL, "(progress)", 0,
                f"Progress: {package_name}",
                (), None
            )
            # Attach the progress data to the record (convert to dict for serialization)
            record.progress_data = asdict(progress_data) if hasattr(progress_data, '__dataclass_fields__') else progress_data
            self.handle(record)

    # Bind the method to the logger instance
    import types
    worker_logger.progress = types.MethodType(progress, worker_logger)

    # Forward message to the websocket client
    hinstall_handler = None
    if setup_hinstall:
        try:
            from hinstall.logger import ilog
            from hinstall_ws_handler import HInstallWebSocketHandler

            # Remove all StreamHandlers (stdout) from ilog to prevent duplicate messages
            # (since queue_handler will forward them to the central listener which handles stdout)
            for handler in ilog.handlers[:]:
                if isinstance(handler, logging.StreamHandler):
                    ilog.removeHandler(handler)

            # Create a callback that sends to emit_queue
            def send_to_emit_queue(event_msg):
                emit_queue.put(event_msg)

            # Create and add the handler
            hinstall_handler = HInstallWebSocketHandler(send_to_emit_queue)
            hinstall_handler.setLevel(logging.INFO)
            ilog.addHandler(hinstall_handler)
            
            # Also add the queue handler to ilog so messages go to the server log file
            ilog.addHandler(queue_handler)
            
            worker_logger.debug(f"Added WebSocket handler to hinstall logger")

        except Exception as e:
            worker_logger.warning(f"Failed to setup hinstall handler: {e}")
            hinstall_handler = None

    return worker_logger, hinstall_handler

