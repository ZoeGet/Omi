#pragma once

#include "device_protocol_session.h"
#include <cstring>

namespace OmiPetProtocol {

//  顺序也是持久化格式的一部分，不随界面排序改变 / This order is part of the storage format, independent of UI ordering
constexpr const char* kMonitorStates[] = {"working", "waitingApproval", "idle", "unknown", "offline"};
constexpr unsigned kMonitorStateCount = 5;

struct MonitorProfiles {
  uint32_t revision = 0;
  LocalLightCommand lights[kMonitorStateCount];
  MonitorProfiles() {
    for (auto& light : lights) {
      light.effect = LocalLightEffect::CenterExpand;
      light.red = 0; light.green = 255; light.blue = 0;
    }
    lights[0].red = 255; lights[0].green = 0;
    lights[1].red = 255;
  }
  const LocalLightCommand& forStatus(const char* status) const {
    for (unsigned i = 0; i < kMonitorStateCount; ++i) {
      if (status && std::strcmp(status, kMonitorStates[i]) == 0) return lights[i];
    }
    return lights[3];
  }
};

inline bool sameMonitorLights(const MonitorProfiles& a, const MonitorProfiles& b) {
  for (unsigned i = 0; i < kMonitorStateCount; ++i) {
    const auto& x = a.lights[i]; const auto& y = b.lights[i];
    if (x.effect != y.effect || x.red != y.red || x.green != y.green || x.blue != y.blue || x.brightness != y.brightness) return false;
  }
  return true;
}

//  先持久化整份配置，再发布到 USB 和无线共用的内存 / Persist the entire configuration before publishing shared USB and wireless state
class MonitorProfileStore {
 public:
  using Writer = bool (*)(const MonitorProfiles&);
  void initialize(const MonitorProfiles& profiles, Writer writer) { profiles_ = profiles; writer_ = writer; }
  const MonitorProfiles& current() const { return profiles_; }
  bool save(const MonitorProfiles& next) {
    if (next.revision == profiles_.revision) return sameMonitorLights(next, profiles_);
    if (!writer_ || !writer_(next)) return false;
    profiles_ = next;
    return true;
  }
 private:
  MonitorProfiles profiles_;
  Writer writer_ = nullptr;
};

extern MonitorProfileStore monitorProfiles;
void beginMonitorProfiles();

}  //  协议命名空间 / Protocol namespace
