import argparse
import json
from pathlib import Path
import subprocess
import sys


EVENTS = (
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PermissionRequest", "Stop", "Interrupt", "SessionEnd",
)


def configuration(python, collector):
    command = subprocess.list2cmdline([str(python), str(collector)])
    return {
        "description": "OmiPet local lifecycle metadata monitor",
        "hooks": {
            event: [{"hooks": [{
                "type": "command", "command": command, "commandWindows": command,
                "timeout": 3, "async": event not in ("SessionStart", "Stop", "SessionEnd"),
            }]}]
            for event in EVENTS
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print a hook configuration for review; never modify user settings")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--collector", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(configuration(args.python.resolve(), args.collector.resolve()), indent=2))
