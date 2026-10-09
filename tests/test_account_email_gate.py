from types import SimpleNamespace

from tools.ecommerce_tools import AddressTools, UserAuthTools
from utils.logger_config import LoggerConfig


class FakeState:
    def __init__(self, data):
        self.data = data

    def get(self, _):
        return self.data

    def set(self, _, value):
        self.data = value


def ctx(user):
    data = {"auth_state": {"token": "t", "user": user, "verification_status": "PASS"}}
    return SimpleNamespace(agent=SimpleNamespace(state=FakeState(data)))


def verify(tools, email, c):
    return tools.verify_account_email._tool_func(email, c)


def test_profile_update_blocked_until_email_verified():
    tools = UserAuthTools(LoggerConfig())
    c = ctx({"id": "u1", "email": "me@example.com"})
    out = tools.update_my_profile._tool_func({"name": "x"}, c)
    assert out["error"] == "email_not_verified"


def test_address_edit_and_delete_need_no_email_verification():
    addr = AddressTools(LoggerConfig())
    c = ctx({"id": "u1", "email": "me@example.com"})
    calls = []
    addr._call = lambda tc, m, p, **kw: calls.append((m, p)) or {"data": []}
    out = addr.update_address._tool_func("a1", {"city": "x"}, c)
    assert out.get("error") != "email_not_verified"
    addr.delete_address._tool_func("a1", c)
    assert ("DELETE", "/user-address/a1") in calls


def test_wrong_email_counts_attempts_then_locks():
    tools = UserAuthTools(LoggerConfig())
    c = ctx({"id": "u1", "email": "me@example.com"})
    for _ in range(3):
        assert verify(tools, "bad@x.com", c)["error"] == "email_mismatch"
    assert verify(tools, "me@example.com", c)["error"] == "too_many_attempts"


def test_matching_email_verifies_case_insensitively():
    tools = UserAuthTools(LoggerConfig())
    c = ctx({"id": "u1", "email": "me@example.com"})
    assert verify(tools, " ME@example.com ", c) == {"status": "verified"}
    assert tools._is_email_verified(c) is True


def test_update_address_merges_onto_saved_address_and_drops_locked_fields():
    addr = AddressTools(LoggerConfig())
    c = ctx({"id": "u1", "email": "me@example.com"})
    sent = {}

    def fake_call(tool_context, method, path, **kw):
        if method == "GET":
            return {"data": [{"_id": "a1", "line1": "old", "city": "X", "userId": "u1"}]}
        sent.update(method=method, path=path, payload=kw["payload"])
        return {"success": True}

    addr._call = fake_call
    addr.update_address._tool_func("a1", {"city": "Y", "_id": "evil"}, c)
    assert sent["path"] == "/user-address/a1"
    assert sent["payload"]["city"] == "Y"
    assert sent["payload"]["line1"] == "old"
    assert sent["payload"]["_id"] == "a1"
    assert addr.update_address._tool_func("a1", {"_id": "z"}, c)["error"] == "no_updates"


def test_add_address_validates_and_injects_user_id():
    addr = AddressTools(LoggerConfig())
    c = ctx({"id": "u1", "email": "me@example.com"})
    bad = addr.add_address._tool_func({"name": "A", "phone": "123", "pincode": "12"}, c)
    assert bad["error"] == "invalid_address"
    assert set(bad["fields"]) == {"phone", "pincode", "addressLine1", "city"}

    sent = {}
    addr._call = lambda tc, m, p, **kw: sent.update(method=m, payload=kw["payload"]) or {}
    addr.add_address._tool_func(
        {"name": "A", "phone": "+91 98765 43210", "pincode": 560001,
         "addressLine1": "1 MG Rd", "city": "Bengaluru"}, c)
    assert sent["method"] == "PUT"
    assert sent["payload"]["userId"] == "u1"
    assert sent["payload"]["phone"] == "9876543210"
    assert sent["payload"]["pincode"] == "560001"
    assert sent["payload"]["addressType"] == "home"


def test_401_from_backend_becomes_token_expired():
    from types import SimpleNamespace as NS

    addr = AddressTools(LoggerConfig())
    c = ctx({"id": "u1"})

    def boom(*a, **k):
        err = Exception("401")
        err.response = NS(status_code=401)
        raise err

    addr.api = NS(request=boom)
    assert addr.get_addresses._tool_func(c)["error"] == "token_expired"
