import json
import os

import httpx
import pytest

from readlint import Readlint, ReadlintError
from readlint.auth import load_credentials, login, save_credentials


@pytest.fixture
def credentials(monkeypatch, tmp_path):
    path = tmp_path / "config" / "credentials.json"
    monkeypatch.setattr("readlint.auth.credentials_path", lambda: path)
    return path


def test_atomic_owner_only_and_origin_bound(credentials):
    with Readlint(base_url="https://example.com") as client:
        save_credentials(client, "rlk_test", 3600)
        assert credentials.stat().st_mode & 0o777 == 0o600
        assert load_credentials(client.base_url) == "rlk_test"
        credentials.chmod(0o644)
        save_credentials(client, "rlk_new", 3600)
        assert credentials.stat().st_mode & 0o777 == 0o600
        assert load_credentials(client.base_url) == "rlk_new"
        with pytest.raises(ReadlintError):
            load_credentials("https://other.invalid")
        save_credentials(client, "rlk_old", -1)
        with pytest.raises(ReadlintError):
            load_credentials(client.base_url)


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes")
def test_refuse_insecure_credentials(credentials):
    credentials.parent.mkdir()
    credentials.write_text(
        json.dumps(
            {
                "access_token": "secret",
                "api": "https://readlint.com",
                "expires_at": 99999999999,
            }
        )
    )
    credentials.chmod(0o644)
    with pytest.raises(ReadlintError):
        load_credentials("https://readlint.com")
    target = credentials.with_suffix(".target")
    credentials.rename(target)
    credentials.symlink_to(target)
    with pytest.raises(ReadlintError):
        load_credentials("https://readlint.com")


@pytest.mark.parametrize(
    "outcome", ["success", "access_denied", "expired_token", "invalid_grant"]
)
def test_device_flow_pending_slowdown_and_terminal(credentials, monkeypatch, outcome):
    clock = [0.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr("readlint.auth.time.sleep", sleep)
    monkeypatch.setattr("readlint.auth.time.monotonic", lambda: clock[0])
    polls = []

    def serve(request):
        assert "authorization" not in request.headers
        from urllib.parse import parse_qs

        form = parse_qs(request.content.decode())
        assert form["client_id"] == ["readlint-cli"]
        if request.url.path.endswith("/code"):
            return httpx.Response(
                200,
                json={
                    "device_code": "device_secret",
                    "user_code": "BCDF-GHJK",
                    "verification_uri_complete": "https://readlint.com/app/device?user_code=BCDF-GHJK",
                    "expires_in": 100,
                    "interval": 5,
                },
            )
        assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:device_code"]
        assert form["device_code"] == ["device_secret"]
        polls.append(request)
        if len(polls) == 1:
            return httpx.Response(400, json={"error": "authorization_pending"})
        if len(polls) == 2:
            return httpx.Response(400, json={"error": "slow_down"})
        if len(polls) == 3:
            raise httpx.ConnectError("connection failed")
        if outcome != "success":
            return httpx.Response(400, json={"error": outcome})
        return httpx.Response(
            200,
            json={
                "access_token": "rlk_test",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    shown = []
    with Readlint(transport=httpx.MockTransport(serve)) as client:
        if outcome == "success":
            login(client, lambda uri, code: shown.append((uri, code)))
            assert load_credentials(client.base_url) == "rlk_test"
        else:
            with pytest.raises(ReadlintError) as found:
                login(client, lambda uri, code: shown.append((uri, code)))
            assert found.value.code == outcome
            assert not credentials.exists()
    assert waits == [5, 5, 10, 20]
    assert len(shown) == 1


def test_device_deadline_does_not_poll_after_expiry(credentials, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(
        "readlint.auth.time.sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    monkeypatch.setattr("readlint.auth.time.monotonic", lambda: clock[0])
    with (
        Readlint(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={
                        "device_code": "secret",
                        "user_code": "code",
                        "verification_uri_complete": "https://readlint.com/app/device",
                        "interval": 5,
                        "expires_in": 2,
                    },
                )
            )
        ) as client,
        pytest.raises(ReadlintError, match="expired"),
    ):
        login(client, lambda uri, code: None)
    assert not credentials.exists()


def test_login_refuses_unsupported_platform_before_network(monkeypatch):
    def unexpected_request(request):
        pytest.fail("unsupported login must not create a device request or key")

    with Readlint(transport=httpx.MockTransport(unexpected_request)) as client:
        with monkeypatch.context() as patch, pytest.raises(ReadlintError) as found:
            patch.setattr("readlint.auth.os.name", "nt")
            login(client, lambda uri, code: None)
        assert found.value.code == "unsupported_platform"
