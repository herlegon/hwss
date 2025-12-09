# Logging System Documentation

## Overview

The logging system has been refactored to use `slog` (structured logging) with custom log levels to handle both client communication and debug output.

## Custom Log Levels

### Client Levels (sent to client + stdout)
- `CLIENT_CRITICAL` (51) - Critical errors sent to client
- `CLIENT_ERROR` (41) - Errors sent to client  
- `CLIENT_WARNING` (31) - Warnings sent to client
- `CLIENT_INFO` (21) - Info messages sent to client

### Standard Levels (stdout only)
- `CRITICAL` (50) - Critical errors (stdout only)
- `ERROR` (40) - Errors (stdout only)
- `WARNING` (30) - Warnings (stdout only)
- `INFO` (20) - Info messages (stdout only)
- `DEBUG` (10) - Debug messages (stdout only, requires --debug flag)

## Usage

### In Worker Processes (install_worker.py)

```python
from logger import slog, set_client_queue

# In the worker's run() method, set up the client queue
set_client_queue(self.result_queue)

# Messages sent to client AND stdout
slog.client_info("All packages installed")
slog.client_warning("Package version mismatch")
slog.client_error("Failed to install package")
slog.client_critical("Critical installation failure")

# Messages sent to stdout only
slog.debug("Detailed debug information")  # Only shown with --debug
slog.info("General information")
slog.warning("Warning message")
slog.error("Error message")
slog.critical("Critical error")
```

### In Main Server (wss.py)

```python
from logger import slog, set_debug_mode

# Enable/disable debug mode based on command-line argument
set_debug_mode(args.debug)

# Use standard logging
slog.info("Server starting")
slog.debug("Detailed server state")  # Only shown with --debug
```

## Command-Line Arguments

### --debug Flag

Enable debug output to stdout:

```bash
python wss.py --debug
```

Without `--debug`, only INFO and above messages are shown to stdout.

## Architecture

### ClientQueueHandler

A custom logging handler that intercepts `CLIENT_*` level messages and sends them to a multiprocessing queue. The queue is monitored by the `ClientConnectionHandler` which forwards messages to the websocket client.

### Message Flow

1. Worker calls `slog.client_info("message")`
2. Logger emits log record with level `CLIENT_INFO`
3. `ClientQueueHandler` intercepts the record
4. Handler creates an `EventMessage` and puts it in the result queue
5. `ClientConnectionHandler.worker_result_loop()` reads from queue
6. Message is sent to client via websocket

### Abbreviated Level Names

Log output uses abbreviated level names for cleaner display:
- `[V]` - DEBUG (Verbose)
- `[I]` - INFO
- `[W]` - WARNING
- `[E]` - ERROR
- `[C]` - CRITICAL
- `[CI]` - CLIENT_INFO
- `[CW]` - CLIENT_WARNING
- `[CE]` - CLIENT_ERROR
- `[CC]` - CLIENT_CRITICAL

### Worker Process Identification

When logging from worker processes, the console output automatically includes the process name to help identify the source:
- Main process: `[I] Server starting`
- Worker process: `[CI] [InstallWorker-1] Package installed`

The process name is only added to console output (stdout). Messages sent to the client queue do not include the process name prefix.


## Migration from Old System

### Before (install_worker.py)

```python
def send_info(self, text: str) -> None:
    self.send(EventMessage('msg', payload={'type': 'info', 'text': text}))

def send_error(self, text: str) -> None:
    self.send(EventMessage('msg', payload={'type': 'error', 'text': text}))

# Usage
self.send_info("Package installed")
self.send_error("Installation failed")
```

### After

```python
# No helper methods needed, use logger directly
slog.client_info("Package installed")
slog.client_error("Installation failed")
```

## Benefits

1. **Unified Logging**: Single logging interface for all messages
2. **Debug Control**: Easy enable/disable of debug output via `--debug` flag
3. **Separation of Concerns**: Clear distinction between client messages and internal logs
4. **Standard Logging**: Uses Python's standard logging framework
5. **Flexibility**: Easy to add new handlers (file logging, remote logging, etc.)
6. **Type Safety**: Custom logger class with type hints
