import argparse
import hashlib
import json
from pathlib import Path


EXPECTED_SHA256 = "d0a8ca606c2729c8522a041113285dbf27033c22a5a6af8649a7305ffe84c449"
OLD_BLOCK = """  if (s_usb_serial_jtag_conn_status != sof_received) {
    if (!sof_received) {
      if (remaining_allowed_no_sof_ticks > 0) {
        remaining_allowed_no_sof_ticks--;
      } else {
        s_usb_serial_jtag_conn_status = false;
      }
    } else {
      s_usb_serial_jtag_conn_status = true;
      remaining_allowed_no_sof_ticks = ALLOWED_NO_SOF_TICKS;
    }
  }"""
NEW_BLOCK = """  if (!sof_received) {
    if (remaining_allowed_no_sof_ticks > 0) {
      remaining_allowed_no_sof_ticks--;
    } else {
      s_usb_serial_jtag_conn_status = false;
    }
  } else {
    //  每次观测到 SOF 都重置原有连续缺失预算 / Reset the existing consecutive-miss budget on every observed SOF
    s_usb_serial_jtag_conn_status = true;
    remaining_allowed_no_sof_ticks = ALLOWED_NO_SOF_TICKS;
  }"""


def patch_source(raw):
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Unverified HWCDC source; re-audit before enabling the isolated SOF fix")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if text.count(OLD_BLOCK) != 1:
        raise ValueError("Expected exactly one audited SOF detection block")
    return text.replace(OLD_BLOCK, NEW_BLOCK).encode("utf-8")


def tick_function(text):
    start = text.index("static void IRAM_ATTR usb_serial_jtag_sof_tick_hook(void)")
    end = text.index("// runs on Core 0", start)
    return text[start:end]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate an isolated, audited HWCDC source copy; never edit the installed SDK")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == args.output.resolve():
        parser.error("Output must differ from the installed SDK source")
    patched = patch_source(args.source.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists() or args.output.read_bytes() != patched:
        args.output.write_bytes(patched)
    print(json.dumps(dict(usbSofFix="consecutive-misses", originalSha256=EXPECTED_SHA256,
                         patchedSha256=hashlib.sha256(patched).hexdigest(), sdkThresholdUnchanged=True)))
