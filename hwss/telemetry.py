import asyncio
import psutil
from websockets import (
    ServerConnection,
    ConnectionClosedOK,
    ConnectionClosedError,


)
from hytils import red, yellow
from utils import send_json
from .logger import slog
import json
from websockets import (
    ServerConnection,
    ConnectionClosed,
)
from .logger import slog


TELEMETRY_RATE: float = 1.5


def get_system_usage() -> dict:
    ram = psutil.virtual_memory().used / (1024**2)
    cpu = psutil.cpu_percent(interval=None)
    data = {"type": "system_usage", "cpu": cpu, "ram": ram, "vram": 0}
    return data


async def send_json(ws: ServerConnection, data: dict):
    """Send JSON safely; ignore if connection is closed."""
    try:
        await ws.send(json.dumps(data))
    except ConnectionClosed:
        slog.debug("send_json: connection closed, skipping send")




async def telemetry_loop(ws: ServerConnection):
    try:
        while True:
            data = get_system_usage()
            await send_json(ws, data)
            await asyncio.sleep(TELEMETRY_RATE)

    except ConnectionClosedOK:
        slog.info("Telemetry loop: client disconnected normally")

    except ConnectionClosedError as e:
        slog.warning(f"Telemetry loop: connection closed with error: {e}")

    except asyncio.CancelledError:
        slog.info("Telemetry loop cancelled")

    except Exception as e:
        slog.exception(f"Telemetry loop crashed: {e}")


