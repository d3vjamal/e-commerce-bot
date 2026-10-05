import requests

from utils.logger_config import LoggerConfig
from utils.response import ResponseBuilder

rb = ResponseBuilder(LoggerConfig())


def _resp(status, body=b'{"a": 1}'):
    r = requests.Response()
    r.status_code = status
    r._content = body
    r.reason = "Reason"
    return r


def test_success():
    out = rb.from_response(_resp(200)).to_dict()
    assert out == {"success": True, "status_code": 200, "data": {"a": 1}}


def test_http_error_uses_backend_message():
    out = rb.from_response(_resp(400, b'{"message": "bad order"}'))
    assert not out.success and out.error == "http_400" and out.message == "bad order"


def test_exceptions_map_to_codes():
    assert rb.from_exception(requests.Timeout()).error == "timeout"
    assert rb.from_exception(requests.ConnectionError()).error == "connection_error"
    assert rb.from_exception(ValueError("x")).message == "x"


def test_builder_never_raises():
    assert rb.from_response(None).error == "response_build_failed"
