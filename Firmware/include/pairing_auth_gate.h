#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

#include <mbedtls/platform_util.h>

#include "pairing_auth_proof.h"

namespace OmiPetPairing {

//  每条 TLS 连接独立持有认证状态；调用方仍须生成新随机数并在放行协议前检查 authorized / Keep authentication state per TLS connection; the adapter must supply a fresh nonce and check authorized before accepting protocol messages
class PairingAuthGate {
 public:
  PairingAuthGate() = default;
  PairingAuthGate(const PairingAuthGate&) = delete;
  PairingAuthGate& operator=(const PairingAuthGate&) = delete;
  ~PairingAuthGate() { reset(); }

  bool begin(bool tlsReady, const uint8_t* key, const uint8_t* certPin,
             const uint8_t* freshDeviceNonce) {
    reset();
    if (!tlsReady || key == nullptr || certPin == nullptr ||
        freshDeviceNonce == nullptr || !hasNonzero(key) ||
        !hasNonzero(certPin) || !hasNonzero(freshDeviceNonce)) {
      return false;
    }
    std::memcpy(key_, key, kPairingKeyBytes);
    std::memcpy(certPin_, certPin, kPairingCertPinBytes);
    std::memcpy(deviceNonce_, freshDeviceNonce, kPairingNonceBytes);
    challengeReady_ = true;
    return true;
  }

  bool finish(const uint8_t* hostNonce, const uint8_t* hostProof,
              size_t proofLength, uint8_t* deviceProof) {
    if (!challengeReady_ || authenticated_ || hostNonce == nullptr ||
        deviceProof == nullptr || !hasNonzero(hostNonce) ||
        !verifyPairingAuthProof(key_, sizeof(key_), ProofRole::Host,
                                deviceNonce_, hostNonce, certPin_,
                                hostProof, proofLength)) {
      reset();
      return false;
    }
    if (!makePairingAuthProof(key_, sizeof(key_), ProofRole::Device,
                              deviceNonce_, hostNonce, certPin_, deviceProof)) {
      mbedtls_platform_zeroize(deviceProof, kPairingProofBytes);
      reset();
      return false;
    }
    authenticated_ = true;
    return true;
  }

  bool authorized() const { return challengeReady_ && authenticated_; }

  void reset() {
    mbedtls_platform_zeroize(key_, sizeof(key_));
    mbedtls_platform_zeroize(certPin_, sizeof(certPin_));
    mbedtls_platform_zeroize(deviceNonce_, sizeof(deviceNonce_));
    challengeReady_ = false;
    authenticated_ = false;
  }

 private:
  static bool hasNonzero(const uint8_t* bytes) {
    uint8_t nonzero = 0;
    for (size_t index = 0; index < kPairingKeyBytes; ++index) {
      nonzero |= bytes[index];
    }
    return nonzero != 0;
  }

  uint8_t key_[kPairingKeyBytes] = {};
  uint8_t certPin_[kPairingCertPinBytes] = {};
  uint8_t deviceNonce_[kPairingNonceBytes] = {};
  bool challengeReady_ = false;
  bool authenticated_ = false;
};

}  //  配对命名空间 / Pairing namespace
