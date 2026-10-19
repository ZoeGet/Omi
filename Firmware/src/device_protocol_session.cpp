#include "protocol_experiment_config.h"

#if OMIPET_PROTOCOL_EXPERIMENT
#include "device_protocol_session.h"
#include "monitor_light_profiles.h"
#include "device_protocol_envelope.h"
#include "cJSON.h"
#include <climits>
#include <cmath>
#include <cstring>
#include <initializer_list>

namespace OmiPetProtocol {
namespace {
const char* const kStatuses[] = {"waitingApproval", "working", "unknown", "idle", "offline"};
const char* const kHosts[] = {"running", "exited", "identityMismatch", "unknown", "unverified"};

const cJSON* field(const cJSON* object, const char* name) {
  return cJSON_GetObjectItemCaseSensitive(object, name);
}

bool equalText(const cJSON* node, const char* text) {
  return cJSON_IsString(node) && node->valuestring && std::strcmp(node->valuestring, text) == 0;
}

bool validToken(const char* text) {
  if (!text || std::strlen(text) != 32) return false;
  for (const char* p = text; *p; ++p) {
    if (!(*p >= '0' && *p <= '9') && !(*p >= 'a' && *p <= 'f')) return false;
  }
  return true;
}

bool unsignedNumber(const cJSON* node, uint32_t minimum, uint32_t& value) {
  if (!cJSON_IsNumber(node) || !std::isfinite(node->valuedouble) ||
      node->valuedouble < minimum || node->valuedouble > UINT32_MAX ||
      std::floor(node->valuedouble) != node->valuedouble) return false;
  value = static_cast<uint32_t>(node->valuedouble);
  return true;
}

bool fields(const cJSON* object, const char* const* names, std::size_t count) {
  if (!cJSON_IsObject(object) || static_cast<std::size_t>(cJSON_GetArraySize(object)) != count) return false;
  for (std::size_t i = 0; i < count; ++i) if (!field(object, names[i])) return false;
  return true;
}

int choice(const cJSON* node, const char* const* values, std::size_t count) {
  for (std::size_t i = 0; i < count; ++i) if (equalText(node, values[i])) return static_cast<int>(i);
  return -1;
}

#if OMIPET_DESKTOP_CONTROL
const char* localLight(const cJSON* body, LocalLightCommand& command) {
  const char* const names[] = {"effect", "red", "green", "blue", "brightness"};
  const char* const effects[] = {"solid", "rainbow", "breathe", "sweep", "centerExpand", "off"};
  if (!fields(body, names, 5)) return "invalid-light-fields";
  const int effect = choice(field(body, "effect"), effects, 6);
  uint32_t red = 0, green = 0, blue = 0, brightness = 0;
  if (effect < 0 || !unsignedNumber(field(body, "red"), 0, red) || red > 255 ||
      !unsignedNumber(field(body, "green"), 0, green) || green > 255 ||
      !unsignedNumber(field(body, "blue"), 0, blue) || blue > 255 ||
      !unsignedNumber(field(body, "brightness"), 0, brightness) || brightness > 255) {
    return "invalid-light-setting";
  }
  command.effect = static_cast<LocalLightEffect>(effect);
  command.red = static_cast<uint8_t>(red);
  command.green = static_cast<uint8_t>(green);
  command.blue = static_cast<uint8_t>(blue);
  command.brightness = static_cast<uint8_t>(brightness);
  return nullptr;
}
#endif

bool alias(const cJSON* node) {
  if (!cJSON_IsString(node) || !node->valuestring) return false;
  const char* text = node->valuestring;
  if (text[0] != 's' || text[1] < '1' || text[1] > '9') return false;
  for (const char* p = text + 2; *p; ++p) if (*p < '0' || *p > '9') return false;
  return true;
}

//  保留整数字面量，防止 cJSON 的 double 舍入让不同请求误判为重复 / Preserve integer literals so cJSON double rounding cannot equate distinct requests
bool retainIntegers(cJSON* node, const char* raw, std::size_t length, std::size_t& cursor) {
  if (cJSON_IsNumber(node)) {
    bool quoted = false, escaped = false;
    while (cursor < length) {
      const char byte = raw[cursor];
      if (!quoted && (byte == '-' || (byte >= '0' && byte <= '9'))) break;
      if (quoted) {
        if (escaped) escaped = false;
        else if (byte == '\\') escaped = true;
        else if (byte == '"') quoted = false;
      } else if (byte == '"') quoted = true;
      ++cursor;
    }
    const std::size_t start = cursor;
    if (cursor < length && raw[cursor] == '-') ++cursor;
    while (cursor < length && raw[cursor] >= '0' && raw[cursor] <= '9') ++cursor;
    if (cursor == start) return false;
    const bool negativeZero = cursor - start == 2 && raw[start] == '-' && raw[start + 1] == '0';
    const std::size_t count = negativeZero ? 1 : cursor - start;
    node->valuestring = static_cast<char*>(cJSON_malloc(count + 1));
    if (!node->valuestring) return false;
    std::memcpy(node->valuestring, raw + start + (negativeZero ? 1 : 0), count);
    node->valuestring[count] = '\0';
  }
  for (cJSON* child = node->child; child; child = child->next) {
    if (!retainIntegers(child, raw, length, cursor)) return false;
  }
  return true;
}

bool sameRequest(const cJSON* left, const cJSON* right) {
  if (!left || !right || (left->type & 255) != (right->type & 255)) return false;
  if (cJSON_IsNumber(left)) return std::strcmp(left->valuestring, right->valuestring) == 0;
  if (cJSON_IsObject(left) || cJSON_IsArray(left)) {
    if (cJSON_GetArraySize(left) != cJSON_GetArraySize(right)) return false;
    const cJSON* other = right->child;
    for (const cJSON* child = left->child; child; child = child->next) {
      if (cJSON_IsObject(left)) other = field(right, child->string);
      if (!sameRequest(child, other)) return false;
      if (cJSON_IsArray(left)) other = other->next;
    }
    return true;
  }
  return cJSON_Compare(left, right, true);
}

//  所有会话校验完成后才提交快照，错误不产生部分应用 / Commit a snapshot only after every session passes validation without partial application
bool decodeRaster(const cJSON* node, uint8_t* output, unsigned size) {
  const unsigned encoded = ((size + 2) / 3) * 4;
  const unsigned padding = (3 - size % 3) % 3;
  if (!cJSON_IsString(node) || std::strlen(node->valuestring) != encoded) return false;
  const char* text = node->valuestring;
  const char* alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  uint32_t bits = 0;
  unsigned count = 0, written = 0;
  for (unsigned i = 0; i < encoded - padding; ++i) {
    const char* symbol = text[i] ? std::strchr(alphabet, text[i]) : nullptr;
    if (!symbol) return false;
    bits = (bits << 6) | static_cast<unsigned>(symbol - alphabet);
    count += 6;
    if (count >= 8) {
      count -= 8;
      if (written >= size) return false;
      output[written++] = static_cast<uint8_t>(bits >> count);
    }
  }
  for (unsigned i = encoded - padding; i < encoded; ++i) if (text[i] != '=') return false;
  return written == size && !(bits & ((1U << count) - 1));
}

const char* taskCards(const cJSON* body, TaskScreen& screen) {
  screen = TaskScreen{};
  const cJSON* value = field(body, "taskCards");
  if (!value) return nullptr;
  const char* const names[] = {"active", "cards"};
  const char* const labelNames[] = {"active", "cards", "labels"};
  const bool hasLabels = field(value, "labels") != nullptr;
  uint32_t active = 0;
  const cJSON* cards = field(value, "cards");
  unsigned actual = 0;
  const cJSON* sessions = field(body, "sessions");
  for (const cJSON* s = sessions->child; s; s = s->next) {
    if (equalText(field(s, "display"), "working") || equalText(field(s, "display"), "waitingApproval")) ++actual;
  }
  if (!(hasLabels ? fields(value, labelNames, 3) : fields(value, names, 2)) || !unsignedNumber(field(value, "active"), 0, active) || active != actual ||
      !cJSON_IsArray(cards) || cJSON_GetArraySize(cards) != static_cast<int>(actual > 4 ? 4 : actual)) return "invalid-task-cards";
  if (hasLabels && !decodeRaster(field(value, "labels"), screen.labels, 256)) return "invalid-task-labels";
  screen.hasLabels = hasLabels;
  for (const cJSON* card = cards->child; card; card = card->next) {
    const char* const cardNames[] = {"slot", "id", "bitmap"};
    uint32_t slot = 0;
    if (!fields(card, cardNames, 3) || !unsignedNumber(field(card, "slot"), 0, slot) || slot >= 4 ||
        screen.cards[slot].used || !alias(field(card, "id"))) return "invalid-task-card";
    for (const cJSON* prior = cards->child; prior != card; prior = prior->next) {
      if (equalText(field(prior, "id"), field(card, "id")->valuestring)) return "invalid-task-card";
    }
    const cJSON* match = nullptr;
    for (const cJSON* s = sessions->child; s; s = s->next) {
      if (equalText(field(s, "id"), field(card, "id")->valuestring)) match = s;
    }
    if (!match || (!equalText(field(match, "display"), "working") && !equalText(field(match, "display"), "waitingApproval"))) return "invalid-task-card";
    if (!decodeRaster(field(card, "bitmap"), screen.cards[slot].pixels, 320)) return "invalid-task-bitmap";
    screen.cards[slot].used = true;
    screen.cards[slot].waiting = equalText(field(match, "display"), "waitingApproval");
  }
  screen.available = true;
  screen.active = static_cast<uint8_t>(active);
  return nullptr;
}

const char* snapshot(const cJSON* body, std::size_t maxSessions, uint32_t& revision,
                     uint32_t& validity, const char*& display, uint32_t& challengeSeq, TaskScreen& screen) {
  const char* const names[] = {"revision", "validForMs", "sourceLiveness", "overallStatus", "sessions"};
  const bool challenge = field(body, "challengeSeq") != nullptr;
  const bool hasCards = field(body, "taskCards") != nullptr;
  bool validFields = cJSON_IsObject(body) && cJSON_GetArraySize(body) == (challenge ? 6 : 5) + (hasCards ? 1 : 0);
  for (const char* name : names) validFields = validFields && field(body, name);
  if (!validFields ||
      !equalText(field(body, "sourceLiveness"), "unverified")) return "invalid-source-state";
  if (challenge && !unsignedNumber(field(body, "challengeSeq"), 1, challengeSeq)) return "invalid-challenge";
  if (!unsignedNumber(field(body, "revision"), 1, revision) ||
      !unsignedNumber(field(body, "validForMs"), 0, validity)) return "invalid-snapshot-validity";
  const cJSON* sessions = field(body, "sessions");
  if (!cJSON_IsArray(sessions) || static_cast<std::size_t>(cJSON_GetArraySize(sessions)) > maxSessions) {
    return "session-capacity-exceeded";
  }
  int best = 5;
  for (const cJSON* entry = sessions->child; entry; entry = entry->next) {
    const char* const entryNames[] = {"id", "observed", "display", "host"};
    if (!fields(entry, entryNames, 4)) return "invalid-session-entry";
    const cJSON* id = field(entry, "id");
    if (!alias(id)) return "invalid-session-alias";
    for (const cJSON* other = sessions->child; other != entry; other = other->next) {
      if (equalText(field(other, "id"), id->valuestring)) return "invalid-session-alias";
    }
    const int observed = choice(field(entry, "observed"), kStatuses, 5);
    const int status = choice(field(entry, "display"), kStatuses, 5);
    if (observed < 0 || status < 0) return "invalid-business-state";
    const int host = choice(field(entry, "host"), kHosts, 5);
    if (host < 0) return "invalid-host-state";
    if (status != 2 && host != 0) return "host-unconfirmed";
    if (status != 2 && validity == 0) return "observation-expired";
    if (status < best) best = status;
  }
  display = kStatuses[best == 5 ? 2 : best];
  if (!equalText(field(body, "overallStatus"), display)) return "inconsistent-overall-state";
  return taskCards(body, screen);
}

cJSON* envelope(const char* boot, const char* channel, const char* session, uint32_t seq, const char* type) {
  cJSON* root = cJSON_CreateObject();
  if (!root) return nullptr;
  if (!cJSON_AddNumberToObject(root, "v", 1) || !cJSON_AddStringToObject(root, "boot", boot) ||
      !cJSON_AddStringToObject(root, "channel", channel) || !cJSON_AddStringToObject(root, "session", session) ||
      !cJSON_AddNumberToObject(root, "seq", seq) || !cJSON_AddStringToObject(root, "type", type) ||
      !cJSON_AddObjectToObject(root, "body")) {
    cJSON_Delete(root);
    return nullptr;
  }
  return root;
}

SessionResult serialize(cJSON* root, std::size_t limit, char* output, std::size_t capacity) {
  if (!root) return SessionResult::OutOfMemory;
  char* text = cJSON_PrintUnformatted(root);
  cJSON_Delete(root);
  if (!text) return SessionResult::OutOfMemory;
  const std::size_t length = std::strlen(text);
  const bool fits = output && length < capacity && length <= limit;
  if (fits) std::memcpy(output, text, length + 1);
  cJSON_free(text);
  return fits ? SessionResult::Reply : SessionResult::OutputTooSmall;
}
}  //  内部命名空间 / Internal namespace

ProtocolSession::ProtocolSession(const char* boot, SessionLimits limits) : limits_(limits) {
  valid_ = validToken(boot) && limits.maxJsonBytes > 0 && limits.maxJsonBytes < INT_MAX &&
           limits.maxSessions > 0 && limits.maxSessions < INT_MAX && limits.maxDepth > 0 && limits.leaseMs > 0;
  if (valid_) std::memcpy(boot_, boot, 33);
}

ProtocolSession::~ProtocolSession() { cJSON_Delete(lastRequest_); }

bool ProtocolSession::advance(uint64_t nowMs) {
  if (nowMs < now_) return false;
  now_ = nowMs;
  if (state_.leaseActive && now_ - state_.leaseStart >= limits_.leaseMs) {
    state_.leaseActive = false;
    state_.monitor = false;
    state_.expired = true;
  }
  return true;
}

SessionView ProtocolSession::stateView(const State& state) const {
  const bool fresh = state.monitor && now_ - state.snapshotStart < state.snapshotValidity;
  return {state.monitor ? "monitor" : "local", fresh ? state.display : "unknown",
          state.leaseActive, state.sequence, state.revision};
}

SessionView ProtocolSession::view() const { return stateView(state_); }

MonitorOutput ProtocolSession::monitorOutput(const State& state, bool selected) const {
  if (!selected) return MonitorOutput::Local;
  return state.monitor && state.leaseActive ? MonitorOutput::Connected : MonitorOutput::Disconnected;
}

MonitorOutput ProtocolSession::monitorOutput() const {
  return monitorOutput(state_, monitorSelected_);
}

void ProtocolSession::disconnect() {
  opened_ = false;
  state_ = State{};
  voiceSuppressed_ = false;
  localSelected_ = false;
  cJSON_Delete(lastRequest_);
  lastRequest_ = nullptr;
}

SessionResult ProtocolSession::open(const char* channel, uint64_t nowMs, char* output, std::size_t capacity) {
  if (output && capacity) output[0] = '\0';
  if (!valid_ || !validToken(channel) || std::strcmp(channel, channel_) == 0) return SessionResult::InvalidInput;
  if (!advance(nowMs)) return SessionResult::InvalidClock;
  cJSON* root = envelope(boot_, channel, "", 0, "welcome");
  if (!root) return SessionResult::OutOfMemory;
  cJSON* body = cJSON_GetObjectItemCaseSensitive(root, "body");
  cJSON* operations = cJSON_AddArrayToObject(body, "operations");
  bool ok = operations && cJSON_AddNumberToObject(body, "maxJsonBytes", limits_.maxJsonBytes) &&
            cJSON_AddNumberToObject(body, "maxSessions", limits_.maxSessions) &&
            cJSON_AddNumberToObject(body, "leaseMs", limits_.leaseMs);
#if OMIPET_PROTOCOL_FRESHNESS_CHALLENGE
  if (ok) ok = cJSON_AddBoolToObject(body, "freshnessChallenge", true) != nullptr;
#endif
#if OMIPET_MONITOR_LIGHTS
  if (ok) ok = cJSON_AddBoolToObject(body, "monitorLights", true) != nullptr;
  if (ok) ok = cJSON_AddBoolToObject(body, "taskCards", true) != nullptr;
#endif
#if OMIPET_MONITOR_GREEN_OFF
  if (ok) ok = cJSON_AddBoolToObject(body, "monitorGreenOff", true) != nullptr;
#endif
  for (const char* type : {"hello", "heartbeat", "snapshot", "release"}) {
    if (!ok) break;
    cJSON* item = cJSON_CreateString(type);
    if (!item || !cJSON_AddItemToArray(operations, item)) { cJSON_Delete(item); ok = false; }
  }
#if OMIPET_DESKTOP_CONTROL
  if (ok) {
    cJSON* item = cJSON_CreateString("light");
    if (!item || !cJSON_AddItemToArray(operations, item)) { cJSON_Delete(item); ok = false; }
  }
#endif
  if (ok && profiles_) {
    cJSON* item = cJSON_CreateString("monitorProfile");
    if (!item || !cJSON_AddItemToArray(operations, item)) { cJSON_Delete(item); ok = false; }
  }
  if (!ok) { cJSON_Delete(root); return SessionResult::OutOfMemory; }
  const SessionResult result = serialize(root, limits_.maxJsonBytes, output, capacity);
  if (result == SessionResult::Reply) {
    disconnect();
    std::memcpy(channel_, channel, 33);
    opened_ = true;
  }
  return result;
}

SessionResult ProtocolSession::writeAck(const cJSON* request, const State& state, bool ok,
                                       const char* code, bool duplicate, bool monitorSelected,
                                       char* output, std::size_t capacity, const MonitorProfiles* profiles) const {
  cJSON* root = envelope(boot_, channel_, field(request, "session")->valuestring,
                         static_cast<uint32_t>(field(request, "seq")->valuedouble), "ack");
  if (!root) return SessionResult::OutOfMemory;
  cJSON* body = cJSON_GetObjectItemCaseSensitive(root, "body");
  cJSON* status = cJSON_AddObjectToObject(body, "state");
  const SessionView current = stateView(state);
  if (!status || !cJSON_AddBoolToObject(body, "ok", ok) || !cJSON_AddStringToObject(body, "code", code) ||
      !cJSON_AddStringToObject(body, "command", field(request, "type")->valuestring) ||
      !cJSON_AddBoolToObject(body, "duplicate", duplicate) ||
      !cJSON_AddStringToObject(status, "mode", current.mode) ||
      !cJSON_AddStringToObject(status, "displayStatus", current.displayStatus) ||
      !cJSON_AddStringToObject(status, "sourceLiveness", "unverified") ||
      !cJSON_AddBoolToObject(status, "leaseActive", current.leaseActive)) {
    cJSON_Delete(root);
    return SessionResult::OutOfMemory;
  }
#if OMIPET_MONITOR_GREEN_OFF
  const MonitorOutput selectedOutput = monitorOutput(state, monitorSelected);
  const char* outputName = selectedOutput == MonitorOutput::Connected ? "connected" :
                           selectedOutput == MonitorOutput::Disconnected ? "disconnected" : "local";
  if (!cJSON_AddStringToObject(status, "monitorOutput", outputName)) {
    cJSON_Delete(root);
    return SessionResult::OutOfMemory;
  }
#else
  (void)monitorSelected;
#endif
  if (profiles_) {
    const auto& value = profiles ? *profiles : profiles_->current();
    cJSON* config = cJSON_AddObjectToObject(body, "monitorProfile");
    cJSON* lights = config ? cJSON_AddObjectToObject(config, "profiles") : nullptr;
    bool complete = lights && cJSON_AddNumberToObject(config, "revision", value.revision);
    const char* const effectNames[] = {"solid", "rainbow", "breathe", "sweep", "centerExpand", "off"};
    for (unsigned i = 0; complete && i < kMonitorStateCount; ++i) {
      const auto& light = value.lights[i];
      cJSON* entry = cJSON_AddObjectToObject(lights, kMonitorStates[i]);
      complete = entry && cJSON_AddStringToObject(entry, "effect", effectNames[static_cast<unsigned>(light.effect)]) &&
        cJSON_AddNumberToObject(entry, "red", light.red) && cJSON_AddNumberToObject(entry, "green", light.green) &&
        cJSON_AddNumberToObject(entry, "blue", light.blue) && cJSON_AddNumberToObject(entry, "brightness", light.brightness);
    }
    if (!complete) { cJSON_Delete(root); return SessionResult::OutOfMemory; }
  }
  return serialize(root, limits_.maxJsonBytes, output, capacity);
}

SessionResult ProtocolSession::receive(const char* data, std::size_t length, uint64_t nowMs,
                                      char* output, std::size_t capacity) {
  if (output && capacity) output[0] = '\0';
  if (!valid_) return SessionResult::InvalidInput;
  if (!advance(nowMs)) return SessionResult::InvalidClock;
  if (!data || length > limits_.maxJsonBytes) return SessionResult::InvalidInput;
  if (!opened_) return SessionResult::NotOpen;
  EnvelopeInfo info;
  if (inspectEnvelope(data, length, limits_.maxDepth, info) != EnvelopeResult::Valid) return SessionResult::InvalidInput;
  cJSON* request = cJSON_ParseWithLengthOpts(data, length, nullptr, false);
  if (!request) return SessionResult::OutOfMemory;
  std::size_t cursor = 0;
  if (!retainIntegers(request, data, length, cursor)) {
    cJSON_Delete(request);
    return SessionResult::OutOfMemory;
  }
  State next = state_;
  bool nextMonitorSelected = monitorSelected_;
  bool nextVoiceSuppressed = voiceSuppressed_;
  LocalLightCommand nextLight = light_;
  bool lightChanged = false;
  MonitorProfiles nextProfiles;
  bool profilesChanged = false;
  const cJSON* body = field(request, "body");
  const char* code = "ok";
  bool ok = false;
  bool duplicate = false;
  bool consume = false;
  if (!equalText(field(request, "boot"), boot_) || !equalText(field(request, "channel"), channel_)) code = "wrong-connection";
  else if (state_.session[0] && !equalText(field(request, "session"), state_.session)) code = "wrong-session";
  else if (state_.expired) code = "connection-expired-reconnect-required";
  else if (info.sequence == state_.sequence && lastRequest_) {
    if (!sameRequest(request, lastRequest_)) code = "sequence-conflict";
    else { ok = lastOk_; code = lastCode_; duplicate = true; }
  } else if (state_.sequence == UINT32_MAX || info.sequence != state_.sequence + 1) code = "sequence-gap-or-stale";
  else if (!state_.session[0]) {
    uint32_t version = 0;
    if (info.type != CommandType::Hello || info.sequence != 1 || cJSON_GetArraySize(body) != 1 ||
        !unsignedNumber(field(body, "protocol"), 1, version) || version != 1) code = "hello-required";
    else {
      std::memcpy(next.session, field(request, "session")->valuestring, 33);
      next.leaseActive = true;
      next.leaseStart = now_;
      ok = consume = true;
    }
  } else {
    consume = true;
    if (info.type == CommandType::Snapshot) {
      TaskScreen nextScreen;
      uint32_t revision = 0, validity = 0, challengeSeq = 0;
      const char* display = "unknown";
      const char* issue = snapshot(body, limits_.maxSessions, revision, validity, display, challengeSeq, nextScreen);
      if (issue) code = issue;
      else if (revision <= state_.revision) code = "snapshot-revision-stale";
#if OMIPET_PROTOCOL_FRESHNESS_CHALLENGE
      else if (display != kStatuses[2] &&
               (challengeSeq != state_.sequence || !lastRequest_ || !lastOk_ ||
                !equalText(field(lastRequest_, "type"), "heartbeat"))) code = "freshness-challenge-required";
#endif
      else {
#if OMIPET_PROTOCOL_FRESHNESS_CHALLENGE
        //  设备计时从心跳开始，过期快照只显示未知 / Count from the device heartbeat and display unknown for expired snapshots
        if (display != kStatuses[2]) {
          const uint64_t elapsed = now_ - state_.leaseStart;
          if (elapsed >= validity) { validity = 0; display = kStatuses[2]; }
          else validity -= static_cast<uint32_t>(elapsed);
        }
#endif
        next.revision = revision;
        next.screen = nextScreen;
        next.snapshotStart = now_;
        next.snapshotValidity = validity;
        next.display = display;
        next.monitor = next.leaseActive = true;
        if (!voiceSuppressed_) nextMonitorSelected = true;
        next.leaseStart = now_;
        ok = true;
      }
    }
#if OMIPET_DESKTOP_CONTROL
    else if (info.type == CommandType::MonitorProfile && profiles_) {
      if (cJSON_GetArraySize(body) == 0) ok = true;
      else {
        const char* const names[] = {"revision", "profiles"};
        uint32_t expected = 0;
        const cJSON* entries = field(body, "profiles");
        if (!fields(body, names, 2) || !unsignedNumber(field(body, "revision"), 0, expected) ||
            !fields(entries, kMonitorStates, kMonitorStateCount)) code = "invalid-monitor-profile";
        else if (expected != profiles_->current().revision) code = "monitor-profile-conflict";
        else {
          nextProfiles = profiles_->current();
          const char* issue = nullptr;
          for (unsigned i = 0; i < kMonitorStateCount && !issue; ++i) issue = localLight(field(entries, kMonitorStates[i]), nextProfiles.lights[i]);
          if (issue) code = issue;
          else if (!sameMonitorLights(nextProfiles, profiles_->current()) && expected == UINT32_MAX) code = "monitor-profile-revision-exhausted";
          else {
            profilesChanged = !sameMonitorLights(nextProfiles, profiles_->current());
            if (profilesChanged) ++nextProfiles.revision;
            ok = true;
          }
        }
      }
      if (ok) { next.leaseActive = true; next.leaseStart = now_; }
    }
    else if (info.type == CommandType::Light) {
      if (state_.monitor) code = "monitor-mode-active";
      else if (!localLightAllowed_) code = localLightReason_;
      else if (light_.revision == UINT32_MAX) code = "light-revision-exhausted";
      else {
        const char* issue = localLight(body, nextLight);
        if (issue) code = issue;
        else {
          ++nextLight.revision;
          next.leaseActive = true;
          next.leaseStart = now_;
          ok = lightChanged = true;
          nextMonitorSelected = nextVoiceSuppressed = false;
        }
      }
    }
#endif
    else if (info.type == CommandType::Heartbeat || info.type == CommandType::Release) {
      bool disconnectRelease = false;
#if OMIPET_MONITOR_GREEN_OFF
      const char* const disconnectFields[] = {"disconnect"};
      disconnectRelease = info.type == CommandType::Release && fields(body, disconnectFields, 1) &&
                          cJSON_IsTrue(field(body, "disconnect"));
#endif
      if (cJSON_GetArraySize(body) != 0 && !disconnectRelease) code = "empty-body-required";
      else {
        ok = true;
        if (info.type == CommandType::Release) {
          next.monitor = false;
          next.leaseActive = false;
          if (!disconnectRelease) nextMonitorSelected = false;
          nextVoiceSuppressed = false;
        }
        else { next.leaseActive = true; next.leaseStart = now_; }
      }
    } else code = "unsupported-command";
  }
  if (consume) next.sequence = info.sequence;
  //  先完整生成应答再提交；输出不足或分配失败时可以原序号重试 / Generate the full reply before committing so output or allocation failure permits retry
  SessionResult result = writeAck(request, next, ok, code, duplicate, nextMonitorSelected, output, capacity,
                                  profilesChanged ? &nextProfiles : nullptr);
  if (result == SessionResult::Reply && profilesChanged && !profiles_->save(nextProfiles)) {
    ok = false; code = "monitor-profile-save-failed";
    result = writeAck(request, next, ok, code, false, nextMonitorSelected, output, capacity);
  }
  if (result == SessionResult::Reply && consume) {
    state_ = next;
    monitorSelected_ = nextMonitorSelected;
    voiceSuppressed_ = nextVoiceSuppressed;
    cJSON_Delete(lastRequest_);
    lastRequest_ = request;
    request = nullptr;
    lastOk_ = ok;
    lastCode_ = code;
    if (lightChanged) light_ = nextLight;
    if (ok && (lightChanged || (info.type == CommandType::Release && !nextMonitorSelected))) localSelected_ = true;
  }
  cJSON_Delete(request);
  return result;
}

}  //  协议命名空间 / Protocol namespace
#endif
