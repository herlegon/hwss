from typing import Literal
from dataclasses import dataclass
from typing import Any, Optional



RequestType = Literal[
    'heartbeat',
    'identify',
    'restart',
    'shutdown',
    'telemetry',

    # applications:
    'setup',
    'convert',
    # ...
]


ResponseType = Literal[
    'pong',
    'identity',
    'setup',
]


EventType = Literal[
    'msg',
    'telemetry',
    'status',
]


SetupTaskId = Literal[
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



@dataclass(slots=True)
class EventMessage:
    type: EventType
    payload: dict | None = None




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
#       'use_local_host': bool
#       'local_host': str
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
    cmd: str                 # "parse", "convert", "cancel", "shutdown"
    payload: Optional[dict] = None

@dataclass
class WorkerResponse:
    type: str                # "progress", "log", "result", "error", "status"
    payload: Any = None

