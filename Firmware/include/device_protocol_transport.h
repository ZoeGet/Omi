#pragma once

#include "device_protocol_framer.h"
#include "device_protocol_session.h"
#include <cstring>

namespace OmiPetProtocol {

struct TransportStats {
  uint32_t probes = 0;
  uint32_t requests = 0;
  uint32_t rejected = 0;
  uint32_t sent = 0;
  uint32_t stalled = 0;
  uint32_t staleReplies = 0;
  uint32_t writeFailures = 0;
  uint32_t lastSessionFailure = 0;
  uint32_t lastFrameFailure = 0;
  uint32_t linkLosses = 0;
  uint32_t reopens = 0;
  uint32_t linkDownPolls = 0;
  uint64_t lastLinkDownMs = 0;
  uint64_t maxLinkDownMs = 0;
};

//  单槽发送与有界接收；端口适配器必须支持整帧写入 / Single-slot sending and bounded receiving; port adapters must support whole-frame writes
template <std::size_t MaxJsonBytes>
class ProtocolTransport {
 public:
  ProtocolTransport(const char* boot, std::size_t maxSessions, std::size_t maxDepth, uint32_t leaseMs)
      : session_(boot, {MaxJsonBytes, maxSessions, maxDepth, leaseMs}), leaseMs_(leaseMs) {}

  void disconnect() {
    session_.disconnect();
    framer_ = SerialFramer<MaxJsonBytes>{};
    framer_.discardUntilNewline();
    pending_ = 0;
  }

  SessionView view() const { return session_.view(); }
  LocalLightCommand localLightCommand() const { return session_.localLightCommand(); }
  void allowLocalLightCommand(bool allowed) { session_.allowLocalLightCommand(allowed); }
  MonitorOutput monitorOutput() const { return session_.monitorOutput(); }
  void yieldMonitorToVoice() { session_.yieldMonitorToVoice(); }
  const TransportStats& stats() const { return stats_; }

  template <class Port, class NewToken>
  void poll(Port& port, uint64_t now, std::size_t rxBudget, NewToken newToken, void (*debugWake)()) {
    if (!session_.advance(now)) { disconnect(); return; }
    if (!port.plugged()) {
      if (wasPlugged_) {
        ++stats_.linkLosses;
        linkDownAt_ = now;
        linkDownActive_ = true;
      }
      ++stats_.linkDownPolls;
      wasPlugged_ = false;
      disconnect();
      return;
    }
    if (linkDownActive_) {
      //  仅测量原有断线信号的持续时间，不改变断线处理 / Measure existing link-signal gaps without changing disconnect handling
      stats_.lastLinkDownMs = now >= linkDownAt_ ? now - linkDownAt_ : 0;
      if (stats_.lastLinkDownMs > stats_.maxLinkDownMs) stats_.maxLinkDownMs = stats_.lastLinkDownMs;
      linkDownActive_ = false;
    }
    wasPlugged_ = true;
    if (pending_ && (now - pendingAt_ >= leaseMs_ || (!welcome_ && changed()))) {
      ++stats_.staleReplies;
      pending_ = 0;
    }
    //  发送拥塞时仍允许读取探测帧以建立新连接，不建立隐式命令队列 / Allow discovery during congestion without creating an implicit command queue
    for (std::size_t count = 0; count < rxBudget && port.available() > 0; ++count) {
      const int byte = port.read();
      if (byte < 0) break;
      const FeedResult result = framer_.feed(static_cast<uint8_t>(byte));
      if (result == FeedResult::DebugWake) { if (debugWake) debugWake(); }
      else if (result == FeedResult::FrameReady) {
        if (framer_.frameLength() == 1 && framer_.frame()[0] == '?') {
          char channel[33];
          newToken(channel);
          session_.disconnect();
          pending_ = 0;
          ++stats_.probes;
          queue(session_.open(channel, now, tx_ + 6, MaxJsonBytes + 1), now, true);
        } else if (!pending_) {
          ++stats_.requests;
          const SessionResult reply = session_.receive(framer_.frame(), framer_.frameLength(), now, tx_ + 6, MaxJsonBytes + 1);
          if (reply == SessionResult::NotOpen) {
            //  旧连接请求只触发新握手，不执行正文或悄悄恢复旧控制权 / Stale connection requests trigger a fresh handshake without executing their body or restoring control
            char channel[33];
            newToken(channel);
            ++stats_.reopens;
            queue(session_.open(channel, now, tx_ + 6, MaxJsonBytes + 1), now, true);
          } else queue(reply, now, false);
        } else ++stats_.rejected;
        break;
      } else if (result != FeedResult::None) {
        ++stats_.rejected;
        stats_.lastFrameFailure = static_cast<uint32_t>(result);
      }
    }
    if (!pending_) return;
    if (!port.ready() || port.availableForWrite() < static_cast<int>(pending_)) { ++stats_.stalled; return; }
    //  一次写入完整前缀、正文和换行，避免本地日志插入协议帧 / Write prefix, body, and newline together to prevent local logs splitting protocol frames
    if (port.write(reinterpret_cast<const uint8_t*>(tx_), pending_) != pending_) {
      ++stats_.writeFailures;
      disconnect();
      return;
    }
    ++stats_.sent;
    pending_ = 0;
  }

 private:
  bool changed() const {
    const SessionView current = session_.view();
    return std::strcmp(current.mode, pendingView_.mode) != 0 ||
           std::strcmp(current.displayStatus, pendingView_.displayStatus) != 0 ||
           current.leaseActive != pendingView_.leaseActive;
  }
  void queue(SessionResult result, uint64_t now, bool welcome) {
    if (result != SessionResult::Reply) {
      ++stats_.rejected;
      stats_.lastSessionFailure = static_cast<uint32_t>(result);
      return;
    }
    std::memcpy(tx_, "\n@OMI ", 6);
    pending_ = 6 + std::strlen(tx_ + 6);
    tx_[pending_++] = '\n';
    pendingAt_ = now;
    pendingView_ = session_.view();
    welcome_ = welcome;
  }
  ProtocolSession session_;
  SerialFramer<MaxJsonBytes> framer_;
  char tx_[MaxJsonBytes + 8] = {};
  std::size_t pending_ = 0;
  uint64_t pendingAt_ = 0;
  uint32_t leaseMs_;
  SessionView pendingView_ = {"local", "unknown", false, 0, 0};
  bool welcome_ = false;
  bool wasPlugged_ = true;
  bool linkDownActive_ = false;
  uint64_t linkDownAt_ = 0;
  TransportStats stats_;
};

}  //  协议命名空间 / Protocol namespace
