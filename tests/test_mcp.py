"""Testes da ponte MCP (servidor falso via stdio) e do OAuth do Notion (rede simulada)."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from agent.harness import run_turn
from agent.mcp_bridge import CONNECTED, DISABLED, ERROR, UNAUTHORIZED, McpManager, ServerSpec, stdio_transport
from integrations import notion_oauth
from integrations.notion_oauth import NotAuthorized, NotionAuthError, NotionOAuth
from tests.test_agent import FakeLLM, FakeMessage, tool_call

FAKE_SERVER = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"


def fake_spec(**overrides) -> ServerSpec:
    log = Path(tempfile.gettempdir()) / "stories-fake-mcp.log"
    defaults = dict(
        name="fake", group="azure", prefix="fake",
        open_transport=stdio_transport(sys.executable, [str(FAKE_SERVER)], {}, log),
        read_only_names=frozenset({"no_annotation_listed"}),
        hidden_names=frozenset({"dup_thing"}),
        fingerprint="v1",
    )
    defaults.update(overrides)
    return ServerSpec(**defaults)


def wait_for(manager, name, states, timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if manager.servers[name].state in states:
            return
        time.sleep(0.2)
    raise AssertionError(f"estado final {manager.servers[name].state}: {manager.servers[name].error}")


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.manager = McpManager()
        self.addCleanup(self.manager.close)

    def connect(self, spec=None):
        self.manager.configure({"fake": spec or fake_spec()})
        wait_for(self.manager, "fake", {CONNECTED, ERROR, UNAUTHORIZED})
        return {t.name: t for t in self.manager.tools("fake")}

    def test_exposes_only_read_only_tools(self):
        tools = self.connect()
        self.assertEqual(set(tools), {"fake__read_thing", "fake__no_annotation_listed", "fake__boom"})
        self.assertTrue(all(t.group == "azure" and not t.needs_approval for t in tools.values()))
        self.assertEqual(tools["fake__read_thing"].spec()["function"]["parameters"]["properties"]["key"]["type"], "string")

    def test_only_names_curates_the_exposed_tools(self):
        tools = self.connect(fake_spec(only_names=frozenset({"read_thing", "write_thing"})))
        self.assertEqual(set(tools), {"fake__read_thing"})   # a de escrita continua fora mesmo se listada

    def test_call_through_harness_and_error_mapping(self):
        tools = self.connect()
        llm = FakeLLM([
            FakeMessage(tool_calls=[tool_call("fake__read_thing", {"key": "abc"}, "a"),
                                    tool_call("fake__boom", {}, "b"),
                                    tool_call("fake__read_thing", {}, "c")]),
            FakeMessage("fim"),
        ])
        result = run_turn(llm, "s", [], list(tools.values()))
        self.assertEqual(result.steps[0].output, "valor de abc")
        self.assertTrue(result.steps[1].error)
        self.assertIn("boom", result.steps[1].output)     # o servidor MCP esconde o detalhe da exceção
        self.assertTrue(result.steps[2].error)            # falta o argumento obrigatório (validado antes)

    def test_status_and_reconfigure_without_change_keeps_connection(self):
        self.connect()
        task = self.manager.servers["fake"].task
        self.manager.configure({"fake": fake_spec()})     # mesmo fingerprint
        self.assertIs(self.manager.servers["fake"].task, task)
        self.assertEqual(self.manager.status()["fake"]["state"], CONNECTED)

    def test_fingerprint_change_reconnects_and_none_disables(self):
        self.connect()
        old_task = self.manager.servers["fake"].task
        self.manager.configure({"fake": fake_spec(fingerprint="v2")})
        wait_for(self.manager, "fake", {CONNECTED})
        self.assertIsNot(self.manager.servers["fake"].task, old_task)
        self.manager.configure({"fake": None})
        self.assertEqual(self.manager.servers["fake"].state, DISABLED)
        self.assertEqual(self.manager.tools("fake"), [])

    def test_unauthorized_marker_and_restart(self):
        self.manager.configure({"fake": fake_spec()}, {"fake": "precisa autorizar"})
        self.assertEqual(self.manager.status()["fake"], {"state": UNAUTHORIZED, "error": "precisa autorizar", "tools": 0})
        self.manager.restart("fake")
        wait_for(self.manager, "fake", {CONNECTED})
        self.assertEqual(len(self.manager.tools("fake")), 3)

    def test_connection_failure_becomes_visible_error(self):
        spec = fake_spec(open_transport=stdio_transport("comando-que-nao-existe-xyz", [], {}, Path(tempfile.gettempdir()) / "x.log"))
        self.manager.configure({"fake": spec})
        wait_for(self.manager, "fake", {ERROR})
        self.assertTrue(self.manager.servers["fake"].error)
        self.assertEqual(self.manager.tools("fake"), [])


class NotionOAuthTests(unittest.TestCase):
    META = {"issuer": "https://mcp.notion.com", "authorization_endpoint": "https://mcp.notion.com/authorize",
            "token_endpoint": "https://mcp.notion.com/token", "registration_endpoint": "https://mcp.notion.com/register"}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.oauth = NotionOAuth(Path(self.tmp.name) / "auth.json", "https://mcp.notion.com/mcp")
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_http(self, responses):
        def fake(url, *, payload=None, form=None):
            self.calls.append((url, payload, form))
            for suffix, response in responses.items():
                if url.endswith(suffix):
                    return response
            raise AssertionError(f"chamada inesperada: {url}")
        return mock.patch.object(notion_oauth, "_http", fake)

    def discovery(self):
        return {"/.well-known/oauth-protected-resource": {"authorization_servers": ["https://mcp.notion.com"]},
                "/.well-known/oauth-authorization-server": self.META}

    def test_full_flow_pkce_and_tokens(self):
        responses = {**self.discovery(), "/register": {"client_id": "cid"},
                     "/token": {"access_token": "AT", "refresh_token": "RT", "expires_in": 28800}}
        with self.fake_http(responses):
            url = self.oauth.begin("http://127.0.0.1:8020/api/oauth/notion/callback")
            self.assertTrue(url.startswith("https://mcp.notion.com/authorize?"))
            for fragment in ("code_challenge_method=S256", "client_id=cid", "response_type=code"):
                self.assertIn(fragment, url)
            state = json.loads(self.oauth.auth_file.read_text())["pending"]["state"]
            with self.assertRaises(NotionAuthError):
                self.oauth.complete("code", "estado-errado")
            self.oauth.complete("code123", state)
            self.assertTrue(self.oauth.is_connected())
            self.assertEqual(self.oauth.access_token(), "AT")
        token_call = next(c for c in self.calls if c[0].endswith("/token"))
        self.assertEqual(token_call[2]["grant_type"], "authorization_code")
        self.assertIn("code_verifier", token_call[2])
        self.assertNotIn("pending", json.loads(self.oauth.auth_file.read_text()))

    def seed(self, expires_at, refresh="RT"):
        self.oauth.auth_file.write_text(json.dumps({
            "server_url": "https://mcp.notion.com/mcp", "oauth": self.META, "client": {"client_id": "cid"},
            "tokens": {"access_token": "OLD", "refresh_token": refresh, "expires_at": expires_at}}))

    def test_refresh_when_near_expiry_and_rotates_refresh_token(self):
        self.seed(int(time.time()) + 30)
        with self.fake_http({"/token": {"access_token": "NEW", "refresh_token": "RT2", "expires_in": 3600}}):
            self.assertEqual(self.oauth.access_token(), "NEW")
        saved = json.loads(self.oauth.auth_file.read_text())["tokens"]
        self.assertEqual((saved["access_token"], saved["refresh_token"]), ("NEW", "RT2"))

    def test_valid_token_does_not_hit_network(self):
        self.seed(int(time.time()) + 7200)
        with self.fake_http({}):
            self.assertEqual(self.oauth.access_token(), "OLD")
        self.assertEqual(self.calls, [])

    def test_expired_without_refresh_or_failed_refresh_requires_reconnect(self):
        self.seed(int(time.time()) - 10, refresh="")
        self.assertFalse(self.oauth.is_connected())
        with self.assertRaises(NotAuthorized):
            self.oauth.access_token()
        self.seed(int(time.time()) - 10)

        def failing(url, **kw):
            raise NotionAuthError("HTTP 400 invalid_grant")
        with mock.patch.object(notion_oauth, "_http", failing), self.assertRaises(NotAuthorized):
            self.oauth.access_token()

    def test_not_connected_and_server_change(self):
        self.assertFalse(self.oauth.is_connected())
        with self.assertRaises(NotAuthorized):
            self.oauth.access_token()
        self.seed(int(time.time()) + 7200)
        self.assertFalse(NotionOAuth(self.oauth.auth_file, "https://outro.exemplo/mcp").is_connected())


if __name__ == "__main__":
    unittest.main()
