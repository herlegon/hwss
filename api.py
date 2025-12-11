import json
from typing import Literal
from dataclasses import asdict, dataclass
from typing import Any, Optional


RequestType = Literal[
    'heartbeat',
    'identify',
    'shutdown',
    'telemetry',

    # Applications
    'install',
    'convert',
]


ResponseType = Literal[
    'pong',
    'identity',
    'shutdown',

    # Applications
    'install',
    'convert',
]



EventType = Literal[
    'log',
    # 'msg',
    'telemetry',
    'status',
    'progress',
]


InstallTaskId = Literal[
    'stop',
    'parse',
    'install',
]



@dataclass(slots=True)
class RequestMessage:
    type: RequestType
    payload: dict | None = None



@dataclass(slots=True)
class ResponseMessage:
    type: ResponseType
    payload: dict | None = None


MessageType = Literal[
    'critical',
    'error',
    'warning',
    'info',
    'debug'
]




@dataclass(slots=True)
class EventMessage:
    type: EventType
    payload: Any


@dataclass(slots=True)
class WssIdentity:
    organization: str
    app: str
    clients: int



@dataclass(slots=True)
class ParseTask:
    task_id: InstallTaskId = 'parse'
    app_name: str = ""
    cfg: str = ""
    cache: bool = True
    local_backend: bool = False
    reinstall: bool = False
    use_local_rehost: bool = False
    local_rehost: str = ""



@dataclass(slots=True)
class InstallTask:
    task_id: InstallTaskId = 'install'
    stage: int = -1



@dataclass(slots=True)
class InstallTaskResult:
    task_id: InstallTaskId = 'install'
    stage: int = -1
    status: Literal['parsed', 'installed', 'failed', 'error'] = ''
    restart: bool = False



@dataclass(slots=True)
class InstallProgress:
    task_id: InstallTaskId = 'install'
    package_name: str = ""
    status: str = ""
    type: Literal['progress', 'indet'] = 'progress'
    progress: float = 0.



def serialize(msg: RequestMessage) -> str:
    """Serialize object to JSON string"""
    if hasattr(msg, '__dataclass_fields__'):
        return json.dumps(asdict(msg))

    elif hasattr(msg, '__dict__'):
        return json.dumps(vars(msg))

    return json.dumps(msg)



def deserialize(msg: ResponseMessage | EventMessage) -> dict | None:
    try:
        return json.loads(msg)

    except json.JSONDecodeError:
        pass

    return None



# Packets
#----------------------------------------------------------------------
#   Requests
#     'type': RequestType
#     'payload': dict[str, Any] | None
#
#   Response
#     'type': ResponseType
#     'payload': dict[str, Any] | None
#
#   Events
#     'type': EventType
#     'payload': dict[str, Any] | None


# Server
#----------------------------------------------------------------------
# request = 'heartbeat'
#   payload=None

# request = 'identify'
#   payload = None
#
# response: ResponseType = 'identity'
#   payload = dict
#       'organization'
#       'app'
#       'clients'

# request = 'restart'
#   payload=None

# request = 'shutdown'
#   payload=None

# request = 'telemetry'
#   payload=dict
#       'frequency': 0 (one-shot) or > 0.2 (cyclic)
#       todo: all, only some subparts
#           more complex scenario?


# Setup/Install Tasks
#----------------------------------------------------------------------
# request: RequestType = 'setup'

# task_id = 'parse'
#   {
#       'task_id': SetupTaskId
#       'cfg': str (json.dumps)
#       'local_backend': bool
#       'reinstall': bool
#       'use_local_rehost': bool
#       'local_rehost': str
#   }

# task_id: 'install'
#   {
#       'task_id': SetupTaskId
#       'stage_no': int
#   }


# Responses
#----------------------------------------------------------------------
# ...




@dataclass
class WorkerCommand:
    cmd: str
    payload: Optional[dict] = None

@dataclass
class WorkerResponse:
    type: str
    payload: Any = None

