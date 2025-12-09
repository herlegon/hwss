"""
WebSocket logging handler for forwarding hinstall log messages to WebSocket clients.
"""
import logging
import re
from typing import Callable, Optional
from api import EventMessage, InstallProgress


class HInstallWebSocketHandler(logging.Handler):
    """
    Custom logging handler that forwards hinstall log messages to WebSocket clients.
    
    This handler:
    - Forwards regular log messages (INFO, WARNING, ERROR, CRITICAL) as EventMessage type='msg'
    - Parses STATUS level messages with tags like [si], [ei], [pg] and converts to progress events
    - Sends EventMessage type='progress' for installation progress tracking
    """
    
    # Status message tag patterns
    TAG_PATTERN = re.compile(r'^\[([a-z]{2})\](.*)$')
    
    # Tag to event mapping
    PROGRESS_TAGS = {
        'sd': 'start_download',
        'ed': 'end_download',
        'fd': 'failed_download',
        'si': 'start_install',
        'ei': 'end_install',
        'if': 'install_failed',
        'df': 'download_failed',
    }
    
    def __init__(self, send_callback: Callable[[EventMessage], None]):
        """
        Initialize the WebSocket handler.
        
        Args:
            send_callback: Function to send EventMessage to the WebSocket client
        """
        super().__init__()
        self.send_callback = send_callback
        self.current_package: Optional[str] = None
        self.STATUS_LEVEL = 15  # Same as in hinstall.logger
    
    def emit(self, record: logging.LogRecord):
        """
        Forward log record to WebSocket client.
        
        Args:
            record: Log record to process
        """
        try:
            # Handle STATUS level messages (progress updates)
            if record.levelno == self.STATUS_LEVEL:
                self._handle_status(record)
            
            # Handle regular log messages (INFO and above)
            elif record.levelno >= logging.INFO:
                self._handle_log_message(record)
        
        except Exception:
            self.handleError(record)
    
    def _handle_log_message(self, record: logging.LogRecord):
        """
        Handle regular log messages and forward as EventMessage type='msg'.
        
        Args:
            record: Log record to process
        """
        level_name = record.levelname.lower()
        message = self.format(record)
        
        self.send_callback(EventMessage(
            type='msg',
            payload={'type': level_name, 'text': message}
        ))
    
    def _handle_status(self, record: logging.LogRecord):
        """
        Parse STATUS level messages and forward as progress events.
        
        Status messages use tags like:
        - [si]package_name - Start install
        - [ei]package_name - End install
        - [pg]75.5 - Progress percentage
        - [sd]package_name - Start download
        - etc.
        
        Args:
            record: Log record to process
        """
        message = record.getMessage()
        match = self.TAG_PATTERN.match(message)
        
        if not match:
            # No tag, skip
            return
        
        tag = match.group(1)
        content = match.group(2).strip()
        
        # Handle progress percentage
        if tag == 'pg':
            try:
                progress = float(content)
                if self.current_package:
                    self.send_callback(EventMessage(
                        type='progress',
                        payload=InstallProgress(
                            task_id='install',
                            package_name=self.current_package,
                            type='progress',
                            progress=int(progress)
                        )
                    ))
            except ValueError:
                pass
            return
        
        # Handle critical error
        if tag == 'ce':
            self.send_callback(EventMessage(
                type='msg',
                payload={'type': 'critical', 'text': content}
            ))
            return
        
        # Handle progress tags
        if tag in self.PROGRESS_TAGS:
            event_type = self.PROGRESS_TAGS[tag]
            package_name = content
            
            # Track current package for progress updates
            if tag in ('si', 'sd'):
                self.current_package = package_name
            elif tag in ('ei', 'ed', 'if', 'fd', 'df'):
                self.current_package = None
            
            # Send progress event
            self.send_callback(EventMessage(
                type='progress',
                payload={
                    'task_id': 'install',
                    'package_name': package_name,
                    'type': 'indet',
                    'progress': 0
                }
            ))
