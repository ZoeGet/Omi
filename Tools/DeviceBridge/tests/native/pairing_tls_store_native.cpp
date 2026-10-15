#include "pairing_tls_identity.h"
#include "pairing_tls_store.h"

#include <mbedtls/ctr_drbg.h>
#include <mbedtls/entropy.h>
#include <nvs.h>

#include <array>
#include <cstring>
#include <iostream>
#include <vector>

namespace {
bool exists = false;
bool commitFails = false;
std::vector<uint8_t> stored;
std::vector<uint8_t> pending;
}

extern "C" esp_err_t nvs_open(const char* name, nvs_open_mode_t mode,
                               nvs_handle_t* handle) {
  if (std::strcmp(name, "omipet_tls") != 0) return ESP_ERR_NVS_FAIL;
  if (!exists && mode == NVS_READONLY) return ESP_ERR_NVS_NOT_FOUND;
  exists = true;
  *handle = 1;
  return ESP_OK;
}

extern "C" esp_err_t nvs_get_blob(nvs_handle_t handle, const char* key,
                                   void* output, size_t* length) {
  if (handle != 1 || std::strcmp(key, "identity") != 0) {
    return ESP_ERR_NVS_FAIL;
  }
  if (stored.empty()) return ESP_ERR_NVS_NOT_FOUND;
  if (output == nullptr) {
    *length = stored.size();
    return ESP_OK;
  }
  if (*length < stored.size()) return ESP_ERR_NVS_FAIL;
  std::memcpy(output, stored.data(), stored.size());
  *length = stored.size();
  return ESP_OK;
}

extern "C" esp_err_t nvs_set_blob(nvs_handle_t handle, const char* key,
                                   const void* input, size_t length) {
  if (handle != 1 || std::strcmp(key, "identity") != 0) {
    return ESP_ERR_NVS_FAIL;
  }
  const auto* bytes = static_cast<const uint8_t*>(input);
  pending.assign(bytes, bytes + length);
  return ESP_OK;
}

extern "C" esp_err_t nvs_commit(nvs_handle_t handle) {
  if (handle != 1 || commitFails) return ESP_ERR_NVS_FAIL;
  stored = pending;
  pending.clear();
  return ESP_OK;
}

extern "C" void nvs_close(nvs_handle_t) { pending.clear(); }

int main() {
  mbedtls_entropy_context entropy;
  mbedtls_ctr_drbg_context random;
  mbedtls_entropy_init(&entropy);
  mbedtls_ctr_drbg_init(&random);
  const unsigned char label[] = "omipet-tls-store-test";
  if (mbedtls_ctr_drbg_seed(&random, mbedtls_entropy_func, &entropy,
                            label, sizeof(label) - 1) != 0) return 1;
  std::array<uint8_t, 2048> certificate{};
  std::array<uint8_t, 1024> privateKey{};
  std::array<uint8_t, 32> pin{};
  size_t certificateLength = 0;
  size_t privateKeyLength = 0;
  if (!OmiPetPairing::generateTlsIdentity(
          mbedtls_ctr_drbg_random, &random, "20260101000000", "20360101000000",
          certificate.data(), certificate.size(), &certificateLength,
          privateKey.data(), privateKey.size(), &privateKeyLength,
          pin.data())) return 1;
  std::array<uint8_t, 2048> loadedCertificate{};
  std::array<uint8_t, 1024> loadedKey{};
  std::array<uint8_t, 32> loadedPin{};
  size_t loadedCertificateLength = 0;
  size_t loadedKeyLength = 0;
  if (OmiPetPairing::loadTlsIdentity(
          loadedCertificate.data(), loadedCertificate.size(),
          &loadedCertificateLength, loadedKey.data(), loadedKey.size(),
          &loadedKeyLength, loadedPin.data()) !=
          OmiPetPairing::TlsIdentityReadState::Absent) return 1;
  std::cout << "PASS missing_tls_identity_is_absent\n";

  if (!OmiPetPairing::saveTlsIdentityOnce(certificate.data(), certificateLength,
                                          privateKey.data(), privateKeyLength,
                                          pin.data()) ||
      OmiPetPairing::saveTlsIdentityOnce(certificate.data(), certificateLength,
                                         privateKey.data(), privateKeyLength,
                                         pin.data()) ||
      OmiPetPairing::loadTlsIdentity(
          loadedCertificate.data(), loadedCertificate.size(),
          &loadedCertificateLength, loadedKey.data(), loadedKey.size(),
          &loadedKeyLength, loadedPin.data()) !=
          OmiPetPairing::TlsIdentityReadState::Verified ||
      loadedCertificateLength != certificateLength ||
      loadedKeyLength != privateKeyLength || loadedPin != pin ||
      std::memcmp(loadedCertificate.data(), certificate.data(),
                  certificateLength) != 0 ||
      std::memcmp(loadedKey.data(), privateKey.data(),
                  privateKeyLength) != 0) return 1;
  std::cout << "PASS tls_certificate_and_key_round_trip_as_one_record\n";

  stored[20] ^= 1;
  if (OmiPetPairing::loadTlsIdentity(
          loadedCertificate.data(), loadedCertificate.size(),
          &loadedCertificateLength, loadedKey.data(), loadedKey.size(),
          &loadedKeyLength, loadedPin.data()) !=
          OmiPetPairing::TlsIdentityReadState::Unknown ||
      loadedCertificateLength != 0 || loadedKeyLength != 0 ||
      loadedCertificate[0] != 0 || loadedKey[0] != 0 || loadedPin[0] != 0) return 1;
  stored.resize(16);
  if (OmiPetPairing::loadTlsIdentity(
          loadedCertificate.data(), loadedCertificate.size(),
          &loadedCertificateLength, loadedKey.data(), loadedKey.size(),
          &loadedKeyLength, loadedPin.data()) !=
          OmiPetPairing::TlsIdentityReadState::Unknown) return 1;
  std::cout << "PASS corrupted_or_partial_tls_record_fails_closed\n";

  exists = false;
  stored.clear();
  commitFails = true;
  if (OmiPetPairing::saveTlsIdentityOnce(certificate.data(), certificateLength,
                                         privateKey.data(), privateKeyLength,
                                         pin.data()) || !stored.empty()) return 1;
  std::cout << "PASS failed_tls_commit_does_not_mark_identity_verified\n";
  mbedtls_ctr_drbg_free(&random);
  mbedtls_entropy_free(&entropy);
}
