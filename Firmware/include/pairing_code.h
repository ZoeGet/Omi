#pragma once

#include <cstdint>

namespace OmiPetPairing {

constexpr uint64_t kSixDigitRange = 1000000ULL;
constexpr uint64_t kRandomWordRange = uint64_t{1} << 32;
constexpr uint64_t kUnbiasedUpperBound =
    (kRandomWordRange / kSixDigitRange) * kSixDigitRange;

//  仅把一个合格的随机字映射为六位码；随机源和重试由调用方负责 / Map one accepted random word to a six-digit code; the caller supplies entropy and retries
inline bool formatSixDigitCode(uint32_t randomWord, char* output) {
  if (output == nullptr || uint64_t{randomWord} >= kUnbiasedUpperBound) return false;
  uint32_t value = randomWord % static_cast<uint32_t>(kSixDigitRange);
  for (int index = 5; index >= 0; --index) {
    output[index] = static_cast<char>('0' + value % 10U);
    value /= 10U;
  }
  output[6] = '\0';
  return true;
}

}  //  配对命名空间 / Pairing namespace
