#pragma once

#include <cstdint>

#include "pairing_auth_proof.h"

namespace OmiPetPairing {

enum class CredentialLoadState { Absent, Present, Unknown };

//  只读独立命名空间；任何存储错误或损坏都返回未知并清空输出 / Read only the isolated namespace; return unknown and clear outputs on any storage error or corruption
CredentialLoadState loadPairingCredential(uint8_t* dailyKey,
                                          uint8_t* certPin);

//  首次配对成功后写入单条记录；已有记录即拒绝覆盖 / Store one record after first pairing; refuse to replace any existing record
bool savePairingCredentialOnce(const uint8_t* dailyKey,
                               const uint8_t* certPin);

}  //  配对命名空间 / Pairing namespace
