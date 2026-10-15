#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

#include <mbedtls/hkdf.h>
#include <mbedtls/md.h>

#include "pairing_auth_proof.h"

namespace OmiPetPairing {

//  仅在双方确认短码交换及证书指纹后，从共享秘密派生长期认证密钥 / Derive a long-term authentication key only after both peers confirm the code exchange and certificate pin
inline bool derivePairingDailyKey(const uint8_t* sharedSecret,
                                  size_t secretLength,
                                  const uint8_t* transcriptSha256,
                                  const uint8_t* certPin,
                                  uint8_t* output) {
  if (sharedSecret == nullptr || secretLength < kPairingKeyBytes ||
      transcriptSha256 == nullptr || certPin == nullptr || output == nullptr) {
    return false;
  }
  uint8_t nonzeroTranscript = 0;
  uint8_t nonzeroPin = 0;
  uint8_t nonzeroSecret = 0;
  for (size_t index = 0; index < secretLength; ++index) {
    nonzeroSecret |= sharedSecret[index];
  }
  for (size_t index = 0; index < kPairingKeyBytes; ++index) {
    nonzeroTranscript |= transcriptSha256[index];
    nonzeroPin |= certPin[index];
  }
  if (nonzeroSecret == 0 || nonzeroTranscript == 0 || nonzeroPin == 0) {
    return false;
  }
  constexpr char kInfoPrefix[] = "OmiPet daily authentication key v1";
  uint8_t info[sizeof(kInfoPrefix) - 1 + kPairingCertPinBytes] = {};
  std::memcpy(info, kInfoPrefix, sizeof(kInfoPrefix) - 1);
  std::memcpy(info + sizeof(kInfoPrefix) - 1, certPin,
              kPairingCertPinBytes);
  const mbedtls_md_info_t* sha256 = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  return sha256 != nullptr &&
         mbedtls_hkdf(sha256, transcriptSha256, kPairingKeyBytes,
                      sharedSecret, secretLength, info, sizeof(info),
                      output, kPairingKeyBytes) == 0;
}

}  //  配对命名空间 / Pairing namespace
