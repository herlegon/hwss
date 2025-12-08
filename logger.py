import logging


class AbbreviatedLevelFilter(logging.Filter):
    # A dictionary to map full level names to abbreviated names
    level_map = {
        logging.DEBUG: '[V]',
        logging.INFO: '[I]',
        logging.WARNING: '[W]',
        logging.ERROR: '[E]',
        logging.CRITICAL: '[C]',
    }

    def filter(self, record):
        record.levelname = self.level_map.get(record.levelno, record.levelname)
        return True


# Set up logging with custom format
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(message)s")

# Add custom filters to the root logger
slog = logging.getLogger()
slog.addFilter(AbbreviatedLevelFilter())


