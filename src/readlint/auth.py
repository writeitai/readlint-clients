"""Device login and owner-only storage adapted from mountable's CLI."""

import json
import os
import platform
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from readlint.client import Readlint, ReadlintError


def credentials_path() -> Path:
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / "readlint" / "credentials.json"


def save_credentials(client: Readlint, token: str, expires_in: int) -> None:
    if os.name != "posix":
        raise ReadlintError(
            "unsupported_platform",
            "Saved login requires POSIX file permissions. Use READLINT_API_KEY on this platform.",
        )
    path = credentials_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".credentials-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(
                {
                    "api": client.base_url,
                    "access_token": token,
                    "expires_at": time.time() + expires_in,
                },
                stream,
            )
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_credentials(api: str) -> str:
    try:
        # O_NOFOLLOW prevents reading a substituted symlink on POSIX.
        fd = os.open(credentials_path(), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (
                os.name == "posix"
                and (info.st_mode & 0o077 or info.st_uid != os.getuid())
            ):
                raise ValueError("unsafe permissions")
            data = json.load(stream)
        if (
            data["api"] != api
            or data["expires_at"] <= time.time()
            or not isinstance(data["access_token"], str)
        ):
            raise ValueError("expired or different origin")
        return data["access_token"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ReadlintError(
            "authentication_required",
            "No usable saved login. Run `readlint login` or set READLINT_API_KEY.",
        ) from None


def login(client: Readlint, show_code: Callable[[str, str], None]) -> None:
    if os.name != "posix":
        raise ReadlintError(
            "unsupported_platform",
            "Saved login requires POSIX file permissions. Use READLINT_API_KEY on this platform.",
        )
    code = client._request(
        "POST",
        "/auth/device/code",
        authenticated=False,
        data={
            "client_id": "readlint-cli",
            "hostname": platform.node()[:200],
            "os": sys.platform,
        },
    )
    try:
        interval = max(1, int(code.get("interval", 5)))
        deadline = time.monotonic() + int(code["expires_in"])
        device_code = code["device_code"]
        uri = code["verification_uri_complete"]
        user_code = code["user_code"]
        if not all(isinstance(v, str) for v in (device_code, uri, user_code)):
            raise ValueError("invalid device response")
    except (KeyError, TypeError, ValueError):
        raise ReadlintError(
            "invalid_response",
            "Invalid device response. Update readlint or retry login later.",
        ) from None
    show_code(uri, user_code)
    while time.monotonic() < deadline:
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
        if time.monotonic() >= deadline:
            break
        try:
            token = client._request(
                "POST",
                "/auth/device/token",
                authenticated=False,
                data={
                    "client_id": "readlint-cli",
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                },
            )
        except ReadlintError as exc:
            if exc.code == "authorization_pending":
                continue
            if exc.code == "slow_down":
                interval += 5
                continue
            if exc.code == "network_error":
                interval *= 2
                continue
            raise
        try:
            if (
                not isinstance(token["access_token"], str)
                or not token["access_token"]
                or int(token["expires_in"]) <= 0
                or token["token_type"].lower() != "bearer"
            ):
                raise ValueError("invalid token response")
            save_credentials(client, token["access_token"], int(token["expires_in"]))
        except (KeyError, TypeError, ValueError):
            raise ReadlintError(
                "invalid_response",
                "Invalid token response. Run `readlint login` again.",
            ) from None
        return
    raise ReadlintError(
        "expired_token", "The code expired; run `readlint login` again."
    )
