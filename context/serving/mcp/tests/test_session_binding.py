"""BearerAuth binds each MCP session to the caller that created it. Runs without a database or a network: the
wrapper is driven directly with a stand-in ASGI app that issues session ids the way the SDK does."""
import asyncio
import os
import unittest

for k, v in {"NEO4J_URI": "bolt://dummy:7687", "NEO4J_USER": "dummy", "NEO4J_PASSWORD": "dummy"}.items():
    os.environ.setdefault(k, v)

import server  # noqa: E402

TOKENS = {"alice": b"token-a", "bob": b"token-b"}


class FakeMcpApp:
    """Answers 200. When the request has no session id it issues a new one, like an MCP initialize."""

    def __init__(self):
        self.calls = 0
        self.next = 0

    async def __call__(self, scope, receive, send):
        self.calls += 1
        headers = [(b"content-type", b"application/json")]
        if b"mcp-session-id" not in dict(scope["headers"]):
            self.next += 1
            headers.append((b"mcp-session-id", f"s{self.next}".encode()))
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"{}"})


def request(wrapper, token=None, sid=None, method="POST", path="/mcp"):
    """Send one request through the wrapper; return (status, response headers)."""
    headers = []
    if token is not None:
        headers.append((b"authorization", b"Bearer " + token))
    if sid is not None:
        headers.append((b"mcp-session-id", sid))
    scope = {"type": "http", "method": method, "path": path, "headers": headers}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(wrapper(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], dict(start.get("headers", []))


class SessionBindingTests(unittest.TestCase):
    def setUp(self):
        self.saved = (server.TOKENS, server.MAX_SESSIONS)
        server.TOKENS = TOKENS
        self.app = FakeMcpApp()
        self.auth = server.BearerAuth(self.app)

    def tearDown(self):
        server.TOKENS, server.MAX_SESSIONS = self.saved

    def open_session(self, token):
        status, headers = request(self.auth, token)
        self.assertEqual(status, 200)
        return headers[b"mcp-session-id"]

    def test_owner_can_use_its_session(self):
        sid = self.open_session(b"token-a")
        self.assertEqual(request(self.auth, b"token-a", sid)[0], 200)

    def test_another_caller_cannot_use_the_session(self):
        sid = self.open_session(b"token-a")
        calls = self.app.calls
        self.assertEqual(request(self.auth, b"token-b", sid)[0], 404)
        self.assertEqual(self.app.calls, calls, "the refused request must not reach the MCP app")

    def test_unknown_session_is_refused(self):
        self.assertEqual(request(self.auth, b"token-a", b"never-issued")[0], 404)
        self.assertEqual(self.app.calls, 0)

    def test_delete_by_owner_forgets_the_session(self):
        sid = self.open_session(b"token-a")
        self.assertEqual(request(self.auth, b"token-a", sid, method="DELETE")[0], 200)
        self.assertEqual(request(self.auth, b"token-a", sid)[0], 404)

    def test_delete_by_another_caller_is_refused_and_keeps_the_session(self):
        sid = self.open_session(b"token-a")
        self.assertEqual(request(self.auth, b"token-b", sid, method="DELETE")[0], 404)
        self.assertEqual(request(self.auth, b"token-a", sid)[0], 200)

    def test_oldest_sessions_are_forgotten_beyond_the_cap(self):
        server.MAX_SESSIONS = 2
        first, second, third = (self.open_session(b"token-a") for _ in range(3))
        self.assertEqual(request(self.auth, b"token-a", first)[0], 404)
        self.assertEqual(request(self.auth, b"token-a", second)[0], 200)
        self.assertEqual(request(self.auth, b"token-a", third)[0], 200)

    def test_token_and_health_checks_are_unchanged(self):
        self.assertEqual(request(self.auth)[0], 401)
        self.assertEqual(request(self.auth, b"wrong")[0], 401)
        self.assertEqual(request(self.auth, path="/healthz")[0], 200)
        self.assertEqual(self.app.calls, 0)


if __name__ == "__main__":
    unittest.main()
