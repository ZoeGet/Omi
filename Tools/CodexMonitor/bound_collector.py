import importlib.util
import json
from pathlib import Path
import sys
import time


def main():
    directory = Path(__file__).resolve().parent
    source = directory / "lifecycle_collector.py"
    spec = importlib.util.spec_from_file_location("lifecycle_collector", source)
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)
    original_collect = lifecycle.collect

    def collect_and_bind(root, payload):
        original_timestamp = lifecycle.timestamp
        stamped = []
        def capture_timestamp():
            observed_monotonic_ns = time.monotonic_ns()
            value = original_timestamp()
            stamped.append((value, observed_monotonic_ns))
            return value
        lifecycle.timestamp = capture_timestamp
        try:
            original_collect(root, payload)
        finally:
            lifecycle.timestamp = original_timestamp
        try:
            configuration = directory / "host-binding-config.json"
            if configuration.exists() and stamped:
                from host_binding_sidecar import update
                update(root, payload, json.loads(configuration.read_text(encoding="utf-8-sig")),
                       expected_updated_at=stamped[-1][0],
                       observed_monotonic_ns=stamped[-1][1],
                       lock=lifecycle.monitor_lock, save=lifecycle.atomic_json)
        except Exception:
            pass

    lifecycle.collect = collect_and_bind
    return lifecycle.main()


if __name__ == "__main__":
    sys.exit(main())
