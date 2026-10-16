#include "device_protocol_session.h"
#include "cJSON.h"
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace OmiPetProtocol;

namespace {
const char* boot = "11111111111111111111111111111111";
const char* channel = "22222222222222222222222222222222";
const char* light = "{\"effect\":\"sweep\",\"red\":0,\"green\":0,\"blue\":255,\"brightness\":16}";

void require(bool value, const char* reason) { if (!value) throw std::runtime_error(reason); }

std::string message(unsigned sequence, const char* type, const char* body) {
  return std::string("{\"v\":1,\"boot\":\"") + boot + "\",\"channel\":\"" + channel +
      "\",\"session\":\"33333333333333333333333333333333\",\"seq\":" + std::to_string(sequence) +
      ",\"type\":\"" + type + "\",\"body\":" + body + "}";
}

void exchange(ProtocolSession& session, unsigned sequence, const char* type,
               const char* body, const char* code, uint64_t now = 1) {
  char output[4097];
  const std::string request = message(sequence, type, body);
  require(session.receive(request.data(), request.size(), now, output, sizeof(output)) == SessionResult::Reply, "reply");
  cJSON* reply = cJSON_Parse(output);
  require(reply != nullptr, "JSON reply");
  const cJSON* result = cJSON_GetObjectItemCaseSensitive(reply, "body");
  const cJSON* actual = cJSON_GetObjectItemCaseSensitive(result, "code");
  const bool matches = actual && actual->valuestring && std::strcmp(actual->valuestring, code) == 0;
  cJSON_Delete(reply);
  require(matches, "reply code");
}
}

int main() {
  ProtocolSession session(boot, {4096, 16, 8, 5000});
  char output[4097];
  require(session.open(channel, 0, output, sizeof(output)) == SessionResult::Reply, "open");
  require(std::strstr(output, "\"light\"") != nullptr, "advertise real capability");
  exchange(session, 1, "hello", "{\"protocol\":1}", "ok");
  const std::string first = message(2, "light", light);
  require(session.receive(first.data(), first.size(), 1, output, 2) == SessionResult::OutputTooSmall, "short reply");
  require(session.localLightCommand().revision == 0, "no partial apply");
  exchange(session, 2, "light", light, "ok");
  const LocalLightCommand accepted = session.localLightCommand();
  require(session.takeLocalSelection() && !session.takeLocalSelection(), "local intent consumed once");
  require(accepted.revision == 1 && accepted.effect == LocalLightEffect::Sweep && accepted.blue == 255 && accepted.brightness == 16, "accepted setting");
  exchange(session, 2, "light", light, "ok");
  require(!session.takeLocalSelection(), "duplicate does not reclaim local ownership");
  require(session.localLightCommand().revision == 1, "duplicate does not restart");
  std::cout << "PASS desktop_light_atomic_acceptance_and_retry_deduplication\n";

  exchange(session, 3, "light", "{\"effect\":\"off\",\"red\":0,\"green\":0,\"blue\":0,\"brightness\":256}", "invalid-light-setting");
  require(session.localLightCommand().revision == 1, "invalid setting unchanged");
  session.allowLocalLightCommand(false);
  exchange(session, 4, "light", light, "voice-active");
  session.allowLocalLightCommand(true);
  exchange(session, 5, "snapshot", "{\"revision\":1,\"validForMs\":0,\"sourceLiveness\":\"unverified\",\"overallStatus\":\"unknown\",\"sessions\":[]}", "ok");
  exchange(session, 6, "light", light, "monitor-mode-active");
  require(session.localLightCommand().revision == 1, "monitor and voice cannot be overridden");
  exchange(session, 7, "release", "{}", "ok");
  exchange(session, 8, "light", light, "ok");
  require(session.localLightCommand().revision == 2, "release enables manual command");
  session.takeLocalSelection();
  session.allowLocalLightCommand(false, "usb-priority");
  exchange(session, 9, "light", light, "usb-priority");
  require(session.localLightCommand().revision == 2 && !session.takeLocalSelection(), "USB blocks wireless manual ownership");
  session.disconnect();
  require(session.localLightCommand().revision == 2, "disconnect does not replay or erase local setting");
  std::cout << "PASS desktop_monitor_and_voice_lock_manual_settings_until_release\n";
}
