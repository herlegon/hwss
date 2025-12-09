from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class WorkerCommand:
    cmd: str                 # "parse", "convert", "cancel", "shutdown"
    payload: Optional[dict] = None

@dataclass
class WorkerResponse:
    type: str                # "progress", "log", "result", "error", "status"
    payload: Any = None
