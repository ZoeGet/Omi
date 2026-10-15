#pragma once

#include <cstddef>
#include <cstdint>

namespace OmiPetPairing {

enum class TlsIdentityReadState { Absent, Verified, Unknown };

//  输出缓冲容量由调用方明确给出；缺失、损坏及读错必须区分 / Caller supplies output capacities; distinguish missing identity from damage or read failures
TlsIdentityReadState loadTlsIdentity(uint8_t* certificateDer,
                                     size_t certificateCapacity,
                                     size_t* certificateLength,
                                     uint8_t* privateKeyDer,
                                     size_t privateKeyCapacity,
                                     size_t* privateKeyLength,
                                     uint8_t* certificatePin);

//  一次写入经校验的证书与私钥，已有记录不能覆盖 / Store one validated certificate-and-key record and never overwrite an existing record
bool saveTlsIdentityOnce(const uint8_t* certificateDer,
                         size_t certificateLength,
                         const uint8_t* privateKeyDer,
                         size_t privateKeyLength,
                         const uint8_t* certificatePin);

}  //  配对命名空间 / Pairing namespace
