import logging
from requests.exceptions import (
    ConnectionError,
    Timeout,
    HTTPError)

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception,
    before_sleep_log,
)


def is_retryable(exception):

    if isinstance(exception, HTTPError):
        response = getattr(exception, "response", None)
        if response:
            return response.status_code >= 500
        return False

    return isinstance(exception,(ConnectionError,Timeout,),)


retry_api_call = retry(
    retry=retry_if_exception(is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(
        multiplier=1,
        min=1,
        max=10,
    ),
    before_sleep=before_sleep_log(
        logging.getLogger(__name__),
        logging.WARNING,
    ),
    reraise=True,
)