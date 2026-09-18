#!

import logging
import uuid


class Logger(logging.Logger):
    """
    This is a logger class
    """

    def __init__(self, name: str, logger_config: any) -> None:
        """
        This Init method
        """
        super().__init__(name, logger_config.log_level)

        self.setLevel(logger_config.log_level)
        self.propagate = False

        # Adding a console handler
        console_handler = ConsoleHandler(logger_config)
        console_handler.addFilter(SeedFilter(logger_config))
        self.addHandler(console_handler)

        # Apply filter to uvicorn.access logger
        access_logger = logging.getLogger("uvicorn.access")
        access_logger.addFilter(FilteredAccessLogFilter())


#######################################################################
# Class for Console Log Handler
#######################################################################
class ConsoleHandler(logging.StreamHandler):
    def __init__(self, logger_config: any) -> None:
        super().__init__()
        formatter = logging.Formatter(
            logger_config.log_format, datefmt=logger_config.date_format
        )
        self.setFormatter(formatter)
        self.setLevel(logger_config.log_level)


#######################################################################
# Class for Seeding the Log
#######################################################################
class SeedFilter(logging.Filter):
    def __init__(self, logger_config: any):
        super().__init__()
        self.seed = logger_config.seed or str(uuid.uuid4())

    def filter(self, record):
        if not hasattr(record, "seed"):
            record.seed = self.seed
        return True


class FilteredAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Hide logs containing the health check endpoint
        return '"GET /ping HTTP/1.1" 200' not in record.getMessage()
