#pragma once

#include <cstddef>
#include <cstdint>

namespace OmiPetProtocol {

//  此阶段只诊断信封，不授权或执行任何设备命令 / This stage diagnoses envelopes without authorizing or executing device commands
enum class EnvelopeResult { Valid, InvalidText, DepthExceeded, InvalidJson, DuplicateKey, InvalidEnvelope };
enum class CommandType { Hello, Heartbeat, Snapshot, Release, Light, Unsupported };

struct EnvelopeInfo {
  CommandType type = CommandType::Unsupported;
  uint32_t sequence = 0;
};

EnvelopeResult inspectEnvelope(const char* data, std::size_t length,
                               std::size_t maxDepth, EnvelopeInfo& info);
const char* envelopeResultName(EnvelopeResult result);
const char* commandTypeName(CommandType type);

}  //  协议命名空间 / Protocol namespace
