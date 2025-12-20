import os
from pathlib import Path
import sys
import logging

sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parent.parent))

import asyncio
asyncio_logger = logging.getLogger("asyncio")
asyncio_logger.setLevel(logging.WARNING)

import multiprocessing as mp
from .backend_server import start_wss, main_log


if __name__ == "__main__":
    mp.set_start_method('spawn')
    try:
        asyncio.run(start_wss())
    except Exception as e:
        main_log.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    main_log.info("Process exit")




