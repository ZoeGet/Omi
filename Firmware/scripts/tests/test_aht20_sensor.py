import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
STUB = r"""
#pragma once
#include <cstdint>
#include <cstddef>
#include <vector>
static uint32_t tick = 0;
static unsigned delays = 0;
uint32_t millis() { return tick; }
void delay(uint32_t ms) { tick += ms; ++delays; }
template<class T> T constrain(T value, T low, T high) { return value < low ? low : value > high ? high : value; }
struct TwoWire {
  bool online = true, badCrc = false, shortRead = false, failWrite = false, failStatus = false;
  uint8_t status = 8;
  unsigned measurements = 0, resets = 0, statusReads = 0;
  std::vector<uint8_t> bytes;
  size_t cursor = 0;
  void begin(uint8_t, uint8_t) {}
  void setClock(uint32_t) {}
  void beginTransmission(uint8_t) {}
  int endTransmission(bool) { return online && !failWrite ? 0 : 2; }
  size_t write(const uint8_t* data, size_t size) {
    if (online && !failWrite) {
      if (data[0] == 0xAC) ++measurements;
      if (data[0] == 0xBA) { ++resets; status = 8; }
      if (data[0] == 0xBE) status = 8;
    }
    return size;
  }
  size_t requestFrom(uint8_t, size_t size, bool) {
    bytes.clear(); cursor = 0;
    if (!online) return 0;
    if (size == 1) {
      ++statusReads;
      if (!failStatus) bytes.push_back(status);
    } else {
      bytes = {status, 0x80, 0, 0x06, 0, 0};
      uint8_t crc = 0xFF;
      for (uint8_t byte : bytes) {
        crc ^= byte;
        for (unsigned bit = 0; bit < 8; ++bit)
          crc = (crc & 0x80) ? static_cast<uint8_t>((crc << 1) ^ 0x31) : static_cast<uint8_t>(crc << 1);
      }
      if (!shortRead) bytes.push_back(badCrc ? crc ^ 1 : crc);
    }
    return bytes.size();
  }
  int available() { return static_cast<int>(bytes.size() - cursor); }
  int read() { return cursor < bytes.size() ? bytes[cursor++] : -1; }
} Wire;
"""
MAIN = r"""
#include <cassert>
#include <cmath>
#include <cstdio>
#include "aht20_sensor.cpp"
using namespace OmiPetSensor;

void resetBus() { Wire = TwoWire{}; tick = 0; delays = 0; }

int main() {
  resetBus();
  Aht20Sensor unconfigured;
  for (int i = 0; i < 5; ++i) { tick += 5000; assert(!unconfigured.readMeasurement()); }
  assert(Wire.resets == 0);
  std::puts("PASS no_recovery_without_bus");

  resetBus();
  Wire.online = false;
  Aht20Sensor recovering;
  assert(!recovering.begin());
  tick += 5000; assert(!recovering.readMeasurement());
  tick += 5000; assert(!recovering.readMeasurement());
  assert(!recovering.initialized());
  Wire.online = true;
  tick += 5000; assert(!recovering.readMeasurement());
  assert(Wire.resets == 1 && recovering.initialized());
  assert(recovering.consecutiveFailures() == 0 && recovering.measurement().stale);
  assert(recovering.readMeasurement());
  assert(std::fabs(recovering.measurement().temperatureC - 21.0F) < 0.001F);
  assert(std::fabs(recovering.measurement().humidityPercent - 59.0F) < 0.001F);
  assert(recovering.lastError() == Aht20Error::None);
  std::puts("PASS boot_failure_recovers_and_keeps_compensation");

  const auto previous = recovering.measurement();
  Wire.badCrc = true;
  tick += 5000;
  assert(!recovering.readMeasurement());
  assert(recovering.lastError() == Aht20Error::CrcMismatch);
  assert(recovering.measurement().valid && recovering.measurement().stale);
  assert(recovering.measurement().timestampMs == previous.timestampMs);
  assert(recovering.measurement().temperatureC == previous.temperatureC);
  Wire.badCrc = false;
  Wire.shortRead = true;
  assert(!recovering.readMeasurement() && recovering.lastError() == Aht20Error::ShortRead);
  Wire.shortRead = false;
  assert(recovering.readMeasurement());
  std::puts("PASS failed_frames_keep_last_valid_reading");

  resetBus();
  Aht20Sensor synchronous;
  assert(synchronous.begin());
  const uint32_t started = tick;
  assert(synchronous.readMeasurement());
  assert(tick - started == 90);
  Wire.status = 0x88;
  const uint32_t busyStarted = tick;
  assert(!synchronous.readMeasurement());
  assert(synchronous.lastError() == Aht20Error::BusyTimeout && tick - busyStarted == 210);
  std::puts("PASS synchronous_timing_preserved");

#if OMIPET_AHT20_ASYNC
  resetBus();
  Aht20Sensor staged;
  assert(staged.begin());
  tick = UINT32_MAX - 5;
  const unsigned beforeDelays = delays;
  assert(staged.startMeasurement());
  assert(!staged.startMeasurement() && !staged.readMeasurement());
  tick += 9; assert(!staged.updateMeasurement() && Wire.measurements == 0);
  tick += 1; assert(!staged.updateMeasurement() && Wire.measurements == 1);
  tick += 79; assert(!staged.updateMeasurement());
  Wire.status = 0x88;
  tick += 1; assert(!staged.updateMeasurement());
  const unsigned queries = Wire.statusReads;
  tick += 4; assert(!staged.updateMeasurement() && Wire.statusReads == queries);
  Wire.status = 8;
  tick += 1; assert(staged.updateMeasurement());
  assert(staged.measurement().valid && !staged.measurement().stale);
  assert(std::fabs(staged.measurement().temperatureC - 21.0F) < 0.001F);
  assert(delays == beforeDelays && !staged.updateMeasurement());
  std::puts("PASS staged_conversion_wraparound_polling_and_no_delays");

  auto last = staged.measurement();
  assert(staged.startMeasurement()); tick += 10; assert(!staged.updateMeasurement());
  Wire.status = 0x88;
  tick += 199; assert(!staged.updateMeasurement());
  tick += 1; assert(staged.updateMeasurement());
  assert(staged.lastError() == Aht20Error::BusyTimeout && staged.measurement().stale);
  assert(staged.measurement().timestampMs == last.timestampMs);
  assert(delays == beforeDelays);
  std::puts("PASS staged_timeout_keeps_previous_sample");

  Wire.status = 8; Wire.badCrc = true;
  assert(staged.startMeasurement()); tick += 10; assert(!staged.updateMeasurement());
  tick += 80; assert(staged.updateMeasurement());
  assert(staged.lastError() == Aht20Error::CrcMismatch);
  Wire.badCrc = false; Wire.failWrite = true;
  assert(staged.startMeasurement()); tick += 10; assert(staged.updateMeasurement());
  assert(staged.lastError() == Aht20Error::WriteFailed);
  Wire.failWrite = false;
  assert(staged.startMeasurement()); tick += 10; assert(!staged.updateMeasurement());
  tick += 80; assert(staged.updateMeasurement() && !staged.measurement().stale);
  std::puts("PASS staged_crc_write_failure_and_next_measurement");
#endif
}
"""


