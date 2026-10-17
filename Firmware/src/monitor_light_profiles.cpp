#include "protocol_experiment_config.h"
#if OMIPET_DESKTOP_CONTROL && OMIPET_MONITOR_LIGHTS && OMIPET_MONITOR_GREEN_OFF
#include "monitor_light_profiles.h"
#include <Arduino.h>
#include <nvs.h>

namespace OmiPetProtocol {
MonitorProfileStore monitorProfiles;
namespace {
constexpr size_t kRecordBytes = 30;
nvs_handle_t handle = 0;
bool ready = false;

bool persist(const MonitorProfiles& profiles) {
  if (!ready) return false;
  uint8_t record[kRecordBytes] = {1};
  for (unsigned i = 0; i < 4; ++i) record[1 + i] = (profiles.revision >> (8 * i)) & 255;
  for (unsigned i = 0; i < kMonitorStateCount; ++i) {
    const auto& light = profiles.lights[i];
    uint8_t* slot = record + 5 + i * 5;
    slot[0] = static_cast<uint8_t>(light.effect);
    slot[1] = light.red; slot[2] = light.green; slot[3] = light.blue; slot[4] = light.brightness;
  }
  //  NVS 单键替换保留掉电恢复和校验，不擦除其他命名空间 / NVS single-key replacement retains power-loss recovery and validation without erasing other namespaces
  return nvs_set_blob(handle, "profiles", record, sizeof(record)) == ESP_OK && nvs_commit(handle) == ESP_OK;
}
}

void beginMonitorProfiles() {
  if (ready) nvs_close(handle);
  MonitorProfiles loaded;
  ready = nvs_open("omi-monitor", NVS_READWRITE, &handle) == ESP_OK;
  const char* result = ready ? "defaults" : "storage-unavailable";
  if (ready) {
    uint8_t record[kRecordBytes] = {};
    size_t size = sizeof(record);
    const esp_err_t status = nvs_get_blob(handle, "profiles", record, &size);
    if (status == ESP_OK && size == sizeof(record) && record[0] == 1) {
      bool valid = true;
      for (unsigned i = 0; i < 4; ++i) loaded.revision |= static_cast<uint32_t>(record[1 + i]) << (8 * i);
      for (unsigned i = 0; i < kMonitorStateCount; ++i) {
        const uint8_t* slot = record + 5 + i * 5;
        if (slot[0] > static_cast<uint8_t>(LocalLightEffect::Off)) valid = false;
        auto& light = loaded.lights[i];
        light.effect = static_cast<LocalLightEffect>(slot[0]);
        light.red = slot[1]; light.green = slot[2]; light.blue = slot[3]; light.brightness = slot[4];
      }
      result = valid ? "loaded" : "invalid-defaults";
      if (!valid) loaded = MonitorProfiles{};
    } else if (status != ESP_ERR_NVS_NOT_FOUND) result = "invalid-defaults";
  }
  monitorProfiles.initialize(loaded, persist);
  Serial.printf("[MONITOR_CONFIG] load=%s revision=%lu\n", result, static_cast<unsigned long>(loaded.revision));
}
}  //  协议命名空间 / Protocol namespace
#endif
