import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Compile actual firmware parsers using the installed IDF cJSON source")
    parser.add_argument("--cjson-dir", type=Path, required=True)
    parser.add_argument("--wsl-distro")
    parser.add_argument("--hwcdc-source", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[3]
    (repository / "tmp").mkdir(exist_ok=True)
    includes = repository / "Firmware/include"
    native = Path(__file__).resolve().parent / "native"
    sys.path.insert(0, str(native.parents[1]))
    from protocol import Limits, envelope, serial_frame, token
    cjson = args.cjson_dir.resolve()
    if not (cjson / "cJSON.c").is_file():
        parser.error("Installed cJSON source directory required")
    if os.name == "nt" and not args.wsl_distro:
        parser.error("On Windows explicitly choose an existing WSL distribution")

    def path(value):
        value = str(Path(value).resolve())
        if os.name == "nt":
            return "/mnt/" + value[0].lower() + value[2:].replace("\\", "/")
        return value

    def run(command, *, source=None, success=True):
        prefix = ["wsl", "-d", args.wsl_distro, "--exec", "env", "LC_ALL=C"] if os.name == "nt" else []
        result = subprocess.run(prefix + command, input=source, text=True, encoding="utf-8",
                                capture_output=True, timeout=120)
        if (result.returncode == 0) != success:
            raise RuntimeError(result.stdout + result.stderr)
        return result

    with tempfile.TemporaryDirectory(prefix="native-protocol-", dir=repository / "tmp") as directory:
        output = Path(directory)
        fixture_flags = ["-DOMIPET_PROTOCOL_EXPERIMENT=1", "-DOMIPET_PROTOCOL_MAX_JSON_BYTES=4096",
                         "-DOMIPET_PROTOCOL_RX_BYTES_PER_LOOP=16", "-DOMIPET_PROTOCOL_MAX_JSON_DEPTH=8"]
        check = ["g++", "-std=c++11", "-I" + path(includes), "-fsyntax-only", "-x", "c++", "-"]
        run(check, source='#include "protocol_experiment_config.h"\nstatic_assert(OMIPET_PROTOCOL_EXPERIMENT == 0, "off");\n')
        run(check + ["-DOMIPET_PROTOCOL_EXPERIMENT=1"],
            source='#include "protocol_experiment_config.h"\n', success=False)
        run(check + fixture_flags + ["-UOMIPET_PROTOCOL_RX_BYTES_PER_LOOP", "-DOMIPET_PROTOCOL_RX_BYTES_PER_LOOP=0"],
            source='#include "protocol_experiment_config.h"\n', success=False)
        usb_flags = fixture_flags + ["-DOMIPET_PROTOCOL_USB=1", "-DOMIPET_PROTOCOL_MAX_SESSIONS=16",
                                     "-DOMIPET_PROTOCOL_LEASE_MS=1000", "-DOMIPET_PROTOCOL_TX_BUFFER_BYTES=8192",
                                     "-DOMIPET_PROTOCOL_WRITE_WAIT_MS=1"]
        run(check + usb_flags, source='#include "protocol_experiment_config.h"\n')
        run(check + usb_flags + ["-DOMIPET_PROTOCOL_LINK_GRACE_MS=20"],
            source='#include "protocol_experiment_config.h"\n')
        for value in (-1, 1000):
            run(check + usb_flags + ["-DOMIPET_PROTOCOL_LINK_GRACE_MS=" + str(value)],
                source='#include "protocol_experiment_config.h"\n', success=False)
        run(check + ["-DOMIPET_PROTOCOL_LINK_GRACE_MS=20"],
            source='#include "protocol_experiment_config.h"\n', success=False)
        challenge_flags = usb_flags + ["-DOMIPET_PROTOCOL_FRESHNESS_CHALLENGE=1"]
        run(check + challenge_flags, source='#include "protocol_experiment_config.h"\n')
        run(check + challenge_flags + ["-DOMIPET_MONITOR_LIGHTS=1"],
            source='#include "protocol_experiment_config.h"\n')
        run(check + usb_flags + ["-DOMIPET_MONITOR_LIGHTS=1"],
            source='#include "protocol_experiment_config.h"\n', success=False)
        run(check + fixture_flags + ["-DOMIPET_PROTOCOL_FRESHNESS_CHALLENGE=1"],
            source='#include "protocol_experiment_config.h"\n', success=False)
        run(check + fixture_flags + ["-DOMIPET_PROTOCOL_USB=1"],
            source='#include "protocol_experiment_config.h"\n', success=False)
        run(check + usb_flags + ["-UOMIPET_PROTOCOL_TX_BUFFER_BYTES", "-DOMIPET_PROTOCOL_TX_BUFFER_BYTES=256"],
            source='#include "protocol_experiment_config.h"\n', success=False)
        run(check + usb_flags + ["-UOMIPET_PROTOCOL_WRITE_WAIT_MS", "-DOMIPET_PROTOCOL_WRITE_WAIT_MS=0"],
            source='#include "protocol_experiment_config.h"\n', success=False)
        sanitizer = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g"]
        main_source = (repository / "Firmware/src/main.cpp").read_text(encoding="utf-8")
        loop_start = main_source.index("while (", main_source.index("void updateCommandAudioFrames()"))
        loop_end = main_source.index(" {", loop_start)
        (output / "audio_budget_loop.h").write_text(main_source[loop_start:loop_end] + "\n", encoding="utf-8")
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer,
             "-I" + path(output), path(native / "audio_budget_native.cpp"), "-o", path(output / "audio_budget_native")])
        audio_result = run([path(output / "audio_budget_native")])
        run(["gcc", "-std=c99", *sanitizer, "-I" + path(cjson), "-c", path(cjson / "cJSON.c"),
             "-o", path(output / "cjson.o")])
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer, *fixture_flags,
             "-I" + path(native), "-I" + path(includes), "-I" + path(cjson),
             path(native / "protocol_native.cpp"), path(repository / "Firmware/src/device_protocol_envelope.cpp"),
             path(repository / "Firmware/src/device_protocol_experiment.cpp"), path(output / "cjson.o"),
             "-o", path(output / "protocol_native")])
        fixture = output / "host-frames.txt"
        snapshot = dict(revision=1, validForMs=0, sourceLiveness="unverified", overallStatus="unknown", sessions=[
            dict(id="s1", observed="working", display="unknown", host="unverified")])
        fixture.write_bytes(b"".join(serial_frame(envelope(token(), token(), token(), index, kind, body), Limits(4096, 16))
                            for index, (kind, body) in enumerate((("hello", {"protocol": 1}), ("heartbeat", {}),
                                                                ("snapshot", snapshot), ("release", {})), 1)))
        result = run([path(output / "protocol_native"), path(fixture)])
        from session_vectors import write_vectors
        session_fixture = output / "session-vectors.jsonl"
        write_vectors(session_fixture)
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer, *fixture_flags,
             "-I" + path(includes), "-I" + path(cjson), path(native / "session_native.cpp"),
             path(repository / "Firmware/src/device_protocol_envelope.cpp"),
             path(repository / "Firmware/src/device_protocol_session.cpp"), path(output / "cjson.o"),
             "-o", path(output / "session_native")])
        session_result = run([path(output / "session_native"), path(session_fixture)])
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer, *fixture_flags,
             "-I" + path(includes), "-I" + path(cjson), path(native / "transport_native.cpp"),
             path(repository / "Firmware/src/device_protocol_envelope.cpp"),
             path(repository / "Firmware/src/device_protocol_session.cpp"), path(output / "cjson.o"),
             "-o", path(output / "transport_native")])
        transport_result = run([path(output / "transport_native")])
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer, *challenge_flags,
             "-I" + path(includes), "-I" + path(cjson), path(native / "challenge_native.cpp"),
             path(repository / "Firmware/src/device_protocol_envelope.cpp"),
             path(repository / "Firmware/src/device_protocol_session.cpp"), path(output / "cjson.o"),
             "-o", path(output / "challenge_native")])
        challenge_result = run([path(output / "challenge_native")])
        desktop_flags = challenge_flags + ["-DOMIPET_DESKTOP_CONTROL=1"]
        run(check + desktop_flags, source='#include "protocol_experiment_config.h"\n')
        run(check + fixture_flags + ["-DOMIPET_DESKTOP_CONTROL=1"],
            source='#include "protocol_experiment_config.h"\n', success=False)
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer, *desktop_flags,
             "-I" + path(includes), "-I" + path(cjson), path(native / "desktop_control_native.cpp"),
             path(repository / "Firmware/src/device_protocol_envelope.cpp"),
             path(repository / "Firmware/src/device_protocol_session.cpp"), path(output / "cjson.o"),
             "-o", path(output / "desktop_control_native")])
        desktop_result = run([path(output / "desktop_control_native")])
        monitor_policy_flags = desktop_flags + ["-DOMIPET_MONITOR_LIGHTS=1", "-DOMIPET_MONITOR_GREEN_OFF=1"]
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer, *monitor_policy_flags,
             "-I" + path(native), "-I" + path(native / "mock_idf"), "-I" + path(includes), "-I" + path(cjson),
             path(native / "monitor_profiles_native.cpp"), path(repository / "Firmware/src/monitor_light_profiles.cpp"),
             path(repository / "Firmware/src/device_protocol_envelope.cpp"),
             path(repository / "Firmware/src/device_protocol_session.cpp"), path(output / "cjson.o"),
             "-o", path(output / "monitor_profiles_native")])
        profiles_result = run([path(output / "monitor_profiles_native")])
        run(check + monitor_policy_flags, source='#include "protocol_experiment_config.h"\n')
        run(check + desktop_flags + ["-DOMIPET_MONITOR_GREEN_OFF=1"], source='#include "protocol_experiment_config.h"\n', success=False)
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer, *monitor_policy_flags,
             "-I" + path(includes), "-I" + path(cjson), path(native / "monitor_policy_native.cpp"),
             path(repository / "Firmware/src/device_protocol_envelope.cpp"),
             path(repository / "Firmware/src/device_protocol_session.cpp"), path(output / "cjson.o"),
             "-o", path(output / "monitor_policy_native")])
        monitor_policy_result = run([path(output / "monitor_policy_native")])
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer,
             "-I" + path(includes), path(native / "led_arbiter_native.cpp"),
             "-o", path(output / "led_arbiter_native")])
        arbiter_result = run([path(output / "led_arbiter_native")])
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer,
             "-I" + path(native), "-I" + path(includes), path(native / "led_effect_native.cpp"),
             path(repository / "Firmware/src/led_controller.cpp"),
             "-o", path(output / "led_effect_native")])
        effect_result = run([path(output / "led_effect_native")])
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer,
             "-I" + path(includes), path(native / "pairing_window_native.cpp"),
             "-o", path(output / "pairing_window_native")])
        pairing_result = run([path(output / "pairing_window_native")])
        run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer,
             "-I" + path(includes), path(native / "monitor_transport_native.cpp"),
             "-o", path(output / "monitor_transport_native")])
        monitor_transport_result = run([path(output / "monitor_transport_native")])
        sof_tests = []
        if args.hwcdc_source:
            sys.path.insert(0, str(repository / "Firmware/scripts"))
            from usb_sof_fix import patch_source, tick_function
            original = args.hwcdc_source.read_bytes()
            patched = patch_source(original)
            prefix = """
#define IRAM_ATTR
struct { struct { uint32_t sof_int_raw; } int_raw; } USB_SERIAL_JTAG;
static volatile bool s_usb_serial_jtag_conn_status = true;
static volatile uint32_t remaining_allowed_no_sof_ticks = 5;
const uint32_t ALLOWED_NO_SOF_TICKS = 5;
const uint32_t USB_SERIAL_JTAG_INTR_SOF = 1;
void usb_serial_jtag_ll_clr_intsts_mask(uint32_t) {}
"""
            suffix = """
void reset() { s_usb_serial_jtag_conn_status = true; remaining_allowed_no_sof_ticks = ALLOWED_NO_SOF_TICKS; }
void tick(bool sof) { USB_SERIAL_JTAG.int_raw.sof_int_raw = sof ? 1 : 0; usb_serial_jtag_sof_tick_hook(); }
"""
            for name, data in (("original", original), ("fixed", patched)):
                (output / ("sof_" + name + ".h")).write_text(prefix + tick_function(data.decode("utf-8")) + suffix, encoding="utf-8")
            run(["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror", *sanitizer,
                 "-I" + path(output), path(native / "sof_native.cpp"), "-o", path(output / "sof_native")])
            sof_result = run([path(output / "sof_native")])
            print(sof_result.stdout, end="")
            sof_tests = [line[5:] for line in sof_result.stdout.splitlines() if line.startswith("PASS ")]
        print("PASS default_disabled\nPASS missing_budget_rejected\nPASS zero_budget_rejected")
        print("PASS usb_explicit_config\nPASS usb_missing_budgets\nPASS usb_small_buffer_rejected\nPASS usb_zero_write_timeout_rejected")
        print(result.stdout, end="")
        print(session_result.stdout, end="")
        print(transport_result.stdout, end="")
        print(challenge_result.stdout, end="")
        print(desktop_result.stdout, end="")
        print(profiles_result.stdout, end="")
        print(monitor_policy_result.stdout, end="")
        print(arbiter_result.stdout, end="")
        print(effect_result.stdout, end="")
        print(audio_result.stdout, end="")
        print(pairing_result.stdout, end="")
        print(monitor_transport_result.stdout, end="")
        report = dict(result="pass", configChecks=19,
                      nativeTests=[line[5:] for line in result.stdout.splitlines() if line.startswith("PASS ")],
                      sessionTests=[line[5:] for line in session_result.stdout.splitlines() if line.startswith("PASS ")],
                      transportTests=[line[5:] for line in transport_result.stdout.splitlines() if line.startswith("PASS ")],
                      challengeTests=[line[5:] for line in challenge_result.stdout.splitlines() if line.startswith("PASS ")],
                      desktopTests=[line[5:] for line in desktop_result.stdout.splitlines() if line.startswith("PASS ")],
                      monitorProfileTests=[line[5:] for line in profiles_result.stdout.splitlines() if line.startswith("PASS ")],
                      monitorPolicyTests=[line[5:] for line in monitor_policy_result.stdout.splitlines() if line.startswith("PASS ")],
                      arbiterTests=[line[5:] for line in arbiter_result.stdout.splitlines() if line.startswith("PASS ")],
                      effectTests=[line[5:] for line in effect_result.stdout.splitlines() if line.startswith("PASS ")],
                      audioBudgetTests=[line[5:] for line in audio_result.stdout.splitlines() if line.startswith("PASS ")],
                      pairingWindowTests=[line[5:] for line in pairing_result.stdout.splitlines() if line.startswith("PASS ")],
                      monitorTransportTests=[line[5:] for line in monitor_transport_result.stdout.splitlines() if line.startswith("PASS ")],
                      sofTests=sof_tests,
                      sanitizers=["address", "undefined"],
                      testOnlyBudgets=dict(maxJsonBytes=4096, rxBytesPerLoop=16, maxJsonDepth=8),
                      firmwareFlashed=False)
        if args.report:
            args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
