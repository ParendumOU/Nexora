#!/usr/bin/env python3
"""Relay a CLI command-hook payload to the Nexora ingest endpoint.

Used by CLIs that only support `command` hooks (Gemini, Codex). Reads the hook
JSON from stdin, attaches the run token + event name, and POSTs to the backend.
Fire-and-forget: any failure exits 0 so the CLI is never blocked.

Usage: cli_hook_relay.py <ingest_url> <token> <event>
"""
import json
import sys
import urllib.request


def main() -> int:
    if len(sys.argv) < 4:
        return 0
    ingest_url, token, event = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    payload.setdefault("hook_event_name", event)
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ingest_url,
        data=body,
        headers={"Content-Type": "application/json", "X-Nexora-Run-Token": token},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=6)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
