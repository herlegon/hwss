from pprint import pprint
import sys
import logging
import multiprocessing as mp

pprint(sys.path)

import asyncio
asyncio_logger = logging.getLogger("asyncio")
asyncio_logger.setLevel(logging.WARNING)

from hinstall import __version__
from .backend_server import start_wss, main_log

if __name__ == "__main__":
    mp.set_start_method('spawn')
    try:
        asyncio.run(start_wss())
    except Exception as e:
        main_log.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

    main_log.info("Process exit")




