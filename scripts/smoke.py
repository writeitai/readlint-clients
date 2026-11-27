"""Exercise the installed wheel through the SDK and non-TTY CLI over real HTTP.

The fake service implements one-time device exchange and idempotent evaluation
storage. No private source, provider, secrets, or paid calls are needed.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from readlint import Readlint, ReadlintError

EVALUATION_ID = "64dfbf5a-2016-41a0-ad7f-b6808929b5ae"
RESULT = {
    "id": EVALUATION_ID,
    "title": "Example",
    "status": "complete",
    "created_at": "2026-11-26T00:00:00Z",
    "expires_at": "2026-12-26T00:00:00Z",
    "error_code": None,
    "report": {
        "title": "Example",
        "description": "",
        "article_checks": [],
        "prose_blocks": [],
        "banned_phrases": [],
        "omitted_computed_jsx": [],
        "model": "fake",
        "input_tokens": 12,
        "expires_at": "2026-12-26T00:00:00Z",
    },
}


async def mcp_workflow(env, *, key=None, flag=None, error=None):
    child_env = dict(env)
    if key:
        child_env["READLINT_API_KEY"] = key
    args = ["-m", "readlint.cli", "mcp"]
    if flag:
        args += ["--api-key", flag]
    params = StdioServerParameters(command=sys.executable, args=args, env=child_env)
    async with (
        stdio_client(params) as (reader, writer),
        ClientSession(reader, writer) as session,
    ):
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "readlint.com"
        tools = (await session.list_tools()).tools
        assert {t.name for t in tools} == {
            "evaluate_article",
            "get_evaluation",
            "list_evaluations",
            "delete_evaluation",
        }
        result = await session.call_tool("list_evaluations", {})
        assert result.structuredContent is not None
        assert "rlk_smoke" not in result.model_dump_json()
        if error:
            assert result.isError
            assert result.structuredContent["error"]["code"] == error
            return
        assert not result.isError
        bad = await session.call_tool("get_evaluation", {"evaluation_id": "not-a-uuid"})
        assert bad.structuredContent is not None
        assert bad.isError and bad.structuredContent["error"]["code"] == "invalid_input"
        arguments = {
            "article": "# MCP draft\n\nUseful prose.",
            "idempotency_key": "mcp-one",
        }
        evaluated = await session.call_tool("evaluate_article", arguments)
        assert evaluated.structuredContent is not None
        assert (
            not evaluated.isError and evaluated.structuredContent["id"] == EVALUATION_ID
        )
        replay = await session.call_tool("evaluate_article", arguments)
        assert (
            not replay.isError
            and replay.structuredContent == evaluated.structuredContent
        )
        read = await session.call_tool(
            "get_evaluation", {"evaluation_id": EVALUATION_ID}
        )
        assert read.structuredContent is not None
        assert not read.isError and read.structuredContent["status"] == "complete"
        deleted = await session.call_tool(
            "delete_evaluation", {"evaluation_id": EVALUATION_ID}
        )
        assert deleted.structuredContent is not None
        assert not deleted.isError and deleted.structuredContent["deleted"]
        missing = await session.call_tool(
            "get_evaluation", {"evaluation_id": EVALUATION_ID}
        )
        assert missing.structuredContent is not None
        assert (
            missing.isError
            and missing.structuredContent["error"]["code"] == "evaluation_not_found"
        )


def main():
    stored = {}
    device_polls = []
    drop_response = [True]
    transient_reads = [0]
    effects = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A002 - stdlib override
            pass

        def answer(self, status, body=None):
            data = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/auth/device/code":
                assert parse_qs(raw.decode())["client_id"] == ["readlint-cli"]
                return self.answer(
                    200,
                    {
                        "device_code": "device-secret",
                        "user_code": "BCDF-GHJK",
                        "verification_uri_complete": "https://readlint.com/app/device?user_code=BCDF-GHJK",
                        "interval": 1,
                        "expires_in": 30,
                    },
                )
            if self.path == "/auth/device/token":
                device_polls.append(parse_qs(raw.decode()))
                if len(device_polls) == 1:
                    return self.answer(400, {"error": "authorization_pending"})
                return self.answer(
                    200,
                    {
                        "access_token": "rlk_smoke",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    },
                )
            if not self.authorized():
                return
            key = self.headers["Idempotency-Key"]
            if key in stored and stored[key] != raw:
                return self.answer(409, {"detail": {"code": "idempotency_key_reused"}})
            if key not in stored:
                effects.append(key)
            stored[key] = raw
            if drop_response[0]:
                # The write succeeded but its answer was lost. Retrying must
                # use the same key and body and create only one record.
                drop_response[0] = False
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.answer(200, RESULT)

        def authorized(self):
            if self.headers.get("Authorization") != "Bearer rlk_smoke":
                self.answer(401, {"detail": {"code": "authentication_required"}})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            if urlsplit(self.path).path == "/v1/agent-permissions":
                return self.answer(
                    200,
                    {
                        "agents_can_start_trials": True,
                        "agents_can_confirm_paid_orders": False,
                        "agents_can_cancel_plans": True,
                    },
                )
            if transient_reads[0]:
                transient_reads[0] -= 1
                return self.answer(503, {"detail": {"code": "unavailable"}})
            if urlsplit(self.path).path == "/v1/evaluations":
                return self.answer(
                    200, {"items": [RESULT] if stored else [], "next_offset": None}
                )
            if not stored:
                return self.answer(404, {"detail": {"code": "evaluation_not_found"}})
            self.answer(200, RESULT)

        def do_DELETE(self):
            if self.authorized():
                stored.clear()
                self.answer(204)

    with (
        tempfile.TemporaryDirectory() as tmp,
        ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server,
    ):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        api = f"http://127.0.0.1:{server.server_port}"
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"READLINT_API_KEY", "READLINT_BASE_URL", "PYTHONPATH"}
        }
        env.update({"HOME": tmp, "XDG_CONFIG_HOME": tmp, "READLINT_BASE_URL": api})

        def cli(*args, key=None, success=True, stdin=None):
            child_env = dict(env)
            if key:
                child_env["READLINT_API_KEY"] = key
            run = subprocess.run(
                [sys.executable, "-m", "readlint.cli", "--json", *args],
                input=stdin,
                text=True,
                capture_output=True,
                check=False,
                env=child_env,
                timeout=20,
            )
            assert run.returncode == (0 if success else 1), run.stderr
            assert "rlk_smoke" not in run.stdout + run.stderr
            if success:
                return json.loads(run.stdout)
            assert run.stdout == ""
            return json.loads(run.stderr.splitlines()[-1])["error"]

        try:
            assert cli("version")["version"]
            assert cli("list", success=False)["code"] == "authentication_required"
            assert cli("login")["signed_in"]
            files = list(Path(tmp).rglob("credentials.json"))
            assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
            assert (
                cli(
                    "evaluate",
                    "-",
                    "--idempotency-key",
                    "smoke-one",
                    stdin="# Article\n\nUseful text.",
                )["report"]["input_tokens"]
                == 12
            )
            assert len(stored) == 1
            assert cli("list")["items"][0]["id"] == EVALUATION_ID
            transient_reads[0] = 1
            assert cli("list")["items"]
            assert (
                cli("get", EVALUATION_ID, key="wrong", success=False)["code"]
                == "authentication_required"
            )
            assert (
                cli("--api-key", "rlk_smoke", "get", EVALUATION_ID, key="wrong")["id"]
                == EVALUATION_ID
            )
            assert (
                cli(
                    "evaluate",
                    "-",
                    "--idempotency-key",
                    "smoke-one",
                    stdin="different",
                    success=False,
                )["code"]
                == "idempotency_key_reused"
            )
            assert (
                cli("agent-permissions", "get")["agents_can_confirm_paid_orders"]
                is False
            )
            with Readlint("rlk_smoke", base_url=api) as client:
                assert (
                    client.get_agent_permissions()["agents_can_confirm_paid_orders"]
                    is False
                )
                assert client.get_evaluation(EVALUATION_ID)["status"] == "complete"
                assert (
                    client.evaluate("SDK text", idempotency_key="sdk-one")["report"]
                    is not None
                )
                assert len(client.list_evaluations()["items"]) == 1
                client.delete_evaluation(EVALUATION_ID)
                try:
                    client.get_evaluation(EVALUATION_ID)
                except ReadlintError as error:
                    assert error.code == "evaluation_not_found"
                else:
                    raise AssertionError("missing expected error")
            assert cli("logout")["signed_in"] is False
            assert not files[0].exists()
            assert cli("list", key="rlk_smoke")["next_offset"] is None
            assert cli("delete", EVALUATION_ID, key="rlk_smoke")["deleted"]
            anyio.run(lambda: mcp_workflow(env, error="authentication_required"))
            assert cli("login")["signed_in"]
            drop_response[0] = True
            transient_reads[0] = 1
            anyio.run(lambda: mcp_workflow(env))  # saved device login
            assert effects.count("mcp-one") == 1
            anyio.run(
                lambda: mcp_workflow(env, key="wrong", error="authentication_required")
            )
            anyio.run(lambda: mcp_workflow(env, key="wrong", flag="rlk_smoke"))
            assert cli("logout")["signed_in"] is False
            anyio.run(lambda: mcp_workflow(env, key="rlk_smoke"))
            transient_reads[0] = 3
            anyio.run(lambda: mcp_workflow(env, key="rlk_smoke", error="api_error"))
        finally:
            server.shutdown()
            thread.join()
    print(
        "Installed SDK, CLI and MCP passed: device login, owner-only storage, saved/env/flag credentials, lost-answer retry with one effect, CRUD, sanitized errors, transient recovery and logout."
    )


if __name__ == "__main__":
    main()