class Aht20Tests(unittest.TestCase):
    def test_actual_driver_sync_and_staged(self):
        def native(path):
            value = str(path.resolve()).replace("\\", "/")
            return "/mnt/" + value[0].lower() + value[2:] if os.name == "nt" else value
        prefix = ["wsl", "-d", "Ubuntu-22.04", "--exec"] if os.name == "nt" else []
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="aht20-test-") as directory:
            folder = Path(directory)
            (folder / "fake.h").write_text(STUB, encoding="utf-8")
            for name in ("Arduino.h", "Wire.h"):
                (folder / name).write_text('#include "fake.h"\n', encoding="utf-8")
            (folder / "main.cpp").write_text(MAIN, encoding="utf-8")
            for enabled in (0, 1):
                with self.subTest(async_enabled=enabled):
                    subprocess.run(prefix + ["g++", "-std=c++11", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=address,undefined", f"-DOMIPET_AHT20_ASYNC={enabled}",
                        "-I" + native(folder), "-I" + native(ROOT / "Firmware/include"),
                        "-I" + native(ROOT / "Firmware/src"), native(folder / "main.cpp"),
                        "-o", native(folder / "test")], check=True, timeout=60)
                    subprocess.run(prefix + [native(folder / "test")], check=True, timeout=30)


if __name__ == "__main__":
    unittest.main()
