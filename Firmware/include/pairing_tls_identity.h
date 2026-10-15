#pragma once

#include <cstddef>
#include <cstdint>

namespace OmiPetPairing {

using PairingRandom = int (*)(void* context, unsigned char* output,
                              size_t length);

//  仅在可信随机源就绪时生成设备 ECDSA 身份；有效期和缓冲容量由调用方显式提供 / Generate an ECDSA device identity only with a ready trusted RNG; the caller supplies validity and buffer capacities
bool generateTlsIdentity(PairingRandom random, void* randomContext,
                         const char* notBeforeUtc, const char* notAfterUtc,
                         uint8_t* certificateDer, size_t certificateCapacity,
                         size_t* certificateLength, uint8_t* privateKeyDer,
                         size_t privateKeyCapacity, size_t* privateKeyLength,
                         uint8_t* certificatePin);

//  校验 DER 证书、私钥、公私钥配对及完整证书指纹 / Validate DER certificate, private key, matching public key, and full-certificate digest
bool verifyTlsIdentity(const uint8_t* certificateDer,
                       size_t certificateLength,
                       const uint8_t* privateKeyDer, size_t privateKeyLength,
                       const uint8_t* certificatePin);

}  //  配对命名空间 / Pairing namespace
