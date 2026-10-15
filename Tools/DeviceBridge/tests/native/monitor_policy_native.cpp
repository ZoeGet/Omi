#include "device_protocol_session.h"
#include "led_arbitration.h"
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

using namespace OmiPetProtocol;
using namespace OmiPetLed;

namespace {
void check(bool value) { if (!value) throw std::runtime_error("monitor policy check failed"); }
const char* boot = "11111111111111111111111111111111";
const char* firstChannel = "22222222222222222222222222222222";
const char* secondChannel = "44444444444444444444444444444444";
const char* unknown = "{\"revision\":1,\"validForMs\":0,\"sourceLiveness\":\"unverified\",\"overallStatus\":\"unknown\",\"sessions\":[]}";
const char* nextUnknown = "{\"revision\":2,\"validForMs\":0,\"sourceLiveness\":\"unverified\",\"overallStatus\":\"unknown\",\"sessions\":[]}";
const LightArbitrationPolicy policy{LightFallback::Green, LightFallback::Green};

struct Fixture {
  ProtocolSession session{boot, {4096, 16, 8, 5000}};
  char output[4097] = {};
  const char* channel = firstChannel;
  Fixture() { open(firstChannel, 0); send(1, "hello", "{\"protocol\":1}", 0); }
  void open(const char* name, uint64_t now) {
    channel = name;
    check(session.open(channel, now, output, sizeof(output)) == SessionResult::Reply);
    check(std::strstr(output, "\"monitorGreenOff\":true") != nullptr);
  }
  std::string request(unsigned seq, const char* type, const char* body) {
    return std::string("{\"v\":1,\"boot\":\"") + boot + "\",\"channel\":\"" + channel +
        "\",\"session\":\"33333333333333333333333333333333\",\"seq\":" + std::to_string(seq) +
        ",\"type\":\"" + type + "\",\"body\":" + body + "}";
  }
  void send(unsigned seq, const char* type, const char* body, uint64_t now, bool ok = true) {
    const std::string raw = request(seq, type, body);
    check(session.receive(raw.data(), raw.size(), now, output, sizeof(output)) == SessionResult::Reply);
    check(std::strstr(output, ok ? "\"ok\":true" : "\"ok\":false") != nullptr);
  }
  LightDecision light() { return arbitrateLight(session.view(), false, policy, session.monitorOutput()); }
};
}

int main() {
  Fixture source;
  source.send(2, "snapshot", unknown, 1);
  check(source.session.view().displayStatus == std::string("unknown"));
  check(source.light().owner == LightOwner::Monitor && source.light().status == MonitorLightStatus::Idle);
  for (const char* status : {"unknown", "offline", "idle"}) {
    SessionView view{"monitor", status, true, 1, 1};
    check(arbitrateLight(view, false, policy).status == MonitorLightStatus::Idle);
  }
  source.session.advance(5001);
  check(source.light().owner == LightOwner::Off);
  std::cout << "PASS unknown_and_empty_sources_green_but_expired_connection_off\n";

  Fixture link;
  link.send(2, "snapshot", unknown, 1);
  link.session.disconnect();
  check(link.light().owner == LightOwner::Off);
  link.open(secondChannel, 2);
  link.send(1, "hello", "{\"protocol\":1}", 2);
  link.send(2, "heartbeat", "{}", 3);
  check(link.light().owner == LightOwner::Off);
  link.send(3, "snapshot", unknown, 4);
  check(link.light().owner == LightOwner::Monitor);
  link.send(4, "release", "{\"disconnect\":false}", 5, false);
  check(link.light().owner == LightOwner::Monitor);
  link.send(5, "release", "{\"disconnect\":true}", 6);
  check(link.light().owner == LightOwner::Off);
  check(std::strstr(link.output, "\"monitorOutput\":\"disconnected\"") != nullptr);
  link.send(5, "release", "{\"disconnect\":true}", 6);
  check(link.light().owner == LightOwner::Off);
  link.send(6, "release", "{}", 7);
  check(link.light().owner == LightOwner::Local);
  link.session.disconnect();
  check(link.light().owner == LightOwner::Local);
  std::cout << "PASS disconnect_off_survives_handshake_but_explicit_local_restores_local\n";

  Fixture voice;
  voice.send(2, "snapshot", unknown, 1);
  voice.session.yieldMonitorToVoice();
  voice.send(3, "snapshot", nextUnknown, 2);
  check(voice.light().owner == LightOwner::Local);
  voice.send(4, "release", "{\"disconnect\":true}", 3);
  check(voice.light().owner == LightOwner::Local);
  voice.session.disconnect();
  check(voice.light().owner == LightOwner::Local);
  std::cout << "PASS voice_exits_monitor_without_disconnection_overwriting_local_light\n";

  Fixture atomic;
  const std::string raw = atomic.request(2, "snapshot", unknown);
  check(atomic.session.receive(raw.data(), raw.size(), 1, atomic.output, 2) == SessionResult::OutputTooSmall);
  check(atomic.session.monitorOutput() == MonitorOutput::Local);
  atomic.send(2, "snapshot", unknown, 1);
  const std::string release = atomic.request(3, "release", "{\"disconnect\":true}");
  check(atomic.session.receive(release.data(), release.size(), 2, atomic.output, 2) == SessionResult::OutputTooSmall);
  check(atomic.light().owner == LightOwner::Monitor);
  std::cout << "PASS monitor_output_changes_only_after_complete_reply_commit\n";
}
