#include "pairing_credential_record.h"
#include "pairing_identity_state.h"
#include "pairing_nvs_store.h"

#include <nvs.h>

#include <array>
#include <cstring>
#include <iostream>
#include <vector>

namespace {
bool namespaceExists = false;
bool openFails = false;
bool readFails = false;
bool setFails = false;
bool commitFails = false;
std::vector<uint8_t> persisted;
std::vector<uint8_t> staged;
int wifiSentinel = 1234;

void resetFake() {
  namespaceExists = false;
  openFails = readFails = setFails = commitFails = false;
  persisted.clear();
  staged.clear();
}

bool allZero(const std::array<uint8_t, 32>& bytes) {
  for (const auto value : bytes) if (value != 0) return false;
  return true;
}
}

extern "C" esp_err_t nvs_open(const char* name, nvs_open_mode_t mode,
                               nvs_handle_t* handle) {
  if (std::strcmp(name, "omipet_pair") != 0 || openFails) return ESP_ERR_NVS_FAIL;
  if (!namespaceExists && mode == NVS_READONLY) return ESP_ERR_NVS_NOT_FOUND;
  namespaceExists = true;
  *handle = 1;
  return ESP_OK;
}

extern "C" esp_err_t nvs_get_blob(nvs_handle_t handle, const char* key,
                                   void* output, size_t* length) {
  if (handle != 1 || std::strcmp(key, "identity") != 0 || readFails) {
    return ESP_ERR_NVS_FAIL;
  }
  if (persisted.empty()) return ESP_ERR_NVS_NOT_FOUND;
  if (output == nullptr) {
    *length = persisted.size();
    return ESP_OK;
  }
  if (*length < persisted.size()) return ESP_ERR_NVS_FAIL;
  std::memcpy(output, persisted.data(), persisted.size());
  *length = persisted.size();
  return ESP_OK;
}

extern "C" esp_err_t nvs_set_blob(nvs_handle_t handle, const char* key,
                                   const void* value, size_t length) {
  if (handle != 1 || std::strcmp(key, "identity") != 0 || setFails) {
    return ESP_ERR_NVS_FAIL;
  }
  const auto* bytes = static_cast<const uint8_t*>(value);
  staged.assign(bytes, bytes + length);
  return ESP_OK;
}

extern "C" esp_err_t nvs_commit(nvs_handle_t handle) {
  if (handle != 1 || commitFails) return ESP_ERR_NVS_FAIL;
  persisted = staged;
  staged.clear();
  return ESP_OK;
}

extern "C" void nvs_close(nvs_handle_t handle) {
  if (handle == 1) staged.clear();
}

int main() {
  using namespace OmiPetPairing;
  std::array<uint8_t, 32> key{};
  std::array<uint8_t, 32> pin{};
  for (size_t index = 0; index < 32; ++index) {
    key[index] = static_cast<uint8_t>(index + 1);
    pin[index] = static_cast<uint8_t>(index + 64);
  }
  std::array<uint8_t, 32> loadedKey{};
  std::array<uint8_t, 32> loadedPin{};
  resetFake();
  loadedKey.fill(0xff);
  loadedPin.fill(0xff);
  if (loadPairingCredential(loadedKey.data(), loadedPin.data()) !=
          CredentialLoadState::Absent || !allZero(loadedKey) ||
      !allZero(loadedPin)) return 1;
  std::cout << "PASS missing_nvs_identity_is_absent_without_erasing_wifi\n";

  if (!savePairingCredentialOnce(key.data(), pin.data()) ||
      loadPairingCredential(loadedKey.data(), loadedPin.data()) !=
          CredentialLoadState::Present || loadedKey != key || loadedPin != pin ||
      savePairingCredentialOnce(key.data(), pin.data()) || wifiSentinel != 1234) return 1;
  std::cout << "PASS nvs_record_writes_once_and_reads_back\n";

  persisted[8] ^= 1;
  loadedKey.fill(0xff);
  loadedPin.fill(0xff);
  if (loadPairingCredential(loadedKey.data(), loadedPin.data()) !=
          CredentialLoadState::Unknown || !allZero(loadedKey) ||
      !allZero(loadedPin) || savePairingCredentialOnce(key.data(), pin.data())) return 1;
  persisted.resize(12);
  if (loadPairingCredential(loadedKey.data(), loadedPin.data()) !=
          CredentialLoadState::Unknown) return 1;
  std::cout << "PASS damaged_or_partial_nvs_record_fails_closed\n";

  resetFake();
  commitFails = true;
  if (savePairingCredentialOnce(key.data(), pin.data()) || !persisted.empty()) return 1;
  commitFails = false;
  readFails = true;
  if (loadPairingCredential(loadedKey.data(), loadedPin.data()) !=
          CredentialLoadState::Unknown ||
      savePairingCredentialOnce(key.data(), pin.data())) return 1;
  readFails = false;
  openFails = true;
  if (loadPairingCredential(loadedKey.data(), loadedPin.data()) !=
          CredentialLoadState::Unknown ||
      savePairingCredentialOnce(key.data(), pin.data())) return 1;
  std::cout << "PASS nvs_io_and_commit_failures_never_authorize\n";

  if (classifyStoredIdentity(CredentialLoadState::Absent,
                              TlsIdentityReadState::Absent, false) !=
          StoredIdentityState::Absent ||
      classifyStoredIdentity(CredentialLoadState::Present,
                              TlsIdentityReadState::Verified, true) !=
          StoredIdentityState::Present ||
      classifyStoredIdentity(CredentialLoadState::Present,
                              TlsIdentityReadState::Absent, false) !=
          StoredIdentityState::Unknown ||
      classifyStoredIdentity(CredentialLoadState::Absent,
                              TlsIdentityReadState::Verified, false) !=
          StoredIdentityState::Absent ||
      classifyStoredIdentity(CredentialLoadState::Absent,
                              TlsIdentityReadState::Unknown, false) !=
          StoredIdentityState::Unknown ||
      classifyStoredIdentity(CredentialLoadState::Present,
                              TlsIdentityReadState::Verified, false) !=
          StoredIdentityState::Unknown) return 1;
  std::cout << "PASS verified_tls_without_host_can_pair_but_damage_blocks_boot\n";
}
