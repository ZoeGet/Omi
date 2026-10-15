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

}  //  协议命名空间 / Protocol namespace
