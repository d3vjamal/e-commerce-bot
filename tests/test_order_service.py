import requests

from services.order_service import OrderService, find_status
from utils.logger_config import LoggerConfig


class FakeApi:
    def __init__(self, status="PLACED", fail=False):
        self.calls, self.status, self.fail = [], status, fail

    def request(self, method, path, **kw):
        self.calls.append((method, path, kw.get("payload")))
        if self.fail:
            raise requests.ConnectionError("down")
        if path.startswith("/order-details/"):
            return {"data": {"status": self.status}}
        return {"ok": True}


def svc(**kw):
    api = FakeApi(**kw)
    return OrderService(LoggerConfig(), api=api), api


def test_find_status_nested():
    assert find_status({"data": {"order": {"orderStatus": "shipped"}}}) == "SHIPPED"


def test_cancel_open_order_calls_rest():
    s, api = svc()
    out = s.cancel_order("t", "7", "changed mind")
    assert out.success
    assert api.calls[-1] == ("POST", "/orders/7/cancel-by-customer", {"reason": "changed mind"})


def test_cancel_shipped_order_blocked_without_rest_call():
    s, api = svc(status="SHIPPED")
    out = s.cancel_order("t", "7", "x")
    assert out.error == "order_not_changeable"
    assert all(c[0] == "GET" for c in api.calls)


def test_modify_rejects_status_field():
    s, api = svc()
    out = s.modify_order("t", "7", {"status": "DELIVERED"})
    assert out.error == "fields_not_allowed" and api.calls == []


def test_modify_allowed_field_patches():
    s, api = svc()
    assert s.modify_order("t", "7", {"phone": "999"}).success
    assert api.calls[-1] == ("PATCH", "/orders/7", {"phone": "999"})


def test_network_failure_becomes_response():
    s, _ = svc(fail=True)
    assert s.list_my_orders("t").error == "connection_error"


def test_place_order_validates_and_posts():
    s, api = svc()
    assert s.place_order("t", {"paymentMethod": "COD"}).error == "invalid_order"
    assert api.calls == []
    assert s.place_order("t", {"addressId": "a1", "paymentMethod": "cod"}).success
    assert api.calls[-1] == (
        "POST", "/place-orders", {"addressId": "a1", "paymentMethod": "COD"}
    )


def test_modify_quantity_patches_items():
    s, api = svc()
    assert s.modify_item_quantity("t", "7", "i1", 3).success
    assert api.calls[-1] == (
        "PATCH", "/orders/7", {"items": [{"itemId": "i1", "quantity": 3}]}
    )


def test_modify_quantity_rejects_zero_and_locked():
    s, api = svc()
    assert s.modify_item_quantity("t", "7", "i1", 0).error == "invalid_quantity"
    assert api.calls == []
    s, api = svc(status="DELIVERED")
    assert s.modify_item_quantity("t", "7", "i1", 2).error == "order_not_changeable"
