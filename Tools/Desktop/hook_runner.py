import json
import os
from pathlib import Path
import sys

import collector
from bound_collector import run
from make_hooks import EVENTS


def main():
    configuration = Path(sys.executable).parent / "host-binding-config.json"
    settings = json.loads(configuration.read_text(encoding="utf-8"))
    os.environ["OMIPET_CODEX_MONITOR_DIR"] = settings["root"]
    original = collector.collect
    applied = []
    def collect(root, payload):
        original(root, payload)
        session = str(payload.get("session_id") or "")
        if session.strip() and payload.get("hook_event_name") in EVENTS:
            applied.append(session)
    collector.collect = collect
    result = run(collector, configuration)
    root = Path(settings["root"])
    if applied:
        collector.atomic_json(root / "hook-receipt.json", dict(
            installationId=settings["installationId"], sessionId=applied[-1], receivedAtUtc=collector.timestamp()))
    return result
