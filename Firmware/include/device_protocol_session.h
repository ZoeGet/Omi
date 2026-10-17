#pragma once

#include <cstddef>
#include <cstdint>

struct cJSON;

namespace OmiPetProtocol {

class MonitorProfileStore;

//  预算和单调毫秒时钟由调用方显式提供，没有实机默认参数 / Callers supply explicit budgets and a monotonic millisecond clock without device defaults
struct SessionLimits {
  std::size_t maxJsonBytes;
  std::size_t maxSessions;
  std::size_t maxDepth;
  uint32_t leaseMs;
};

enum class SessionResult { Reply, InvalidInput, InvalidClock, NotOpen, OutputTooSmall, OutOfMemory };

struct SessionView {
  const char* mode;
  const char* displayStatus;
  bool leaseActive;
  uint32_t lastSequence;
  uint32_t lastRevision;
};

enum class LocalLightEffect : uint8_t { Solid, Rainbow, Breathe, Sweep, CenterExpand, Off };
enum class MonitorOutput : uint8_t { Local, Connected, Disconnected };

//  仅表示已接受的本地设置，修订号保证重试不重复启动动画 / Describe an accepted local setting; the revision prevents retries from restarting animation
struct LocalLightCommand {
  uint32_t revision = 0;
  LocalLightEffect effect = LocalLightEffect::Solid;
  uint8_t red = 255;
  uint8_t green = 255;
  uint8_t blue = 255;
  uint8_t brightness = 16;
};

//  只维护协议逻辑状态；不操作串口、灯带或语音 / Maintain protocol state only without operating serial, LEDs, or voice
class ProtocolSession {
 public:
  ProtocolSession(const char* boot, SessionLimits limits);
  ~ProtocolSession();
  ProtocolSession(const ProtocolSession&) = delete;
  ProtocolSession& operator=(const ProtocolSession&) = delete;

  //  调用方为每次连接生成新标识；输出为无前缀 JSON / Callers generate a fresh connection identity; output is JSON without a prefix
  SessionResult open(const char* channel, uint64_t nowMs, char* output, std::size_t capacity);
  //  输入和输出缓冲必须分开；输出容量包含结尾 NUL / Input and output buffers must be distinct; output capacity includes the trailing NUL
  SessionResult receive(const char* data, std::size_t length, uint64_t nowMs,
                        char* output, std::size_t capacity);
  //  无消息时也必须定期推进时钟；32 位 millis 须先扩展 / Advance the clock even without messages; extend 32-bit millis before use
  bool advance(uint64_t nowMs);
  void disconnect();
  SessionView view() const;
  void setMonitorProfileStore(MonitorProfileStore* store) { profiles_ = store; }
  LocalLightCommand localLightCommand() const { return light_; }
  void allowLocalLightCommand(bool allowed, const char* reason = "voice-active") { localLightAllowed_ = allowed; localLightReason_ = reason; }
  bool takeLocalSelection() { const bool selected = localSelected_; localSelected_ = false; return selected; }
  MonitorOutput monitorOutput() const;
  //  语音退出监控输出，后续快照不能抢回，直到释放或新连接 / Voice exits monitor output and suppresses snapshots until release or a new connection
  void yieldMonitorToVoice() { monitorSelected_ = false; voiceSuppressed_ = true; }

 private:
  struct State {
    char session[33] = {};
    uint32_t sequence = 0;
    uint32_t revision = 0;
    uint64_t leaseStart = 0;
    uint64_t snapshotStart = 0;
    uint32_t snapshotValidity = 0;
    bool leaseActive = false;
    bool expired = false;
    bool monitor = false;
    const char* display = "unknown";
  };
  SessionView stateView(const State& state) const;
  SessionResult writeAck(const cJSON* request, const State& state, bool ok,
                         const char* code, bool duplicate, bool monitorSelected,
                         char* output, std::size_t capacity, const struct MonitorProfiles* profiles = nullptr) const;
  MonitorOutput monitorOutput(const State& state, bool selected) const;

  MonitorProfileStore* profiles_ = nullptr;
  SessionLimits limits_;
  char boot_[33] = {};
  char channel_[33] = {};
  bool valid_ = false;
  bool opened_ = false;
  uint64_t now_ = 0;
  State state_;
  cJSON* lastRequest_ = nullptr;
  bool lastOk_ = false;
  const char* lastCode_ = "ok";
  LocalLightCommand light_;
  bool localLightAllowed_ = true;
  const char* localLightReason_ = "voice-active";
  bool localSelected_ = false;
  bool monitorSelected_ = false;
  bool voiceSuppressed_ = false;
};

}  //  协议命名空间 / Protocol namespace
