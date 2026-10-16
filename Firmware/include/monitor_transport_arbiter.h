#pragma once

#include <cstdint>
#include <cstring>

#include "device_protocol_session.h"

namespace OmiPetProtocol {

enum class MonitorTransport : uint8_t { None, Usb, Wifi };

//  只将仍有有效租约的监控会话视为控制候选 / Consider only monitor sessions with active leases as control candidates
inline bool monitorSessionActive(const SessionView& view) {
  return view.mode != nullptr && std::strcmp(view.mode, "monitor") == 0 &&
         view.leaseActive;
}

//  USB 活动会话优先；无线必须先完成与本连接绑定的身份认证 / Prefer an active USB session; Wi-Fi requires identity authentication bound to this same connection
inline MonitorTransport selectMonitorTransport(const SessionView& usb,
                                               const SessionView& wifi,
                                               bool wifiAuthenticated) {
  if (monitorSessionActive(usb)) return MonitorTransport::Usb;
  if (wifiAuthenticated && monitorSessionActive(wifi)) {
    return MonitorTransport::Wifi;
  }
  return MonitorTransport::None;
}

//  无活动监控时保留上次归属，让断联关灯与显式本地选择正确延续 / Preserve ownership without active monitoring so disconnect-off and explicit local choices persist
class MonitorTransportSelection {
 public:
  void local(MonitorTransport transport) { selected_ = transport; }
  MonitorTransport select(const SessionView& usb, const SessionView& wifi, bool authenticated) {
    const auto active = selectMonitorTransport(usb, wifi, authenticated);
    if (active != MonitorTransport::None) selected_ = active;
    return selected_;
  }
 private:
  MonitorTransport selected_ = MonitorTransport::Usb;
};

}  //  协议命名空间 / Protocol namespace
