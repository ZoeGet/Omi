#include "monitor_light_profiles.h"
#include "led_arbitration.h"
#include "Arduino.h"
#include "nvs.h"
#include "cJSON.h"
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace OmiPetProtocol;
FakeSerial Serial;
uint32_t millis() { return 0; }
namespace {
std::vector<uint8_t> durable, pending;
bool failOpen = false, failWrite = false, failCommit = false;
unsigned writes = 0;
const char* boot = "11111111111111111111111111111111";
const char* channel = "22222222222222222222222222222222";
void require(bool value, const char* why) { if (!value) throw std::runtime_error(why); }
std::string message(unsigned seq, const char* type, const std::string& body) {
  return std::string("{\"v\":1,\"boot\":\"") + boot + "\",\"channel\":\"" + channel +
    "\",\"session\":\"33333333333333333333333333333333\",\"seq\":" + std::to_string(seq) +
    ",\"type\":\"" + type + "\",\"body\":" + body + "}";
}
std::string config(uint32_t revision, unsigned brightness = 70, const char* mode = "sweep") {
  std::string body = "{\"revision\":" + std::to_string(revision) + ",\"profiles\":{";
  for (unsigned i = 0; i < kMonitorStateCount; ++i) {
    if (i) body += ",";
    body += std::string("\"") + kMonitorStates[i] + "\":{\"effect\":\"" + mode +
      "\",\"red\":" + std::to_string(i) + ",\"green\":90,\"blue\":255,\"brightness\":" + std::to_string(brightness) + "}";
  }
  return body + "}}";
}
void open(ProtocolSession& session) {
  char out[4097];
  session.setMonitorProfileStore(&monitorProfiles);
  require(session.open(channel, 0, out, sizeof(out)) == SessionResult::Reply, "open");
  require(std::strstr(out, "monitorProfile"), "capability");
  const auto hello = message(1, "hello", "{\"protocol\":1}");
  require(session.receive(hello.data(), hello.size(), 1, out, sizeof(out)) == SessionResult::Reply, "hello");
}
void exchange(ProtocolSession& session, unsigned seq, const std::string& body, const char* code, const char* type = "monitorProfile") {
  char out[4097]; const auto request = message(seq, type, body);
  require(session.receive(request.data(), request.size(), seq + 1, out, sizeof(out)) == SessionResult::Reply, "reply");
  cJSON* root = cJSON_Parse(out);
  const auto result = cJSON_GetObjectItemCaseSensitive(root, "body");
  const auto actual = cJSON_GetObjectItemCaseSensitive(result, "code");
  require(actual && actual->valuestring && std::strcmp(actual->valuestring, code) == 0, out);
  const auto profile = cJSON_GetObjectItemCaseSensitive(result, "monitorProfile");
  require(profile && cJSON_GetObjectItemCaseSensitive(profile, "revision")->valuedouble == monitorProfiles.current().revision, "readback revision");
  cJSON_Delete(root);
}
}
extern "C" {
esp_err_t nvs_open(const char* name, nvs_open_mode_t, nvs_handle_t* handle) {
  require(std::strcmp(name, "omi-monitor") == 0, "dedicated namespace");
  *handle = 1; return failOpen ? ESP_ERR_NVS_FAIL : ESP_OK;
}
void nvs_close(nvs_handle_t) {}
esp_err_t nvs_get_blob(nvs_handle_t, const char* key, void* output, size_t* size) {
  require(std::strcmp(key, "profiles") == 0, "single key");
  if (durable.empty()) return ESP_ERR_NVS_NOT_FOUND;
  if (*size < durable.size()) return ESP_ERR_NVS_FAIL;
  *size = durable.size(); std::memcpy(output, durable.data(), *size); return ESP_OK;
}
esp_err_t nvs_set_blob(nvs_handle_t, const char*, const void* data, size_t size) {
  ++writes; if (failWrite) return ESP_ERR_NVS_FAIL;
  pending.assign(static_cast<const uint8_t*>(data), static_cast<const uint8_t*>(data) + size); return ESP_OK;
}
esp_err_t nvs_commit(nvs_handle_t) { if (failCommit) return ESP_ERR_NVS_FAIL; durable = pending; return ESP_OK; }
}
int main() {
  beginMonitorProfiles();
  require(monitorProfiles.current().revision == 0, "missing uses defaults");
  require(monitorProfiles.current().forStatus("working").red == 255, "working default red");
  require(monitorProfiles.current().forStatus("waitingApproval").green == 255, "waiting default yellow");
  ProtocolSession usb(boot, {4096,16,8,5000}); open(usb);
  auto first = message(2, "monitorProfile", config(0)); char shortOut[2];
  require(usb.receive(first.data(), first.size(), 2, shortOut, sizeof(shortOut)) == SessionResult::OutputTooSmall, "short buffer rejected");
  require(writes == 0 && monitorProfiles.current().revision == 0, "no mutation before full ACK");
  exchange(usb, 2, config(0), "ok");
  require(writes == 1 && durable.size() == 30 && monitorProfiles.current().revision == 1, "durable full save");
  exchange(usb, 2, config(0), "ok");
  exchange(usb, 3, config(1), "ok");
  require(writes == 1, "duplicates and identical content do not wear flash");
  beginMonitorProfiles();
  require(monitorProfiles.current().revision == 1, "boot reload revision");
  for (unsigned i=0; i<kMonitorStateCount; ++i) {
    const auto& light = monitorProfiles.current().forStatus(kMonitorStates[i]);
    require(light.effect == LocalLightEffect::Sweep && light.red == i && light.brightness == 70, "all statuses survive reboot");
  }
  std::cout << "PASS monitor_profiles_atomic_save_dedup_and_reboot_all_states\n";
  ProtocolSession wifi(boot, {4096,16,8,5000}); open(wifi);
  exchange(wifi, 2, config(1, 0, "off"), "ok");
  exchange(usb, 4, config(1, 255), "monitor-profile-conflict");
  exchange(usb, 5, "{}", "ok");
  require(monitorProfiles.current().revision == 2, "shared USB WSS revision");
  failWrite = true;
  exchange(usb, 6, config(2, 255), "monitor-profile-save-failed"); failWrite = false;
  require(monitorProfiles.current().revision == 2, "write failure retains current");
  failCommit = true;
  exchange(usb, 7, config(2, 255), "monitor-profile-save-failed"); failCommit = false;
  beginMonitorProfiles();
  require(monitorProfiles.current().revision == 2, "commit failure retains durable");
  exchange(usb, 8, config(2, 256), "invalid-light-setting");
  exchange(usb, 9, config(2, 255, "invalid"), "invalid-light-setting");
  exchange(usb, 10, "{\"revision\":2,\"profiles\":{}}", "invalid-monitor-profile");
  exchange(usb, 11, "{\"revision\":1,\"validForMs\":0,\"sourceLiveness\":\"unverified\",\"overallStatus\":\"unknown\",\"sessions\":[]}", "ok", "snapshot");
  exchange(usb, 12, config(2, 255, "rainbow"), "ok");
  require(std::strcmp(usb.view().mode, "monitor") == 0, "saving retains monitor");
  require(!usb.takeLocalSelection(), "profile never selects local output");
  using namespace OmiPetLed;
  const LightArbitrationPolicy policy{LightFallback::Green, LightFallback::Green};
  usb.disconnect();
  require(arbitrateLight(usb.view(), false, policy, usb.monitorOutput()).owner == LightOwner::Off, "disconnect always off");
  wifi.yieldMonitorToVoice();
  require(wifi.monitorOutput() == MonitorOutput::Local, "voice keeps priority");
  std::cout << "PASS monitor_profiles_conflict_failures_monitor_disconnect_and_voice\n";
  const auto good = durable;
  for (unsigned test=0; test<3; ++test) {
    durable=good;
    if (test==0) durable[0]=99;
    if (test==1) durable[5]=99;
    if (test==2) durable.pop_back();
    beginMonitorProfiles();
    require(monitorProfiles.current().revision == 0, "invalid storage defaults");
  }
  durable=good; failOpen=true; beginMonitorProfiles();
  require(monitorProfiles.current().revision == 0, "unavailable storage defaults");
  ProtocolSession unavailable(boot, {4096,16,8,5000}); open(unavailable);
  exchange(unavailable, 2, config(0), "monitor-profile-save-failed");
  std::cout << "PASS monitor_profiles_storage_schema_corruption_and_unavailable\n";
}
