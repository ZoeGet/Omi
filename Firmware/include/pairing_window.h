#pragma once

#include <cstdint>
#include <limits>

namespace OmiPetPairing {

enum class WindowState { Closed, Open, InProgress, Paired, Expired, Locked, ClockInvalid };

//  仅管理配对窗口；密码证明和随机码由独立安全实现提供 / Manage only the pairing window; a separate security implementation supplies proofs and random codes
class PairingWindow {
 public:
  bool open(uint64_t nowMs, uint64_t validityMs, uint8_t maxAttempts) {
    close();
    if (validityMs == 0 || maxAttempts == 0 ||
        nowMs > std::numeric_limits<uint64_t>::max() - validityMs) {
      return false;
    }
    lastNowMs_ = nowMs;
    expiresAtMs_ = nowMs + validityMs;
    maxAttempts_ = maxAttempts;
    attempts_ = 0;
    state_ = WindowState::Open;
    return true;
  }

  WindowState advance(uint64_t nowMs) {
    if (state_ == WindowState::Closed || state_ == WindowState::Paired ||
        state_ == WindowState::Expired || state_ == WindowState::Locked ||
        state_ == WindowState::ClockInvalid) {
      return state_;
    }
    if (nowMs < lastNowMs_) {
      state_ = WindowState::ClockInvalid;
      return state_;
    }
    lastNowMs_ = nowMs;
    if (nowMs >= expiresAtMs_) {
      state_ = WindowState::Expired;
    }
    return state_;
  }

  bool beginAttempt(uint64_t nowMs) {
    if (advance(nowMs) != WindowState::Open) return false;
    ++attempts_;
    state_ = WindowState::InProgress;
    return true;
  }

  bool finishAttempt(bool verifiedProof, uint64_t nowMs) {
    if (advance(nowMs) != WindowState::InProgress) return false;
    if (verifiedProof) {
      state_ = WindowState::Paired;
      return true;
    }
    state_ = attempts_ >= maxAttempts_ ? WindowState::Locked : WindowState::Open;
    return false;
  }

  void close() {
    state_ = WindowState::Closed;
    lastNowMs_ = 0;
    expiresAtMs_ = 0;
    attempts_ = 0;
    maxAttempts_ = 0;
  }

  WindowState state() const { return state_; }
  uint8_t attempts() const { return attempts_; }

 private:
  WindowState state_ = WindowState::Closed;
  uint64_t lastNowMs_ = 0;
  uint64_t expiresAtMs_ = 0;
  uint8_t attempts_ = 0;
  uint8_t maxAttempts_ = 0;
};

}  //  配对命名空间 / Pairing namespace
