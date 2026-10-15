#include "pairing_tls_identity.h"

#include <cstring>

#include <mbedtls/ecp.h>
#include <mbedtls/pk.h>
#include <mbedtls/platform_util.h>
#include <mbedtls/sha256.h>
#include <mbedtls/x509_crt.h>

#include "pairing_auth_proof.h"

namespace OmiPetPairing {
namespace {

struct IdentityContexts {
  mbedtls_pk_context key;
  mbedtls_x509write_cert writer;
  mbedtls_mpi serial;

  IdentityContexts() {
    mbedtls_pk_init(&key);
    mbedtls_x509write_crt_init(&writer);
    mbedtls_mpi_init(&serial);
  }

  ~IdentityContexts() {
    mbedtls_mpi_free(&serial);
    mbedtls_x509write_crt_free(&writer);
    mbedtls_pk_free(&key);
  }
};

}  //  临时密码上下文 / Temporary cryptographic contexts

bool generateTlsIdentity(PairingRandom random, void* randomContext,
                         const char* notBeforeUtc, const char* notAfterUtc,
                         uint8_t* certificateDer, size_t certificateCapacity,
                         size_t* certificateLength, uint8_t* privateKeyDer,
                         size_t privateKeyCapacity, size_t* privateKeyLength,
                         uint8_t* certificatePin) {
  if (certificateLength != nullptr) *certificateLength = 0;
  if (privateKeyLength != nullptr) *privateKeyLength = 0;
  if (certificateDer != nullptr) {
    mbedtls_platform_zeroize(certificateDer, certificateCapacity);
  }
  if (privateKeyDer != nullptr) {
    mbedtls_platform_zeroize(privateKeyDer, privateKeyCapacity);
  }
  if (certificatePin != nullptr) {
    mbedtls_platform_zeroize(certificatePin, kPairingCertPinBytes);
  }
  if (certificateDer == nullptr || privateKeyDer == nullptr ||
      certificatePin == nullptr || random == nullptr ||
      notBeforeUtc == nullptr || notAfterUtc == nullptr ||
      certificateLength == nullptr || privateKeyLength == nullptr ||
      certificateCapacity == 0 || privateKeyCapacity == 0 ||
      certificateDer == privateKeyDer) {
    return false;
  }
  IdentityContexts context;
  uint8_t serialBytes[16] = {};
  bool generated = false;
  do {
    const mbedtls_pk_info_t* ecInfo = mbedtls_pk_info_from_type(MBEDTLS_PK_ECKEY);
    if (ecInfo == nullptr || mbedtls_pk_setup(&context.key, ecInfo) != 0) break;
    if (mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1,
                            mbedtls_pk_ec(context.key), random,
                            randomContext) != 0) break;
    if (random(randomContext, serialBytes, sizeof(serialBytes)) != 0) break;
    serialBytes[sizeof(serialBytes) - 1] |= 1U;
    if (mbedtls_mpi_read_binary(&context.serial, serialBytes,
                                sizeof(serialBytes)) != 0) break;
    mbedtls_x509write_crt_set_md_alg(&context.writer, MBEDTLS_MD_SHA256);
    mbedtls_x509write_crt_set_subject_key(&context.writer, &context.key);
    mbedtls_x509write_crt_set_issuer_key(&context.writer, &context.key);
    if (mbedtls_x509write_crt_set_subject_name(&context.writer,
                                                "CN=OmiPet Device") != 0 ||
        mbedtls_x509write_crt_set_issuer_name(&context.writer,
                                               "CN=OmiPet Device") != 0 ||
        mbedtls_x509write_crt_set_serial(&context.writer,
                                         &context.serial) != 0 ||
        mbedtls_x509write_crt_set_validity(&context.writer, notBeforeUtc,
                                           notAfterUtc) != 0 ||
        mbedtls_x509write_crt_set_basic_constraints(&context.writer, 0,
                                                     -1) != 0 ||
        mbedtls_x509write_crt_set_key_usage(&context.writer,
                                            MBEDTLS_X509_KU_DIGITAL_SIGNATURE) != 0) {
      break;
    }
    const int keyBytes = mbedtls_pk_write_key_der(&context.key,
                                                  privateKeyDer,
                                                  privateKeyCapacity);
    if (keyBytes <= 0) break;
    const int certBytes = mbedtls_x509write_crt_der(&context.writer,
                                                    certificateDer,
                                                    certificateCapacity,
                                                    random, randomContext);
    if (certBytes <= 0) break;
    const size_t keySize = static_cast<size_t>(keyBytes);
    const size_t certSize = static_cast<size_t>(certBytes);
    std::memmove(privateKeyDer, privateKeyDer + privateKeyCapacity - keySize,
                 keySize);
    std::memmove(certificateDer,
                 certificateDer + certificateCapacity - certSize, certSize);
    mbedtls_platform_zeroize(privateKeyDer + keySize,
                              privateKeyCapacity - keySize);
    mbedtls_platform_zeroize(certificateDer + certSize,
                              certificateCapacity - certSize);
    if (mbedtls_sha256_ret(certificateDer, certSize, certificatePin, 0) != 0) {
      break;
    }
    *certificateLength = certSize;
    *privateKeyLength = keySize;
    generated = true;
  } while (false);
  mbedtls_platform_zeroize(serialBytes, sizeof(serialBytes));
  if (!generated) {
    mbedtls_platform_zeroize(certificateDer, certificateCapacity);
    mbedtls_platform_zeroize(privateKeyDer, privateKeyCapacity);
    mbedtls_platform_zeroize(certificatePin, kPairingCertPinBytes);
  }
  return generated;
}

bool verifyTlsIdentity(const uint8_t* certificateDer,
                       size_t certificateLength,
                       const uint8_t* privateKeyDer, size_t privateKeyLength,
                       const uint8_t* certificatePin) {
  if (certificateDer == nullptr || privateKeyDer == nullptr ||
      certificatePin == nullptr || certificateLength == 0 ||
      privateKeyLength == 0) return false;
  uint8_t digest[kPairingCertPinBytes] = {};
  const bool digestReady = mbedtls_sha256_ret(certificateDer,
                                               certificateLength,
                                               digest, 0) == 0;
  const bool pinMatches = digestReady && fixedTimeEqual(
      digest, certificatePin, sizeof(digest));
  mbedtls_platform_zeroize(digest, sizeof(digest));
  if (!pinMatches) return false;
  mbedtls_x509_crt certificate;
  mbedtls_pk_context privateKey;
  mbedtls_x509_crt_init(&certificate);
  mbedtls_pk_init(&privateKey);
  const bool valid = mbedtls_x509_crt_parse_der(&certificate, certificateDer,
                                                certificateLength) == 0 &&
                     certificate.raw.len == certificateLength &&
                     mbedtls_pk_parse_key(&privateKey, privateKeyDer,
                                           privateKeyLength, nullptr, 0) == 0 &&
                     mbedtls_pk_can_do(&certificate.pk, MBEDTLS_PK_ECKEY) &&
                     mbedtls_pk_check_pair(&certificate.pk, &privateKey) == 0;
  mbedtls_pk_free(&privateKey);
  mbedtls_x509_crt_free(&certificate);
  return valid;
}

}  //  配对命名空间 / Pairing namespace
