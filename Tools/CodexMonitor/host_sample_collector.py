import importlib.util
import json
from pathlib import Path
import sys


def main():
    directory = Path(__file__).resolve().parent
    base = directory / "lifecycle_collector.py"
    if not base.exists():
        base = directory / "collector.py"
    if base.resolve() == Path(__file__).resolve():
        return 0
    spec = importlib.util.spec_from_file_location("lifecycle_collector", base)
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)
    original_collect = lifecycle.collect

    def collect_and_sample(root, payload):
        original_collect(root, payload)
        try:
            config = directory / "host-observer.json"
            if config.exists():
                from host_observer import record
                record(payload, json.loads(config.read_text(encoding="utf-8-sig")))
        except Exception:
            pass

    lifecycle.collect = collect_and_sample
    return lifecycle.main()


if __name__ == "__main__":
    sys.exit(main())
