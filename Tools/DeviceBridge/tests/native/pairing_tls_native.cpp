#include "pairing_tls_identity.h"

#include <mbedtls/ctr_drbg.h>
#include <mbedtls/entropy.h>

#include <array>
#include <iostream>

int main() {
  mbedtls_entropy_context entropy;
  mbedtls_ctr_drbg_context random;
  mbedtls_entropy_init(&entropy);
  mbedtls_ctr_drbg_init(&random);
  const unsigned char label[] = "omipet-tls-identity-test";
  if (mbedtls_ctr_drbg_seed(&random, mbedtls_entropy_func, &entropy,
                            label, sizeof(label) - 1) != 0) return 1;
  std::array<uint8_t, 2048> certificate{};
  std::array<uint8_t, 1024> privateKey{};
  std::array<uint8_t, 32> pin{};
  size_t certificateLength = 0;
  size_t privateKeyLength = 0;
  const bool created = OmiPetPairing::generateTlsIdentity(
      mbedtls_ctr_drbg_random, &random, "20260101000000", "20360101000000",
      certificate.data(), certificate.size(), &certificateLength,
      privateKey.data(), privateKey.size(), &privateKeyLength, pin.data());
  if (!created || certificateLength == 0 || privateKeyLength == 0 ||
      !OmiPetPairing::verifyTlsIdentity(certificate.data(), certificateLength,
                                        privateKey.data(), privateKeyLength,
                                        pin.data())) return 1;
  std::cout << "PASS generated_ecdsa_identity_parses_and_matches_pin\n";

  pin[0] ^= 1;
  if (OmiPetPairing::verifyTlsIdentity(certificate.data(), certificateLength,
                                       privateKey.data(), privateKeyLength,
                                       pin.data())) return 1;
  pin[0] ^= 1;
  certificate[10] ^= 1;
  if (OmiPetPairing::verifyTlsIdentity(certificate.data(), certificateLength,
                                       privateKey.data(), privateKeyLength,
                                       pin.data())) return 1;
  certificate[10] ^= 1;
  privateKey[privateKeyLength / 2] ^= 1;
  if (OmiPetPairing::verifyTlsIdentity(certificate.data(), certificateLength,
                                       privateKey.data(), privateKeyLength,
                                       pin.data())) return 1;
  std::cout << "PASS mutated_certificate_pin_or_private_key_is_rejected\n";

  certificate.fill(0xaa);
  privateKey.fill(0xaa);
  pin.fill(0xaa);
  certificateLength = 9;
  privateKeyLength = 9;
  const bool shortBuffer = OmiPetPairing::generateTlsIdentity(
      mbedtls_ctr_drbg_random, &random, "20260101000000", "20360101000000",
      certificate.data(), 8, &certificateLength,
      privateKey.data(), 8, &privateKeyLength, pin.data());
  if (shortBuffer || certificateLength != 0 || privateKeyLength != 0) return 1;
  for (size_t index = 0; index < 8; ++index) {
    if (certificate[index] != 0 || privateKey[index] != 0) return 1;
  }
  for (const auto value : pin) if (value != 0) return 1;
  certificate.fill(0xaa);
  privateKey.fill(0xaa);
  pin.fill(0xaa);
  certificateLength = 9;
  privateKeyLength = 9;
  if (OmiPetPairing::generateTlsIdentity(
          nullptr, &random, "20260101000000", "20360101000000",
          certificate.data(), certificate.size(), &certificateLength,
          privateKey.data(), privateKey.size(), &privateKeyLength,
          pin.data()) || certificateLength != 0 || privateKeyLength != 0) {
    return 1;
  }
  for (const auto value : certificate) if (value != 0) return 1;
  for (const auto value : privateKey) if (value != 0) return 1;
  for (const auto value : pin) if (value != 0) return 1;
  std::cout << "PASS insufficient_buffers_fail_without_partial_identity\n";
  mbedtls_ctr_drbg_free(&random);
  mbedtls_entropy_free(&entropy);
}
