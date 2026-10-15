#include "pairing_boot.h"
#include "pairing_code.h"
#include "pairing_window.h"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

using OmiPetPairing::PairingWindow;
using OmiPetPairing::WindowState;
using OmiPetPairing::StoredIdentityState;

struct RandomSequence {
  uint32_t words[3];
  int count;
  int position;
};

bool nextRandomWord(uint32_t* word, void* context) {
  auto* sequence = static_cast<RandomSequence*>(context);
  if (sequence->position >= sequence->count) return false;
  *word = sequence->words[sequence->position++];
  return true;
}

int main() {
  char code[7] = {};
  assert(OmiPetPairing::formatSixDigitCode(0, code));
  assert(std::string(code) == "000000");
  assert(OmiPetPairing::formatSixDigitCode(1, code));
  assert(std::string(code) == "000001");
  assert(OmiPetPairing::formatSixDigitCode(4293999999U, code));
  assert(std::string(code) == "999999");
  assert(!OmiPetPairing::formatSixDigitCode(4294000000U, code));
  assert(!OmiPetPairing::formatSixDigitCode(0, nullptr));
  std::cout << "PASS unbiased_six_digit_mapping_and_rejection\n";

  PairingWindow window;
  assert(!window.open(0, 0, 5));
  assert(!window.open(0, 300000, 0));
  assert(!window.open(std::numeric_limits<uint64_t>::max() - 1, 300000, 5));
  assert(window.state() == WindowState::Closed);
  std::cout << "PASS invalid_window_rejected\n";

  assert(window.open(1000, 300000, 5));
  assert(window.beginAttempt(1000));
  assert(!window.beginAttempt(1000));
  assert(!window.finishAttempt(false, 1001));
  assert(window.attempts() == 1);
  assert(window.state() == WindowState::Open);
  for (int i = 2; i <= 5; ++i) {
    assert(window.beginAttempt(1000 + i * 2));
    assert(!window.finishAttempt(false, 1001 + i * 2));
  }
  assert(window.state() == WindowState::Locked);
  assert(window.attempts() == 5);
  assert(!window.beginAttempt(1012));
  assert(!window.finishAttempt(true, 1013));
  std::cout << "PASS five_failures_lock_and_parallel_attempt_denied\n";

  assert(window.open(2000, 300000, 5));
  assert(window.beginAttempt(2001));
  assert(window.advance(302000) == WindowState::Expired);
  assert(!window.finishAttempt(true, 302000));
  assert(!window.beginAttempt(302001));
  std::cout << "PASS expiry_rejects_late_proof\n";

  assert(window.open(4000, 300000, 5));
  assert(window.beginAttempt(4001));
  assert(window.advance(4000) == WindowState::ClockInvalid);
  assert(!window.finishAttempt(true, 4002));
  std::cout << "PASS clock_rollback_fails_closed\n";

  assert(window.open(5000, 300000, 5));
  assert(window.beginAttempt(5001));
  assert(window.finishAttempt(true, 5002));
  assert(window.state() == WindowState::Paired);
  assert(!window.beginAttempt(5003));
  window.close();
  assert(window.state() == WindowState::Closed);
  std::cout << "PASS success_consumes_window\n";

  OmiPetPairing::PairingBoot pairedBoot;
  RandomSequence random{{123456U}, 1, 0};
  assert(pairedBoot.onBoot(StoredIdentityState::Present));
  assert(!pairedBoot.onBoot(StoredIdentityState::Absent));
  assert(!pairedBoot.tryOpen(0, true, true, true, nextRandomWord, &random));
  assert(random.position == 0);
  assert(pairedBoot.visibleCode() == nullptr);
  OmiPetPairing::PairingBoot unreadableIdentity;
  assert(unreadableIdentity.onBoot(StoredIdentityState::Unknown));
  assert(!unreadableIdentity.tryOpen(0, true, true, true, nextRandomWord, &random));
  std::cout << "PASS paired_or_unreadable_identity_never_opens_pairing\n";

  OmiPetPairing::PairingBoot boot;
  assert(!boot.tryOpen(0, true, true, true, nextRandomWord, &random));
  assert(boot.onBoot(StoredIdentityState::Absent));
  assert(!boot.tryOpen(0, false, true, true, nextRandomWord, &random));
  assert(!boot.tryOpen(0, true, false, true, nextRandomWord, &random));
  assert(!boot.tryOpen(0, true, true, false, nextRandomWord, &random));
  assert(random.position == 0);
  assert(boot.visibleCode() == nullptr);
  std::cout << "PASS no_code_before_security_and_display_ready\n";

  random = RandomSequence{{4294000000U, 123456U}, 2, 0};
  assert(boot.tryOpen(1000, true, true, true, nextRandomWord, &random));
  assert(random.position == 2);
  assert(std::string(boot.visibleCode()) == "123456");
  assert(!boot.tryOpen(1001, true, true, true, nextRandomWord, &random));
  assert(boot.advance(301000) == WindowState::Expired);
  assert(boot.visibleCode() == nullptr);
  assert(!boot.onBoot(StoredIdentityState::Absent));
  assert(!boot.tryOpen(301001, true, true, true, nextRandomWord, &random));
  std::cout << "PASS unpaired_reboot_opens_once_and_expiry_hides_code\n";

  OmiPetPairing::PairingBoot lockedBoot;
  assert(lockedBoot.onBoot(StoredIdentityState::Absent));
  random = RandomSequence{{654321U}, 1, 0};
  assert(lockedBoot.tryOpen(400000, true, true, true, nextRandomWord, &random));
  for (int attempt = 0; attempt < 5; ++attempt) {
    assert(lockedBoot.beginAttempt(400001 + attempt * 2));
    assert(!lockedBoot.finishAttempt(false, 400002 + attempt * 2));
  }
  assert(lockedBoot.state() == WindowState::Locked);
  assert(lockedBoot.visibleCode() == nullptr);
  assert(!lockedBoot.onBoot(StoredIdentityState::Absent));
  assert(!lockedBoot.tryOpen(400012, true, true, true, nextRandomWord, &random));
  OmiPetPairing::PairingBoot rebooted;
  assert(rebooted.onBoot(StoredIdentityState::Absent));
  random = RandomSequence{{1U}, 1, 0};
  assert(rebooted.tryOpen(0, true, true, true, nextRandomWord, &random));
  assert(std::string(rebooted.visibleCode()) == "000001");
  assert(rebooted.beginAttempt(1));
  assert(rebooted.finishAttempt(true, 2));
  assert(rebooted.visibleCode() == nullptr);
  OmiPetPairing::PairingBoot afterPairing;
  assert(afterPairing.onBoot(StoredIdentityState::Present));
  assert(!afterPairing.tryOpen(0, true, true, true, nextRandomWord, &random));
  std::cout << "PASS lock_requires_reboot_and_success_disables_future_boot\n";
}
