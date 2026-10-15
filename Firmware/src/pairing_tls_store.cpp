#include "pairing_tls_store.h"

#include <cstring>
#include <limits>
#include <new>

#include <mbedtls/platform_util.h>
#include <mbedtls/sha256.h>
#include <nvs.h>

#include "pairing_auth_proof.h"
#include "pairing_tls_identity.h"

namespace OmiPetPairing {
namespace {

constexpr char kNamespace[] = "omipet_tls";
constexpr char kRecordKey[] = "identity";
constexpr uint8_t kHeader[5] = {'O', 'M', 'I', 'T', 1};
constexpr size_t kPayloadHeaderBytes = sizeof(kHeader) + 8;
constexpr size_t kRecordOverheadBytes = kPayloadHeaderBytes + 32;

struct SensitiveBuffer {
  uint8_t* data;
  size_t length;
  explicit SensitiveBuffer(size_t size) : data(new (std::nothrow) uint8_t[size]()),
                                           length(size) {}
  ~SensitiveBuffer() {
    if (data != nullptr) {
      mbedtls_platform_zeroize(data, length);
      delete[] data;
    }
  }
  SensitiveBuffer(const SensitiveBuffer&) = delete;
  SensitiveBuffer& operator=(const SensitiveBuffer&) = delete;
};

void writeUint32(uint8_t* output, uint32_t value) {
  for (size_t index = 0; index < 4; ++index) {
    output[index] = static_cast<uint8_t>(value >> (8 * index));
  }
}

uint32_t readUint32(const uint8_t* input) {
  uint32_t value = 0;
  for (size_t index = 0; index < 4; ++index) {
    value |= uint32_t{input[index]} << (8 * index);
  }
  return value;
}

void clearOutputs(uint8_t* certificateDer, size_t certificateCapacity,
                  size_t* certificateLength, uint8_t* privateKeyDer,
                  size_t privateKeyCapacity, size_t* privateKeyLength,
                  uint8_t* certificatePin) {
  if (certificateDer != nullptr) {
    mbedtls_platform_zeroize(certificateDer, certificateCapacity);
  }
  if (privateKeyDer != nullptr) {
    mbedtls_platform_zeroize(privateKeyDer, privateKeyCapacity);
  }
  if (certificatePin != nullptr) {
    mbedtls_platform_zeroize(certificatePin, kPairingCertPinBytes);
  }
  if (certificateLength != nullptr) *certificateLength = 0;
  if (privateKeyLength != nullptr) *privateKeyLength = 0;
}

}  //  单条 NVS 记录辅助函数 / Single-record NVS helpers

TlsIdentityReadState loadTlsIdentity(uint8_t* certificateDer,
                                     size_t certificateCapacity,
                                     size_t* certificateLength,
                                     uint8_t* privateKeyDer,
                                     size_t privateKeyCapacity,
                                     size_t* privateKeyLength,
                                     uint8_t* certificatePin) {
  clearOutputs(certificateDer, certificateCapacity, certificateLength,
               privateKeyDer, privateKeyCapacity, privateKeyLength,
               certificatePin);
  if (certificateDer == nullptr || privateKeyDer == nullptr ||
      certificateLength == nullptr || privateKeyLength == nullptr ||
      certificatePin == nullptr || certificateCapacity == 0 ||
      privateKeyCapacity == 0 || certificateDer == privateKeyDer) {
    return TlsIdentityReadState::Unknown;
  }
  nvs_handle_t handle = 0;
  const esp_err_t opened = nvs_open(kNamespace, NVS_READONLY, &handle);
  if (opened == ESP_ERR_NVS_NOT_FOUND) return TlsIdentityReadState::Absent;
  if (opened != ESP_OK) return TlsIdentityReadState::Unknown;
  size_t length = 0;
  const esp_err_t queried = nvs_get_blob(handle, kRecordKey, nullptr,
                                         &length);
  if (queried == ESP_ERR_NVS_NOT_FOUND) {
    nvs_close(handle);
    return TlsIdentityReadState::Absent;
  }
  if (queried != ESP_OK || length < kRecordOverheadBytes ||
      certificateCapacity > std::numeric_limits<size_t>::max() -
                                kRecordOverheadBytes ||
      privateKeyCapacity > std::numeric_limits<size_t>::max() -
                                kRecordOverheadBytes - certificateCapacity) {
    nvs_close(handle);
    return TlsIdentityReadState::Unknown;
  }
  const size_t maximum = kRecordOverheadBytes + certificateCapacity +
                         privateKeyCapacity;
  if (length > maximum) {
    nvs_close(handle);
    return TlsIdentityReadState::Unknown;
  }
  SensitiveBuffer record(length);
  if (record.data == nullptr) {
    nvs_close(handle);
    return TlsIdentityReadState::Unknown;
  }
  size_t received = length;
  const esp_err_t read = nvs_get_blob(handle, kRecordKey, record.data,
                                      &received);
  nvs_close(handle);
  if (read != ESP_OK || received != length ||
      std::memcmp(record.data, kHeader, sizeof(kHeader)) != 0) {
    return TlsIdentityReadState::Unknown;
  }
  const size_t certBytes = readUint32(record.data + sizeof(kHeader));
  const size_t keyBytes = readUint32(record.data + sizeof(kHeader) + 4);
  if (certBytes == 0 || keyBytes == 0 || certBytes > certificateCapacity ||
      keyBytes > privateKeyCapacity ||
      certBytes > length - kRecordOverheadBytes ||
      keyBytes != length - kRecordOverheadBytes - certBytes) {
    return TlsIdentityReadState::Unknown;
  }
  uint8_t digest[32] = {};
  const size_t payloadBytes = length - sizeof(digest);
  const bool digestReady = mbedtls_sha256_ret(record.data, payloadBytes,
                                               digest, 0) == 0;
  const bool digestValid = digestReady && fixedTimeEqual(
      digest, record.data + payloadBytes, sizeof(digest));
  mbedtls_platform_zeroize(digest, sizeof(digest));
  if (!digestValid) return TlsIdentityReadState::Unknown;
  std::memcpy(certificateDer, record.data + kPayloadHeaderBytes, certBytes);
  std::memcpy(privateKeyDer, record.data + kPayloadHeaderBytes + certBytes,
              keyBytes);
  if (mbedtls_sha256_ret(certificateDer, certBytes, certificatePin, 0) != 0 ||
      !verifyTlsIdentity(certificateDer, certBytes, privateKeyDer,
                          keyBytes, certificatePin)) {
    clearOutputs(certificateDer, certificateCapacity, certificateLength,
                 privateKeyDer, privateKeyCapacity, privateKeyLength,
                 certificatePin);
    return TlsIdentityReadState::Unknown;
  }
  *certificateLength = certBytes;
  *privateKeyLength = keyBytes;
  return TlsIdentityReadState::Verified;
}

bool saveTlsIdentityOnce(const uint8_t* certificateDer,
                         size_t certificateLength,
                         const uint8_t* privateKeyDer,
                         size_t privateKeyLength,
                         const uint8_t* certificatePin) {
  if (certificateLength > UINT32_MAX || privateKeyLength > UINT32_MAX ||
      certificateLength > std::numeric_limits<size_t>::max() -
                              kRecordOverheadBytes ||
      privateKeyLength > std::numeric_limits<size_t>::max() -
                             kRecordOverheadBytes - certificateLength ||
      !verifyTlsIdentity(certificateDer, certificateLength, privateKeyDer,
                          privateKeyLength, certificatePin)) {
    return false;
  }
  const size_t length = kRecordOverheadBytes + certificateLength +
                        privateKeyLength;
  SensitiveBuffer record(length);
  if (record.data == nullptr) return false;
  std::memcpy(record.data, kHeader, sizeof(kHeader));
  writeUint32(record.data + sizeof(kHeader),
              static_cast<uint32_t>(certificateLength));
  writeUint32(record.data + sizeof(kHeader) + 4,
              static_cast<uint32_t>(privateKeyLength));
  std::memcpy(record.data + kPayloadHeaderBytes, certificateDer,
              certificateLength);
  std::memcpy(record.data + kPayloadHeaderBytes + certificateLength,
              privateKeyDer, privateKeyLength);
  if (mbedtls_sha256_ret(record.data, length - 32,
                          record.data + length - 32, 0) != 0) return false;
  nvs_handle_t handle = 0;
  if (nvs_open(kNamespace, NVS_READWRITE, &handle) != ESP_OK) return false;
  size_t existingLength = 0;
  const esp_err_t existing = nvs_get_blob(handle, kRecordKey, nullptr,
                                          &existingLength);
  bool saved = false;
  if (existing == ESP_ERR_NVS_NOT_FOUND &&
      nvs_set_blob(handle, kRecordKey, record.data, length) == ESP_OK &&
      nvs_commit(handle) == ESP_OK) {
    SensitiveBuffer confirmed(length);
    if (confirmed.data != nullptr) {
      size_t readLength = length;
      saved = nvs_get_blob(handle, kRecordKey, confirmed.data,
                            &readLength) == ESP_OK &&
              readLength == length &&
              std::memcmp(record.data, confirmed.data, length) == 0;
    }
  }
  nvs_close(handle);
  return saved;
}

}  //  配对命名空间 / Pairing namespace
