#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

#include <mbedtls/platform_util.h>
#include <mbedtls/sha256.h>

#include "pairing_auth_proof.h"

namespace OmiPetPairing {

constexpr size_t kCredentialHeaderBytes = 5;
constexpr size_t kCredentialPayloadBytes = kCredentialHeaderBytes +
                                           kPairingKeyBytes + kPairingCertPinBytes;
constexpr size_t kCredentialRecordBytes = kCredentialPayloadBytes + 32;

//  摘要只检测损坏，不抵御能直接改写 Flash 的物理攻击 / The digest detects corruption; it does not prevent an attacker with physical flash access from replacing the record
inline bool encodeCredentialRecord(const uint8_t* dailyKey,
                                   const uint8_t* certPin, uint8_t* output) {
  if (dailyKey == nullptr || certPin == nullptr || output == nullptr) {
    return false;
  }
  uint8_t nonzeroKey = 0;
  uint8_t nonzeroPin = 0;
  for (size_t index = 0; index < kPairingKeyBytes; ++index) {
    nonzeroKey |= dailyKey[index];
    nonzeroPin |= certPin[index];
  }
  if (nonzeroKey == 0 || nonzeroPin == 0) return false;
  uint8_t record[kCredentialRecordBytes] = {};
  const uint8_t header[kCredentialHeaderBytes] = {'O', 'M', 'I', 'C', 1};
  std::memcpy(record, header, sizeof(header));
  std::memcpy(record + kCredentialHeaderBytes, dailyKey, kPairingKeyBytes);
  std::memcpy(record + kCredentialHeaderBytes + kPairingKeyBytes, certPin,
              kPairingCertPinBytes);
  const int result = mbedtls_sha256_ret(record, kCredentialPayloadBytes,
                                        record + kCredentialPayloadBytes, 0);
  if (result == 0) std::memcpy(output, record, sizeof(record));
  mbedtls_platform_zeroize(record, sizeof(record));
  return result == 0;
}

//  解析失败时清空输出，避免旧凭证被误当作有效 / Clear outputs on failure so stale credentials cannot be treated as valid
inline bool decodeCredentialRecord(const uint8_t* record, size_t length,
                                   uint8_t* dailyKey, uint8_t* certPin) {
  const bool shaped = record != nullptr && length == kCredentialRecordBytes &&
                      dailyKey != nullptr && certPin != nullptr &&
                      dailyKey != certPin;
  uint8_t copy[kCredentialRecordBytes] = {};
  if (shaped) std::memcpy(copy, record, sizeof(copy));
  if (dailyKey != nullptr) mbedtls_platform_zeroize(dailyKey, kPairingKeyBytes);
  if (certPin != nullptr) mbedtls_platform_zeroize(certPin,
                                                   kPairingCertPinBytes);
  if (!shaped) {
    return false;
  }
  const uint8_t header[kCredentialHeaderBytes] = {'O', 'M', 'I', 'C', 1};
  uint8_t digest[32] = {};
  const bool digestReady = mbedtls_sha256_ret(copy, kCredentialPayloadBytes,
                                              digest, 0) == 0;
  const bool digestValid = digestReady &&
      fixedTimeEqual(digest, copy + kCredentialPayloadBytes,
                     sizeof(digest));
  mbedtls_platform_zeroize(digest, sizeof(digest));
  uint8_t nonzeroKey = 0;
  uint8_t nonzeroPin = 0;
  for (size_t index = 0; index < kPairingKeyBytes; ++index) {
    nonzeroKey |= copy[kCredentialHeaderBytes + index];
    nonzeroPin |= copy[kCredentialHeaderBytes + kPairingKeyBytes + index];
  }
  const bool valid = std::memcmp(copy, header, sizeof(header)) == 0 &&
                     digestValid && nonzeroKey != 0 && nonzeroPin != 0;
  if (valid) {
    std::memcpy(dailyKey, copy + kCredentialHeaderBytes, kPairingKeyBytes);
    std::memcpy(certPin, copy + kCredentialHeaderBytes + kPairingKeyBytes,
                kPairingCertPinBytes);
  }
  mbedtls_platform_zeroize(copy, sizeof(copy));
  return valid;
}

}  //  配对命名空间 / Pairing namespace
