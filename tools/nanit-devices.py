#!/usr/bin/env python3
"""Dump raw /babies API response to discover all device UIDs.

Reads session from .nanit-session (created by nanit-login.py).
Prints the full JSON so we can find sound machine UIDs and other
device identifiers beyond just camera_uid.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_FILE = REPO_ROOT / ".nanit-session"
sys.path.insert(0, str(REPO_ROOT / "packages" / "aionanit"))

from aionanit.rest import NANIT_API_HEADERS  # noqa: E402

NANIT_API_BASE = "https://api.nanit.com"


async def _get(session, token, url):
    async with session.get(
        url,
        headers={**NANIT_API_HEADERS, "Authorization": token},
    ) as resp:
        text = await resp.text()
        print(f"\n=== GET {url} ===")
        print(f"Status: {resp.status}")
        try:
            print(json.dumps(json.loads(text), indent=2))
        except Exception:
            print(text)
        return resp.status, text


async def async_main() -> int:
    if not SESSION_FILE.exists():
        print("No session found. Run: just login", file=sys.stderr)
        return 1

    data = json.loads(SESSION_FILE.read_text())
    token = data["access_token"]
    baby_uid = data.get("baby_uid", "")
    speaker_uid = data.get("speaker_uid", "")

    async with aiohttp.ClientSession() as session:
        # Dump full /babies response
        status, _ = await _get(session, token, f"{NANIT_API_BASE}/babies")
        if status == 401:
            print("Token expired. Run: just login", file=sys.stderr)
            return 1

        if not speaker_uid:
            print("\nNo speaker_uid in session. Run: just login", file=sys.stderr)
            return 1

        # Probe speaker REST endpoints for state / control
        for path in (
            f"/speakers/{speaker_uid}",
            f"/speakers/{speaker_uid}/status",
            f"/speakers/{speaker_uid}/state",
            f"/speakers/{speaker_uid}/sounds",
            f"/speakers/{speaker_uid}/playback",
            f"/speakers/{speaker_uid}/nature_sounds",
            f"/babies/{baby_uid}/nature_sounds",
            f"/babies/{baby_uid}/sounds",
            f"/babies/{baby_uid}/monitoring",
        ):
            await _get(session, token, NANIT_API_BASE + path)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
