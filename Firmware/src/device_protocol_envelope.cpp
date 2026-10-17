#include "protocol_experiment_config.h"

#if OMIPET_PROTOCOL_EXPERIMENT
#include "device_protocol_envelope.h"
#include <cmath>
#include <cstring>
#include "cJSON.h"

namespace OmiPetProtocol {
namespace {

//  在进入 JSON 库前检查 UTF-8、控制字符和显式深度预算 / Check UTF-8, controls, and the explicit depth budget before entering the JSON library
EnvelopeResult inspectText(const char* data, std::size_t length, std::size_t maxDepth) {
  std::size_t depth = 0;
  bool quoted = false;
  bool escaped = false;
  for (std::size_t i = 0; i < length; ++i) {
    const uint8_t byte = static_cast<uint8_t>(data[i]);
    if (byte >= 0x80) {
      uint32_t code = 0;
      std::size_t count = 0;
      uint32_t minimum = 0;
      if (byte >= 0xC2 && byte <= 0xDF) { code = byte & 0x1F; count = 1; minimum = 0x80; }
      else if (byte >= 0xE0 && byte <= 0xEF) { code = byte & 0x0F; count = 2; minimum = 0x800; }
      else if (byte >= 0xF0 && byte <= 0xF4) { code = byte & 0x07; count = 3; minimum = 0x10000; }
      else return EnvelopeResult::InvalidText;
      if (count > length - i - 1) return EnvelopeResult::InvalidText;
      for (std::size_t part = 0; part < count; ++part) {
        const uint8_t continuation = static_cast<uint8_t>(data[++i]);
        if ((continuation & 0xC0) != 0x80) return EnvelopeResult::InvalidText;
        code = (code << 6) | (continuation & 0x3F);
      }
      if (code < minimum || code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF) || escaped) {
        return EnvelopeResult::InvalidText;
      }
      continue;
    }
    if (byte < 0x20 && (quoted || (byte != '\t' && byte != '\r' && byte != '\n'))) {
      return EnvelopeResult::InvalidText;
    }
    //  当前协议的数字字段只接受整数字面量，不把浮点表示隐式当作整数 / Current numeric fields require integer literals without floating-point coercion
    if (!quoted && (byte == '-' || (byte >= '0' && byte <= '9'))) {
      std::size_t end = i;
      if (data[end] == '-') ++end;
      if (end == length || data[end] < '0' || data[end] > '9') return EnvelopeResult::InvalidEnvelope;
      if (data[end] == '0') ++end;
      else while (end < length && data[end] >= '0' && data[end] <= '9') ++end;
      if (end < length && data[end] != ',' && data[end] != '}' && data[end] != ']' &&
          data[end] != ' ' && data[end] != '\t' && data[end] != '\r' && data[end] != '\n') {
        return EnvelopeResult::InvalidEnvelope;
      }
      i = end - 1;
      continue;
    }
    if (quoted) {
      if (escaped) {
        if (byte == 'u' && i + 4 < length && std::memcmp(data + i + 1, "0000", 4) == 0) {
          return EnvelopeResult::InvalidText;
        }
        escaped = false;
      } else if (byte == '\\') escaped = true;
      else if (byte == '"') quoted = false;
    } else if (byte == '"') quoted = true;
    else if (byte == '{' || byte == '[') {
      if (++depth > maxDepth) return EnvelopeResult::DepthExceeded;
    } else if (byte == '}' || byte == ']') {
      if (depth == 0) return EnvelopeResult::InvalidJson;
      --depth;
    }
  }
  return EnvelopeResult::Valid;
}

bool hasDuplicateKey(const cJSON* node) {
  for (const cJSON* child = node->child; child; child = child->next) {
    if (cJSON_IsObject(node)) {
      for (const cJSON* other = child->next; other; other = other->next) {
        if (child->string && other->string && std::strcmp(child->string, other->string) == 0) return true;
      }
    }
    if (hasDuplicateKey(child)) return true;
  }
  return false;
}

bool isToken(const cJSON* item) {
  if (!cJSON_IsString(item) || !item->valuestring || std::strlen(item->valuestring) != 32) return false;
  for (const char* p = item->valuestring; *p; ++p) {
    if (!(*p >= '0' && *p <= '9') && !(*p >= 'a' && *p <= 'f')) return false;
  }
  return true;
}

bool isUnsignedInteger(const cJSON* item, double minimum, double maximum) {
  return cJSON_IsNumber(item) && std::isfinite(item->valuedouble) &&
         item->valuedouble >= minimum && item->valuedouble <= maximum &&
         std::floor(item->valuedouble) == item->valuedouble;
}

}  //  内部命名空间 / Internal namespace

