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


def main():
    stored = {}
    device_polls = []
    drop_response = [True]

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
            with Readlint("rlk_smoke", base_url=api) as client:
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
        finally:
            server.shutdown()
            thread.join()
    print(
        "Installed SDK and CLI passed: device login, owner-only storage, key precedence, lost-answer retry with one effect, CRUD, JSON errors and logout."
    )


if __name__ == "__main__":
    main()
