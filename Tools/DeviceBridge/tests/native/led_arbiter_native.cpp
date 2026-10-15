#include <cassert>
#include <cstdio>
#include "led_arbitration.h"

using OmiPetLed::LightArbitrationPolicy;
using OmiPetLed::LightDecision;
using OmiPetLed::LightFallback;
using OmiPetLed::LightOwner;
using OmiPetLed::MonitorLightStatus;
using OmiPetLed::MonitorLightRgb;
using OmiPetLed::arbitrateLight;
using OmiPetLed::monitorLightRgb;
using OmiPetLed::VoiceLightOverride;
using OmiPetProtocol::SessionView;

int main() {
  const LightArbitrationPolicy restore{LightFallback::Local, LightFallback::Local};
  const LightArbitrationPolicy dark{LightFallback::Off, LightFallback::Off};
  SessionView view{"local", "unknown", false, 0, 0};

  assert(arbitrateLight(view, false, dark).owner == LightOwner::Local);
  view = {"monitor", "working", true, 1, 1};
  LightDecision result = arbitrateLight(view, false, restore);
  assert(result.owner == LightOwner::Monitor && result.status == MonitorLightStatus::Working);
  view.displayStatus = "waitingApproval";
  result = arbitrateLight(view, false, restore);
  assert(result.owner == LightOwner::Monitor && result.status == MonitorLightStatus::WaitingApproval);
  view.displayStatus = "idle";
  result = arbitrateLight(view, false, restore);
  assert(result.owner == LightOwner::Monitor && result.status == MonitorLightStatus::Idle);
  std::puts("PASS fresh_monitor_states");

  MonitorLightRgb rgb{};
  assert(monitorLightRgb(MonitorLightStatus::Working, rgb) &&
         rgb.red == 255 && rgb.green == 0 && rgb.blue == 0);
  assert(monitorLightRgb(MonitorLightStatus::WaitingApproval, rgb) &&
         rgb.red == 255 && rgb.green == 255 && rgb.blue == 0);
  assert(monitorLightRgb(MonitorLightStatus::Idle, rgb) &&
         rgb.red == 0 && rgb.green == 255 && rgb.blue == 0);
  assert(!monitorLightRgb(MonitorLightStatus::Unknown, rgb));
  assert(!monitorLightRgb(MonitorLightStatus::Offline, rgb));
  std::puts("PASS confirmed_status_colors");

  view.displayStatus = "unknown";
  assert(arbitrateLight(view, false, restore).owner == LightOwner::Local);
  assert(arbitrateLight(view, false, dark).owner == LightOwner::Off);
  view.displayStatus = "offline";
  assert(arbitrateLight(view, false, restore).owner == LightOwner::Local);
  assert(arbitrateLight(view, false, dark).owner == LightOwner::Off);
  std::puts("PASS explicit_fallbacks");

  view.displayStatus = "working";
  assert(arbitrateLight(view, true, dark).owner == LightOwner::Local);
  view.leaseActive = false;
  assert(arbitrateLight(view, false, dark).owner == LightOwner::Local);
  view = {"local", "unknown", false, 2, 2};
  assert(arbitrateLight(view, false, dark).owner == LightOwner::Local);
  std::puts("PASS local_override_and_expiry");

  VoiceLightOverride voice;
  view = {"monitor", "working", true, 4, 4};
  assert(!voice.observe(view));
  voice.onVoiceInteraction();
  assert(arbitrateLight(view, voice.observe(view), restore).owner == LightOwner::Local);
  view.displayStatus = "waitingApproval";
  assert(arbitrateLight(view, voice.observe(view), restore).owner == LightOwner::Local);
  view = {"local", "unknown", false, 5, 5};
  assert(!voice.observe(view));
  view = {"monitor", "idle", true, 6, 6};
  assert(arbitrateLight(view, voice.observe(view), restore).owner == LightOwner::Monitor);
  std::puts("PASS voice_takeover_latches_until_release");

  view = {"monitor", "healthy", true, 3, 3};
  result = arbitrateLight(view, false, dark);
  assert(result.owner == LightOwner::Off && result.status == MonitorLightStatus::Unknown);
  view.displayStatus = nullptr;
  assert(arbitrateLight(view, false, restore).owner == LightOwner::Local);
  view.mode = nullptr;
  assert(arbitrateLight(view, false, dark).owner == LightOwner::Local);
  std::puts("PASS malformed_state_fails_closed");
}
