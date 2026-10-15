#pragma once

#include <cstdint>
#include <cstring>
#include "device_protocol_session.h"

namespace OmiPetLed {

//  仲裁结果只描述输出归属，不绘制灯珠 / Arbitration results describe ownership without rendering pixels
enum class LightOwner : uint8_t { Local, Monitor, Off };
enum class MonitorLightStatus : uint8_t { Unknown, Working, WaitingApproval, Idle, Offline };
enum class LightFallback : uint8_t { Local, Off, Green };

struct LightArbitrationPolicy {
  LightFallback unknown;
  LightFallback offline;
};

struct LightDecision {
  LightOwner owner;
  MonitorLightStatus status;
};

struct MonitorLightRgb {
  uint8_t red;
  uint8_t green;
  uint8_t blue;
};

//  语音接管持续到当前监控连接退出，后续快照不能立即抢回灯带 / Keep voice ownership until the current monitor connection exits
class VoiceLightOverride {
 public:
  void onVoiceInteraction() { active_ = true; }
  bool observe(const OmiPetProtocol::SessionView& view) {
    if (!view.mode || std::strcmp(view.mode, "monitor") != 0 || !view.leaseActive) {
      active_ = false;
    }
    return active_;
  }

 private:
  bool active_ = false;
};

//  仅为已确认的三种活动状态给出颜色，其他状态必须回退 / Map only the three confirmed active states; all others must fall back
inline bool monitorLightRgb(MonitorLightStatus status, MonitorLightRgb& color) {
  switch (status) {
    case MonitorLightStatus::Working: color = {255, 0, 0}; return true;
    case MonitorLightStatus::WaitingApproval: color = {255, 255, 0}; return true;
    case MonitorLightStatus::Idle: color = {0, 255, 0}; return true;
    default: return false;
  }
}

//  未识别的协议状态按未知处理，避免误显示健康状态 / Treat unrecognized protocol states as unknown rather than healthy
inline MonitorLightStatus parseMonitorLightStatus(const char* status) {
  if (!status) return MonitorLightStatus::Unknown;
  if (std::strcmp(status, "working") == 0) return MonitorLightStatus::Working;
  if (std::strcmp(status, "waitingApproval") == 0) return MonitorLightStatus::WaitingApproval;
  if (std::strcmp(status, "idle") == 0) return MonitorLightStatus::Idle;
  if (std::strcmp(status, "offline") == 0) return MonitorLightStatus::Offline;
  return MonitorLightStatus::Unknown;
}

//  调用方显式提供本地优先权和未知/离线回退策略 / Callers explicitly supply local override and unknown/offline fallback policies
inline LightDecision arbitrateLight(const OmiPetProtocol::SessionView& view,
                                    bool localOverride,
                                    LightArbitrationPolicy policy,
                                    OmiPetProtocol::MonitorOutput output = OmiPetProtocol::MonitorOutput::Connected) {
  if (output == OmiPetProtocol::MonitorOutput::Local) return {LightOwner::Local, MonitorLightStatus::Unknown};
  if (!localOverride && output == OmiPetProtocol::MonitorOutput::Disconnected) {
    return {LightOwner::Off, MonitorLightStatus::Unknown};
  }
  if (localOverride || !view.mode || std::strcmp(view.mode, "monitor") != 0 ||
      !view.leaseActive) {
    return {LightOwner::Local, MonitorLightStatus::Unknown};
  }

  const MonitorLightStatus status = parseMonitorLightStatus(view.displayStatus);
  const auto fallback = [](LightFallback selected) {
    return selected == LightFallback::Off ? LightOwner::Off : LightOwner::Local;
  };
  if (status == MonitorLightStatus::Unknown) {
    if (policy.unknown == LightFallback::Green) return {LightOwner::Monitor, MonitorLightStatus::Idle};
    return {fallback(policy.unknown), status};
  }
  if (status == MonitorLightStatus::Offline) {
    if (policy.offline == LightFallback::Green) return {LightOwner::Monitor, MonitorLightStatus::Idle};
    return {fallback(policy.offline), status};
  }
  return {LightOwner::Monitor, status};
}

}  //  灯光命名空间 / LED namespace