EnvelopeResult inspectEnvelope(const char* data, std::size_t length,
                               std::size_t maxDepth, EnvelopeInfo& info) {
  info = EnvelopeInfo{};
  if (!data || !length || !maxDepth) return EnvelopeResult::InvalidJson;
  const EnvelopeResult textResult = inspectText(data, length, maxDepth);
  if (textResult != EnvelopeResult::Valid) return textResult;
  const char* end = nullptr;
  cJSON* root = cJSON_ParseWithLengthOpts(data, length, &end, false);
  if (!root) return EnvelopeResult::InvalidJson;
  bool complete = end && end >= data && end <= data + length;
  if (complete) {
    for (const char* p = end; p < data + length; ++p) {
      if (*p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') complete = false;
    }
  }
  EnvelopeResult result = EnvelopeResult::InvalidEnvelope;
  if (!complete) result = EnvelopeResult::InvalidJson;
  else if (hasDuplicateKey(root)) result = EnvelopeResult::DuplicateKey;
  else if (cJSON_IsObject(root) && cJSON_GetArraySize(root) == 7) {
    const cJSON* version = cJSON_GetObjectItemCaseSensitive(root, "v");
    const cJSON* seq = cJSON_GetObjectItemCaseSensitive(root, "seq");
    const cJSON* type = cJSON_GetObjectItemCaseSensitive(root, "type");
    const cJSON* body = cJSON_GetObjectItemCaseSensitive(root, "body");
    if (isUnsignedInteger(version, 1, 1) && isUnsignedInteger(seq, 1, 4294967295.0) &&
        isToken(cJSON_GetObjectItemCaseSensitive(root, "boot")) &&
        isToken(cJSON_GetObjectItemCaseSensitive(root, "channel")) &&
        isToken(cJSON_GetObjectItemCaseSensitive(root, "session")) &&
        cJSON_IsString(type) && type->valuestring && cJSON_IsObject(body)) {
      if (std::strcmp(type->valuestring, "hello") == 0) info.type = CommandType::Hello;
      else if (std::strcmp(type->valuestring, "heartbeat") == 0) info.type = CommandType::Heartbeat;
      else if (std::strcmp(type->valuestring, "snapshot") == 0) info.type = CommandType::Snapshot;
      else if (std::strcmp(type->valuestring, "release") == 0) info.type = CommandType::Release;
#if OMIPET_DESKTOP_CONTROL
      else if (std::strcmp(type->valuestring, "light") == 0) info.type = CommandType::Light;
      else if (std::strcmp(type->valuestring, "monitorProfile") == 0) info.type = CommandType::MonitorProfile;
#endif
      if (info.type != CommandType::Unsupported) {
        info.sequence = static_cast<uint32_t>(seq->valuedouble);
        result = EnvelopeResult::Valid;
      }
    }
  }
  cJSON_Delete(root);
  if (result != EnvelopeResult::Valid) info = EnvelopeInfo{};
  return result;
}

const char* envelopeResultName(EnvelopeResult result) {
  switch (result) {
    case EnvelopeResult::Valid: return "envelope_valid";
    case EnvelopeResult::InvalidText: return "invalid_text";
    case EnvelopeResult::DepthExceeded: return "depth_exceeded";
    case EnvelopeResult::InvalidJson: return "invalid_json";
    case EnvelopeResult::DuplicateKey: return "duplicate_key";
    default: return "invalid_envelope";
  }
}

const char* commandTypeName(CommandType type) {
  switch (type) {
    case CommandType::Hello: return "hello";
    case CommandType::Heartbeat: return "heartbeat";
    case CommandType::Snapshot: return "snapshot";
    case CommandType::Release: return "release";
    case CommandType::Light: return "light";
    case CommandType::MonitorProfile: return "monitorProfile";
    default: return "unsupported";
  }
}

}  //  协议命名空间 / Protocol namespace
#endif
