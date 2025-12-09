import logging
import logging.handlers
import multiprocessing as mp
from typing import Optional


# Define custom log levels for client messages
# These levels are higher than standard levels to ensure they're always processed
CLIENT_CRITICAL = logging.CRITICAL + 1
CLIENT_ERROR = logging.ERROR + 1
CLIENT_WARNING = logging.WARNING + 1
CLIENT_INFO = logging.INFO + 1
CLIENT_DEBUG = logging.DEBUG + 1

# Register custom level names
logging.addLevelName(CLIENT_CRITICAL, 'CLIENT_CRITICAL')
logging.addLevelName(CLIENT_ERROR, 'CLIENT_ERROR')
logging.addLevelName(CLIENT_WARNING, 'CLIENT_WARNING')
logging.addLevelName(CLIENT_INFO, 'CLIENT_INFO')


class AbbreviatedLevelFilter(logging.Filter):
    """Filter to abbreviate log level names for cleaner output"""
    level_map = {
        logging.DEBUG: '[V]',
        logging.INFO: '[I]',
        logging.WARNING: '[W]',
        logging.ERROR: '[E]',
        logging.CRITICAL: '[C]',
        CLIENT_INFO: '[CI]',
        CLIENT_WARNING: '[CW]',
        CLIENT_ERROR: '[CE]',
        CLIENT_CRITICAL: '[CC]',
    }

    def filter(self, record):
        record.levelname = self.level_map.get(record.levelno, record.levelname)
        return True


class ClientQueueHandler(logging.Handler):
    """Handler that sends client-level messages to a multiprocessing queue"""

    def __init__(self, result_queue: Optional[mp.Queue] = None):
        super().__init__()
        self.result_queue = result_queue

    def set_queue(self, result_queue: mp.Queue):
        """Set or update the result queue"""
        self.result_queue = result_queue

    def emit(self, record: logging.LogRecord):
        """Send client messages to the queue"""
        if self.result_queue is None:
            return

        # Only handle CLIENT_* levels
        if record.levelno not in (
            CLIENT_INFO, CLIENT_WARNING, CLIENT_ERROR, CLIENT_CRITICAL
        ):
            return

        try:
            # Map custom levels to message types
            level_to_type = {
                CLIENT_DEBUG: 'debug',
                CLIENT_INFO: 'info',
                CLIENT_WARNING: 'warning',
                CLIENT_ERROR: 'error',
                CLIENT_CRITICAL: 'critical',
            }

            msg_type = level_to_type.get(record.levelno, 'info')

            # Import here to avoid circular dependency
            from api import EventMessage

            message = EventMessage(
                'msg',
                payload={'type': msg_type, 'text': record.getMessage()}
            )

            self.result_queue.put(message)

        except Exception:
            # Silently fail to avoid breaking the logging system
            pass


class CustomLogger(logging.Logger):
    """Extended logger with client-specific methods"""

    def client_debug(self, msg, *args, **kwargs):
        """Log info message to both client and stdout"""
        if self.isEnabledFor(CLIENT_DEBUG):
            self._log(CLIENT_DEBUG, msg, args, **kwargs)


    def client_info(self, msg, *args, **kwargs):
        """Log info message to both client and stdout"""
        if self.isEnabledFor(CLIENT_INFO):
            self._log(CLIENT_INFO, msg, args, **kwargs)


    def client_warning(self, msg, *args, **kwargs):
        """Log warning message to both client and stdout"""
        if self.isEnabledFor(CLIENT_WARNING):
            self._log(CLIENT_WARNING, msg, args, **kwargs)


    def client_error(self, msg, *args, **kwargs):
        """Log error message to both client and stdout"""
        if self.isEnabledFor(CLIENT_ERROR):
            self._log(CLIENT_ERROR, msg, args, **kwargs)


    def client_critical(self, msg, *args, **kwargs):
        """Log critical message to both client and stdout"""
        if self.isEnabledFor(CLIENT_CRITICAL):
            self._log(CLIENT_CRITICAL, msg, args, **kwargs)


# Set custom logger class
logging.setLoggerClass(CustomLogger)

# Create and configure the main logger
slog: CustomLogger = logging.getLogger('hwss')
slog.setLevel(logging.DEBUG)

# Remove any existing handlers
slog.handlers.clear()

# Custom formatter that includes process name for worker processes
class WorkerAwareFormatter(logging.Formatter):
    """Formatter that includes process name for non-MainProcess logs"""
    def format(self, record):
        # Include process name if not from MainProcess
        if record.processName != "MainProcess":
            # Format: [LEVEL] [ProcessName] message
            return f"{record.levelname} [{record.processName}] {record.getMessage()}"
        else:
            # Format: [LEVEL] message
            return f"{record.levelname} {record.getMessage()}"

# Create console handler with formatter
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(WorkerAwareFormatter())
console_handler.addFilter(AbbreviatedLevelFilter())
slog.addHandler(console_handler)

# Create client queue handler (queue will be set later)
client_queue_handler = ClientQueueHandler()
client_queue_handler.setLevel(CLIENT_INFO)
slog.addHandler(client_queue_handler)

# Prevent propagation to root logger
slog.propagate = False


def set_debug_mode(enabled: bool):
    """Enable or disable debug output to stdout"""
    if enabled:
        console_handler.setLevel(logging.DEBUG)
        slog.debug("Debug mode enabled")
    else:
        console_handler.setLevel(logging.INFO)


def set_client_queue(result_queue: mp.Queue):
    """Set the queue for sending messages to the client"""
    client_queue_handler.set_queue(result_queue)


