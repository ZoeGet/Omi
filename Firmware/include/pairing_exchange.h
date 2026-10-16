#pragma once

#include <cstring>
#include <mbedtls/ecjpake.h>
#include <mbedtls/sha256.h>
#include "pairing_key_derivation.h"
#include "pairing_tls_identity.h"

namespace OmiPetPairing {

constexpr size_t kPairingRoundBytes = 1024;

//  两端复用同一有序交换，错误后不可继续使用 / Both peers share this ordered exchange; errors permanently invalidate it
class PairingExchange {
 public:
  PairingExchange() { mbedtls_ecjpake_init(&pake_); }
  ~PairingExchange() { mbedtls_ecjpake_free(&pake_); }
  PairingExchange(const PairingExchange&) = delete;
  PairingExchange& operator=(const PairingExchange&) = delete;

  bool begin(bool server, const char* code, PairingRandom random, void* context) {
    if (step_ != 0 || code == nullptr || std::strlen(code) != 6 || random == nullptr) return fail();
    for (size_t i = 0; i < 6; ++i) if (code[i] < '0' || code[i] > '9') return fail();
    random_ = random;
    context_ = context;
    if (mbedtls_ecjpake_setup(&pake_, server ? MBEDTLS_ECJPAKE_SERVER : MBEDTLS_ECJPAKE_CLIENT,
        MBEDTLS_MD_SHA256, MBEDTLS_ECP_DP_SECP256R1,
        reinterpret_cast<const unsigned char*>(code), 6) != 0) return fail();
    step_ = 1;
    return true;
  }

  bool write(unsigned char* output, size_t capacity, size_t* length) {
    if (output == nullptr || length == nullptr || capacity > kPairingRoundBytes ||
        (step_ != 1 && step_ != 3)) return fail();
    const int result = step_ == 1
        ? mbedtls_ecjpake_write_round_one(&pake_, output, capacity, length, random_, context_)
        : mbedtls_ecjpake_write_round_two(&pake_, output, capacity, length, random_, context_);
    if (result != 0) return fail();
    ++step_;
    return true;
  }

  bool read(const unsigned char* input, size_t length) {
    if (input == nullptr || length == 0 || length > kPairingRoundBytes ||
        (step_ != 2 && step_ != 4)) return fail();
    const int result = step_ == 2 ? mbedtls_ecjpake_read_round_one(&pake_, input, length)
                                   : mbedtls_ecjpake_read_round_two(&pake_, input, length);
    if (result != 0) return fail();
    ++step_;
    return true;
  }

  bool derive(unsigned char* output) {
    if (step_ != 5 || output == nullptr) return fail();
    size_t length = 0;
    const int result = mbedtls_ecjpake_derive_secret(&pake_, output, 32, &length, random_, context_);
    step_ = 6;
    if (result != 0 || length != 32) {
      mbedtls_platform_zeroize(output, 32);
      return fail();
    }
    return true;
  }

 private:
  bool fail() { step_ = -1; return false; }
  mbedtls_ecjpake_context pake_;
  PairingRandom random_ = nullptr;
  void* context_ = nullptr;
  int step_ = 0;
};

//  确认证明绑定交换摘要、TLS 身份和明确角色 / Confirmation binds the exchange digest, TLS identity, and explicit role
inline bool pairingConfirmation(const uint8_t* key, char role, const uint8_t* digest,
                                 const uint8_t* pin, uint8_t* output) {
  if (!key || !digest || !pin || !output || (role != 'H' && role != 'D' && role != 'C' && role != 'S')) return false;
  constexpr char domain[] = "OmiPet pairing confirmation v1";
  uint8_t material[sizeof(domain) - 1 + 65];
  std::memcpy(material, domain, sizeof(domain) - 1);
  material[sizeof(domain) - 1] = role;
  std::memcpy(material + sizeof(domain), digest, 32);
  std::memcpy(material + sizeof(domain) + 32, pin, 32);
  return mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, 32,
                         material, sizeof(material), output) == 0;
}

}  //  配对命名空间 / Pairing namespace
