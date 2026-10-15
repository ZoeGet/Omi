#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

#include <mbedtls/md.h>
#include <mbedtls/platform_util.h>

namespace OmiPetPairing {

constexpr size_t kPairingKeyBytes = 32;
constexpr size_t kPairingNonceBytes = 32;
constexpr size_t kPairingCertPinBytes = 32;
constexpr size_t kPairingProofBytes = 32;

enum class ProofRole : uint8_t { Host = 'H', Device = 'D' };

//  固定长度逐字节比较，不按首个差异提前退出 / Compare every byte of a fixed-length value without exiting on the first mismatch
inline bool fixedTimeEqual(const uint8_t* left, const uint8_t* right,
                           size_t length) {
  if (left == nullptr || right == nullptr) return false;
  volatile uint8_t difference = 0;
  for (size_t index = 0; index < length; ++index) {
    difference = static_cast<uint8_t>(difference | (left[index] ^ right[index]));
  }
  return difference == 0;
}

//  将角色、双方新随机数和已固定的设备证书指纹绑定到 HMAC 证明 / Bind the role, both fresh nonces, and the pinned device-certificate digest into an HMAC proof
inline bool makePairingAuthProof(const uint8_t* key, size_t keyLength,
                                ProofRole role, const uint8_t* deviceNonce,
                                const uint8_t* hostNonce, const uint8_t* certPin,
                                uint8_t* output) {
  if (key == nullptr || keyLength != kPairingKeyBytes ||
      deviceNonce == nullptr || hostNonce == nullptr || certPin == nullptr ||
      output == nullptr) return false;
  uint8_t nonzero = 0;
  for (size_t index = 0; index < keyLength; ++index) nonzero |= key[index];
  if (nonzero == 0) return false;
  nonzero = 0;
  for (size_t index = 0; index < kPairingCertPinBytes; ++index) {
    nonzero |= certPin[index];
  }
  if (nonzero == 0) return false;
  const auto roleByte = static_cast<uint8_t>(role);
  if (roleByte != 'H' && roleByte != 'D') return false;

  constexpr char kDomain[] = "OmiPet LAN authentication v1";
  uint8_t transcript[sizeof(kDomain) - 1 + 1 + 3 * kPairingNonceBytes] = {};
  size_t offset = 0;
  std::memcpy(transcript + offset, kDomain, sizeof(kDomain) - 1);
  offset += sizeof(kDomain) - 1;
  transcript[offset++] = roleByte;
  std::memcpy(transcript + offset, deviceNonce, kPairingNonceBytes);
  offset += kPairingNonceBytes;
  std::memcpy(transcript + offset, hostNonce, kPairingNonceBytes);
  offset += kPairingNonceBytes;
  std::memcpy(transcript + offset, certPin, kPairingCertPinBytes);
  offset += kPairingCertPinBytes;
  const mbedtls_md_info_t* sha256 = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (sha256 == nullptr) return false;
  return mbedtls_md_hmac(sha256, key, keyLength, transcript, offset,
                         output) == 0;
}

//  比较固定长度证明时使用恒定时间比较，并清除临时证明 / Compare fixed-length proofs in constant time and clear the temporary proof
inline bool verifyPairingAuthProof(const uint8_t* key, size_t keyLength,
                                  ProofRole role, const uint8_t* deviceNonce,
                                  const uint8_t* hostNonce,
                                  const uint8_t* certPin,
                                  const uint8_t* receivedProof,
                                  size_t receivedLength) {
  if (receivedProof == nullptr || receivedLength != kPairingProofBytes) {
    return false;
  }
  uint8_t expected[kPairingProofBytes] = {};
  const bool generated = makePairingAuthProof(key, keyLength, role,
                                               deviceNonce, hostNonce,
                                               certPin, expected);
  const bool matched = generated && fixedTimeEqual(expected, receivedProof,
                                                    kPairingProofBytes);
  mbedtls_platform_zeroize(expected, sizeof(expected));
  return matched;
}

}  //  配对命名空间 / Pairing namespace
