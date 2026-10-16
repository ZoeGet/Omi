import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BLOCKED_PARTS = {"tmp", ".pio", ".venv", "venv", "env", "__pycache__", "build", "dist", "release"}
BLOCKED_SUFFIXES = {".exe", ".zip", ".bin", ".elf", ".map", ".log", ".pem", ".key", ".p12", ".pfx", ".pyc",
                    ".dll", ".sqlite3", ".sqlite3-journal", ".sqlite3-wal", ".sqlite3-shm"}
BLOCKED_NAMES = {"AGENTS.md", "auth.json", "hooks.json", "snapshot.json", "events.jsonl", "host-binding-config.json", "compile_commands.json"}
PATTERNS = {
    "API token": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    "private key payload": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{30,}"),
    "URL credential": re.compile(rb"https?://[^\s/:@]+:[^\s/@]+@"),
    "device serial": re.compile(rb"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b"),
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def findings(name, data):
    path = PurePosixPath(name)
    if (set(path.parts) & BLOCKED_PARTS or path.suffix.lower() in BLOCKED_SUFFIXES
            or path.name in BLOCKED_NAMES or path.name.startswith((".env", "codex-clipboard-", "host-bindings"))
            or (path.name.startswith("sdkconfig") and path.name != "sdkconfig.defaults")
            or (re.search(r"credential|secret|password", path.name, re.I) and path.suffix.lower() not in {".py", ".h", ".cpp"})):
        yield "local-only path"
    for category, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            yield f"{category} at line {data[:match.start()].count(bytes([10])) + 1}"


def main():
    parser = argparse.ArgumentParser(description="Check staged publication paths without printing sensitive values")
    parser.add_argument("--worktree", action="store_true", help="Audit modified and non-ignored untracked candidates")
    args = parser.parse_args()
    if args.worktree:
        names = git("diff", "--name-only", "-z") + git("ls-files", "--others", "--exclude-standard", "-z")
    else:
        names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    paths = sorted(set(name.decode("utf-8") for name in names.split(bytes([0])) if name))
    issues = []
    for name in paths:
        data = (ROOT / name).read_bytes() if args.worktree else git("show", ":" + name)
        issues.extend(f"{name}: {issue}" for issue in findings(name, data))
    print(f"Audited {len(paths)} {'worktree candidates' if args.worktree else 'staged files'}")
    print("\n".join(issues) if issues else "PASS publication path and common-secret checks")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
