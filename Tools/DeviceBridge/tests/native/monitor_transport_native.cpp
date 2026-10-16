#include "monitor_transport_arbiter.h"
#include "led_arbitration.h"

#include <cassert>
#include <cstdio>

using OmiPetProtocol::MonitorTransport;
using OmiPetProtocol::SessionView;

int main() {
  SessionView usb{"monitor", "working", true, 1, 1};
  SessionView wifi{"monitor", "waitingApproval", true, 1, 1};
  assert(OmiPetProtocol::selectMonitorTransport(usb, wifi, true) ==
         MonitorTransport::Usb);
  usb.displayStatus = "unknown";
  assert(OmiPetProtocol::selectMonitorTransport(usb, wifi, true) ==
         MonitorTransport::Usb);
  const OmiPetLed::LightArbitrationPolicy restore{
      OmiPetLed::LightFallback::Local, OmiPetLed::LightFallback::Local};
  assert(OmiPetLed::arbitrateLight(usb, false, restore).owner ==
         OmiPetLed::LightOwner::Local);
  std::puts("PASS active_usb_blocks_wifi_even_when_usb_status_unknown");

  usb = {"local", "unknown", false, 2, 2};
  assert(OmiPetProtocol::selectMonitorTransport(usb, wifi, true) ==
         MonitorTransport::Wifi);
  assert(OmiPetLed::arbitrateLight(wifi, false, restore).status ==
         OmiPetLed::MonitorLightStatus::WaitingApproval);
  assert(OmiPetLed::arbitrateLight(wifi, true, restore).owner ==
         OmiPetLed::LightOwner::Local);
  std::puts("PASS usb_exit_promotes_authenticated_wifi_but_voice_stays_first");

  assert(OmiPetProtocol::selectMonitorTransport(usb, wifi, false) ==
         MonitorTransport::None);
  wifi.leaseActive = false;
  assert(OmiPetProtocol::selectMonitorTransport(usb, wifi, true) ==
         MonitorTransport::None);
  std::puts("PASS unauthenticated_or_expired_wifi_never_controls");

  wifi = {"monitor", "idle", true, 3, 3};
  usb = {"monitor", "working", true, 3, 3};
  assert(OmiPetProtocol::selectMonitorTransport(usb, wifi, true) ==
         MonitorTransport::Usb);
  std::puts("PASS usb_reconnect_preempts_wifi");
  OmiPetProtocol::MonitorTransportSelection selection;
  assert(selection.select(usb, wifi, true) == MonitorTransport::Usb);
  usb.leaseActive = false;
  assert(selection.select(usb, wifi, true) == MonitorTransport::Wifi);
  wifi.leaseActive = false;
  assert(selection.select(usb, wifi, false) == MonitorTransport::Wifi);
  selection.local(MonitorTransport::Usb);
  assert(selection.select(usb, wifi, false) == MonitorTransport::Usb);
  std::puts("PASS disconnect_preserves_last_output_until_explicit_local_choice");
}
