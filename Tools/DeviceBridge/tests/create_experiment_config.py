import argparse
import configparser
from pathlib import Path


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Explicit positive integer required")
    return number


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a separate compile-only experiment configuration; never build or flash")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--max-json-bytes", type=positive, required=True)
    parser.add_argument("--rx-bytes-per-loop", type=positive, required=True)
    parser.add_argument("--max-json-depth", type=positive, required=True)
    parser.add_argument("--usb", action="store_true")
    parser.add_argument("--wireless-pairing", action="store_true")
    parser.add_argument("--wireless-control", action="store_true")
    parser.add_argument("--sof-reset-fix", action="store_true")
    parser.add_argument("--freshness-challenge", action="store_true")
    parser.add_argument("--monitor-lights", action="store_true")
    parser.add_argument("--monitor-green-off", action="store_true")
    parser.add_argument("--desktop-control", action="store_true")
    parser.add_argument("--max-sessions", type=positive)
    parser.add_argument("--lease-ms", type=positive)
    parser.add_argument("--tx-buffer-bytes", type=positive)
    parser.add_argument("--write-wait-ms", type=positive)
    parser.add_argument("--link-grace-ms", type=positive)
    args = parser.parse_args()
    usb_values = (args.max_sessions, args.lease_ms, args.tx_buffer_bytes, args.write_wait_ms)
    if args.usb and (not all(usb_values) or args.lease_ms > 0xFFFFFFFF or args.tx_buffer_bytes < args.max_json_bytes + 8):
        parser.error("USB requires explicit positive budgets, uint32 lease, and a whole-frame TX buffer")
    if not args.usb and any(value is not None for value in usb_values):
        parser.error("USB budgets require --usb")
    if args.sof_reset_fix and not args.usb:
        parser.error("The isolated SOF fix requires --usb")
    if args.link_grace_ms is not None and (not args.usb or args.link_grace_ms >= args.lease_ms):
        parser.error("Link grace requires --usb and must be shorter than the lease")
    if args.freshness_challenge and not args.usb:
        parser.error("Freshness challenge requires --usb")
    if args.monitor_lights and not (args.usb and args.freshness_challenge):
        parser.error("Monitor lights require --usb and --freshness-challenge")
    if args.desktop_control and not args.usb:
        parser.error("Desktop control requires --usb")
    if args.monitor_green_off and not args.monitor_lights:
        parser.error("Green/off policy requires --monitor-lights")
    firmware = Path(__file__).resolve().parents[3] / "Firmware"
    if args.wireless_control and not (args.wireless_pairing and args.usb and args.desktop_control and args.monitor_green_off):
        parser.error("Wireless control requires pairing and the existing USB desktop/monitor policy")
    output, build = args.output.resolve(), args.build_dir.resolve()
    stable = (firmware / ".pio/build").resolve()
    if not build.is_relative_to(firmware / ".pio") or stable.is_relative_to(build) or build.is_relative_to(stable):
        parser.error("Choose an isolated Firmware/.pio subdirectory outside the normal build directory")
    if output == firmware / "platformio.ini" or output.exists():
        parser.error("Choose a new configuration path; never overwrite the project configuration")
    config = configparser.ConfigParser(interpolation=None)
    config.read(firmware / "platformio.ini", encoding="utf-8")
    config["platformio"] = dict(build_dir=str(build))
    flags = config["env:esp32-s3-devkitc-1"]["build_flags"]
    flags += "\n-DOMIPET_PROTOCOL_EXPERIMENT=1"
    flags += "\n-DOMIPET_PROTOCOL_MAX_JSON_BYTES=" + str(args.max_json_bytes)
    flags += "\n-DOMIPET_PROTOCOL_RX_BYTES_PER_LOOP=" + str(args.rx_bytes_per_loop)
    flags += "\n-DOMIPET_PROTOCOL_MAX_JSON_DEPTH=" + str(args.max_json_depth)
    if args.usb:
        flags += "\n-DOMIPET_PROTOCOL_USB=1"
        flags += "\n-DOMIPET_PROTOCOL_MAX_SESSIONS=" + str(args.max_sessions)
        flags += "\n-DOMIPET_PROTOCOL_LEASE_MS=" + str(args.lease_ms)
        flags += "\n-DOMIPET_PROTOCOL_TX_BUFFER_BYTES=" + str(args.tx_buffer_bytes)
        flags += "\n-DOMIPET_PROTOCOL_WRITE_WAIT_MS=" + str(args.write_wait_ms)
        if args.link_grace_ms is not None:
            flags += "\n-DOMIPET_PROTOCOL_LINK_GRACE_MS=" + str(args.link_grace_ms)
        if args.freshness_challenge:
            flags += "\n-DOMIPET_PROTOCOL_FRESHNESS_CHALLENGE=1"
        if args.monitor_lights:
            flags += "\n-DOMIPET_MONITOR_LIGHTS=1"
        if args.monitor_green_off:
            flags += "\n-DOMIPET_MONITOR_GREEN_OFF=1"
        if args.desktop_control:
            flags += "\n-DOMIPET_DESKTOP_CONTROL=1"
    config["env:esp32-s3-devkitc-1"]["build_flags"] = flags
    if args.sof_reset_fix:
        config["env:esp32-s3-devkitc-1"]["board_build.cmake_extra_args"] = "-DOMIPET_USB_SOF_FIX=ON"
    if args.wireless_pairing:
        if output.is_relative_to(build):
            parser.error("Keep wireless configuration files outside the disposable build directory")
        settings = config["env:esp32-s3-devkitc-1"]
        settings["board_build.cmake_extra_args"] = settings.get("board_build.cmake_extra_args", "") + " -DOMIPET_WIFI_PAIRING=ON"
        sdkconfig = output.with_suffix(".sdkconfig")
        defaults = output.with_suffix(".defaults")
        if sdkconfig.exists() or defaults.exists():
            parser.error("Choose unused isolated configuration paths")
        sdkconfig.parent.mkdir(parents=True, exist_ok=True)
        defaults.write_text((firmware / "sdkconfig.defaults").read_text(encoding="utf-8") +
                            "\nCONFIG_HTTPD_WS_SUPPORT=y\nCONFIG_MBEDTLS_ECJPAKE_C=y\nCONFIG_MBEDTLS_HKDF_C=y\n", encoding="utf-8")
        settings["board_build.cmake_extra_args"] += ' -DSDKCONFIG_DEFAULTS="' + defaults.as_posix() + '"'
        settings["board_build.esp-idf.sdkconfig_path"] = sdkconfig.as_posix()
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.wireless_control:
        config["env:esp32-s3-devkitc-1"]["board_build.cmake_extra_args"] += " -DOMIPET_WIFI_CONTROL=ON"
    with output.open("x", encoding="utf-8") as stream:
        config.write(stream)
    print("Generated compile-only configuration: " + str(output))
