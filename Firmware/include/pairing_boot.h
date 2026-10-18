#pragma once

#include <cstdint>
#include <cstddef>

#include "pairing_code.h"
#include "pairing_window.h"

namespace OmiPetPairing {

constexpr uint64_t kPairingValidityMs = 300000;
constexpr uint8_t kPairingMaxAttempts = 5;

enum class StoredIdentityState { Unknown, Absent, Present };

//  显式本机请求才开放限时配对窗口；未知身份仍禁止开放 / Open a bounded pairing window only on an explicit local request; unknown identity remains blocked
class PairingBoot {
 public:
  using RandomWord = bool (*)(uint32_t* word, void* context);

  PairingBoot() = default;
  PairingBoot(const PairingBoot&) = delete;
  PairingBoot& operator=(const PairingBoot&) = delete;

  bool onBoot(StoredIdentityState identity) {
    if (initialized_) return false;
    initialized_ = true;
    eraseCode();
    window_.close();
    eligible_ = identity != StoredIdentityState::Unknown;
    attemptedThisBoot_ = false;
    return true;
  }

  bool tryOpen(uint64_t nowMs, bool displayReady, bool secureRandomReady,
               bool authenticatedPairingReady, RandomWord randomWord,
               void* context) {
    if (!initialized_ || !eligible_ || attemptedThisBoot_ || !displayReady ||
        !secureRandomReady || !authenticatedPairingReady ||
        randomWord == nullptr) {
      return false;
    }
    attemptedThisBoot_ = true;
    uint32_t word = 0;
    bool generated = false;
    for (uint8_t sample = 0; sample < 16; ++sample) {
      if (!randomWord(&word, context)) break;
      if (formatSixDigitCode(word, code_)) {
        generated = true;
        break;
      }
    }
    word = 0;
    if (!generated || !window_.open(nowMs, kPairingValidityMs,
                                    kPairingMaxAttempts)) {
      eraseCode();
      return false;
    }
    return true;
  }

  WindowState advance(uint64_t nowMs) {
    const WindowState state = window_.advance(nowMs);
    if (state != WindowState::Open && state != WindowState::InProgress) {
      eraseCode();
    }
    return state;
  }

  bool openByRequest(uint64_t nowMs, RandomWord randomWord, void* context) {
    if (!initialized_ || !eligible_ || window_.state() == WindowState::InProgress) return false;
    window_.close();
    eraseCode();
    attemptedThisBoot_ = false;
    return tryOpen(nowMs, true, true, true, randomWord, context);
  }

  void invalidateIdentity() {
    eligible_ = false;
    window_.close();
    eraseCode();
  }

  bool beginAttempt(uint64_t nowMs) {
    return advance(nowMs) == WindowState::Open &&
           window_.beginAttempt(nowMs);
  }

  //  只有密码证明通过且长期身份已安全保存时才能结束为已配对 / Finish as paired only after the password proof succeeds and the long-term identity is safely stored
  bool finishAttempt(bool authenticatedAndStored, uint64_t nowMs) {
    const bool paired = window_.finishAttempt(authenticatedAndStored, nowMs);
    advance(nowMs);
    return paired;
  }

  const char* visibleCode() const {
    const WindowState state = window_.state();
    return state == WindowState::Open || state == WindowState::InProgress
               ? code_
               : nullptr;
  }

  WindowState state() const { return window_.state(); }
  uint8_t attempts() const { return window_.attempts(); }

 private:
  void eraseCode() {
    volatile char* bytes = code_;
    for (size_t index = 0; index < 7; ++index) bytes[index] = '\0';
  }

  PairingWindow window_;
  char code_[7] = {};
  bool eligible_ = false;
  bool attemptedThisBoot_ = false;
  bool initialized_ = false;
};

}  //  配对命名空间 / Pairing namespace
