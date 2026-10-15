#pragma once

#include "pairing_boot.h"
#include "pairing_nvs_store.h"
#include "pairing_tls_store.h"

namespace OmiPetPairing {

//  无电脑凭证且 TLS 身份缺失或完整时仍可配对；损坏、孤立凭证及指纹不符保持未知 / With no host credential, an absent or verified TLS identity remains unpaired; damage, orphaned credentials, or a pin mismatch remains unknown
inline StoredIdentityState classifyStoredIdentity(
    CredentialLoadState credential, TlsIdentityReadState tlsIdentity,
    bool certificatePinMatches) {
  if (credential == CredentialLoadState::Absent &&
      (tlsIdentity == TlsIdentityReadState::Absent ||
       tlsIdentity == TlsIdentityReadState::Verified)) {
    return StoredIdentityState::Absent;
  }
  if (credential == CredentialLoadState::Present &&
      tlsIdentity == TlsIdentityReadState::Verified &&
      certificatePinMatches) {
    return StoredIdentityState::Present;
  }
  return StoredIdentityState::Unknown;
}

}  //  配对命名空间 / Pairing namespace
