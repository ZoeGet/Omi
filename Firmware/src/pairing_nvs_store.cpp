#include "pairing_nvs_store.h"

#include <cstddef>
#include <cstring>

#include <mbedtls/platform_util.h>
#include <nvs.h>

#include "pairing_credential_record.h"

namespace OmiPetPairing {
namespace {

constexpr char kNamespace[] = "omipet_pair";
constexpr char kRecordKey[] = "identity";

}  //  本地存储常量 / Local storage constants

CredentialLoadState loadPairingCredential(uint8_t* dailyKey,
                                          uint8_t* certPin) {
  if (dailyKey != nullptr) mbedtls_platform_zeroize(dailyKey, kPairingKeyBytes);
  if (certPin != nullptr) mbedtls_platform_zeroize(certPin, kPairingCertPinBytes);
  if (dailyKey == nullptr || certPin == nullptr || dailyKey == certPin) {
    return CredentialLoadState::Unknown;
  }
  nvs_handle_t handle = 0;
  const esp_err_t opened = nvs_open(kNamespace, NVS_READONLY, &handle);
  if (opened == ESP_ERR_NVS_NOT_FOUND) return CredentialLoadState::Absent;
  if (opened != ESP_OK) return CredentialLoadState::Unknown;
  size_t length = 0;
  esp_err_t result = nvs_get_blob(handle, kRecordKey, nullptr, &length);
  if (result == ESP_ERR_NVS_NOT_FOUND) {
    nvs_close(handle);
    return CredentialLoadState::Absent;
  }
  if (result != ESP_OK || length != kCredentialRecordBytes) {
    nvs_close(handle);
    return CredentialLoadState::Unknown;
  }
  uint8_t record[kCredentialRecordBytes] = {};
  result = nvs_get_blob(handle, kRecordKey, record, &length);
  nvs_close(handle);
  const bool valid = result == ESP_OK && length == sizeof(record) &&
                     decodeCredentialRecord(record, length, dailyKey,
                                            certPin);
  mbedtls_platform_zeroize(record, sizeof(record));
  return valid ? CredentialLoadState::Present : CredentialLoadState::Unknown;
}

bool savePairingCredentialOnce(const uint8_t* dailyKey,
                               const uint8_t* certPin) {
  uint8_t record[kCredentialRecordBytes] = {};
  if (!encodeCredentialRecord(dailyKey, certPin, record)) return false;
  nvs_handle_t handle = 0;
  if (nvs_open(kNamespace, NVS_READWRITE, &handle) != ESP_OK) {
    mbedtls_platform_zeroize(record, sizeof(record));
    return false;
  }
  size_t length = 0;
  const esp_err_t existing = nvs_get_blob(handle, kRecordKey, nullptr,
                                          &length);
  bool stored = false;
  if (existing == ESP_ERR_NVS_NOT_FOUND &&
      nvs_set_blob(handle, kRecordKey, record, sizeof(record)) == ESP_OK &&
      nvs_commit(handle) == ESP_OK) {
    uint8_t confirmed[kCredentialRecordBytes] = {};
    length = sizeof(confirmed);
    const esp_err_t readback = nvs_get_blob(handle, kRecordKey, confirmed,
                                            &length);
    stored = readback == ESP_OK && length == sizeof(confirmed) &&
             std::memcmp(record, confirmed, sizeof(record)) == 0;
    mbedtls_platform_zeroize(confirmed, sizeof(confirmed));
  }
  nvs_close(handle);
  mbedtls_platform_zeroize(record, sizeof(record));
  return stored;
}

}  //  配对命名空间 / Pairing namespace
