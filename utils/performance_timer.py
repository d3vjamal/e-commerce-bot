from datetime import datetime, UTC
from time import perf_counter


class PerformanceTimer:

    def __init__(self, logger=None, operation="Operation"):
        self.logger = logger
        self.operation = operation

    def __enter__(self):

        self.start_time = datetime.now(UTC)
        self.start_perf = perf_counter()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):

        self.end_time = datetime.now(UTC)
        self.end_perf = perf_counter()

        self.duration_ms = round(
            (self.end_perf - self.start_perf) * 1000,
            2
        )

        message = (
            f"{self.operation} | "
            f"start_time={self.start_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC | "
            f"end_time={self.end_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC | "
            f"duration={self.duration_ms} ms"
        )

        if self.logger:
            self.logger.info(message)
        else:
            print(message)
