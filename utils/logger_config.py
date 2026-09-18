import logging
import uuid

from configs.settings import settings


class LoggerConfig:
    def __init__(
        self,
        log_level: str = None,
        log_format: str = None,
        log_date_format: str = None,
    ):
        level = log_level or settings.log_level

        # ✅ Convert string → logging constant
        self.log_level = (
            getattr(logging, level.upper(), logging.INFO)
            if isinstance(level, str)
            else level
        )

        # ✅ Safe format (includes seed)
        self.log_format = (
            log_format
            or settings.log_format
            or "[ %(asctime)s | %(levelname)s | %(name)s | %(seed)s ] %(message)s"
        )

        self.date_format = (
            log_date_format or settings.log_date_format or "%Y-%m-%d %H:%M:%S"
        )

        self.seed = str(uuid.uuid4())

        self.enable_strands_log = settings.enable_strands_log
