#include "wireless_control.h"
#if OMIPET_WIFI_CONTROL
#include "protocol_experiment_config.h"
#include "monitor_light_profiles.h"
#include <Arduino.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <atomic>
#include <cstring>
#include <memory>
#include <new>

namespace OmiPetProtocol {
namespace {
constexpr uint32_t kIoMs = 2000;
SemaphoreHandle_t mutex = nullptr;
SemaphoreHandle_t replyReady = nullptr;
std::atomic<bool> initialized{false};
std::unique_ptr<ProtocolSession> session;
char request[OMIPET_PROTOCOL_MAX_JSON_BYTES + 1], response[OMIPET_PROTOCOL_MAX_JSON_BYTES + 1];
size_t requestSize = 0;
uint32_t connectionId = 0;
uint64_t queuedAt = 0;
bool connected = false, reset = false, pending = false, replied = false;

uint64_t nowMs() { return esp_timer_get_time() / 1000; }
void token(char* output) {
  uint8_t bytes[16]; esp_fill_random(bytes, sizeof(bytes));
  const char hex[] = "0123456789abcdef";
  for (size_t i = 0; i < sizeof(bytes); ++i) { output[i * 2] = hex[bytes[i] >> 4]; output[i * 2 + 1] = hex[bytes[i] & 15]; }
  output[32] = 0;
}
}

bool exchangeWirelessControl(uint32_t connection, const char* data, size_t size, char* reply) {
  if (!initialized || !data || !reply || !size || size > OMIPET_PROTOCOL_MAX_JSON_BYTES) return false;
  xSemaphoreTake(mutex, portMAX_DELAY);
  xSemaphoreTake(replyReady, 0);
  if (connection != connectionId) { reset = true; connectionId = connection; }
  connected = pending = true; replied = false;
  std::memcpy(request, data, size); request[size] = 0; requestSize = size; queuedAt = nowMs();
  xSemaphoreGive(mutex);
  const bool signalled = xSemaphoreTake(replyReady, pdMS_TO_TICKS(kIoMs)) == pdTRUE;
  xSemaphoreTake(mutex, portMAX_DELAY);
  const bool success = signalled && replied && connected && connectionId == connection;
  if (success) std::strcpy(reply, response);
  pending = false; replied = false;
  xSemaphoreGive(mutex);
  return success;
}

void closeWirelessControl(uint32_t connection) {
  if (!initialized) return;
  xSemaphoreTake(mutex, portMAX_DELAY);
  if (connectionId == connection) { connected = pending = false; reset = true; }
  xSemaphoreGive(mutex);
}

void pollWirelessControl(bool networkConnected, bool localAllowed, const char* reason) {
  if (!initialized) {
    static bool attempted = false;
    if (attempted) return;
    attempted = true;
    char boot[33]; token(boot);
    session.reset(new (std::nothrow) ProtocolSession(boot, {OMIPET_PROTOCOL_MAX_JSON_BYTES,
      OMIPET_PROTOCOL_MAX_SESSIONS, OMIPET_PROTOCOL_MAX_JSON_DEPTH, OMIPET_PROTOCOL_LEASE_MS}));
    mutex = xSemaphoreCreateMutex(); replyReady = xSemaphoreCreateBinary();
    if (!session || !mutex || !replyReady) {
      if (mutex) vSemaphoreDelete(mutex);
      if (replyReady) vSemaphoreDelete(replyReady);
      session.reset();
      return;
    }
#if OMIPET_DESKTOP_CONTROL && OMIPET_MONITOR_LIGHTS && OMIPET_MONITOR_GREEN_OFF
    session->setMonitorProfileStore(&monitorProfiles);
#endif
    initialized = true;
  }
  if (xSemaphoreTake(mutex, 0) != pdTRUE) return;
  const uint64_t now = nowMs();
  if (!networkConnected) { connected = pending = false; reset = true; }
  if (reset) { session->disconnect(); reset = false; }
  session->advance(now);
  session->allowLocalLightCommand(localAllowed, reason);
  if (pending && connected) {
    SessionResult result = SessionResult::InvalidInput;
    if (now - queuedAt < kIoMs) {
      if (requestSize == 1 && request[0] == '?') {
        char channel[33]; token(channel);
        result = session->open(channel, now, response, sizeof(response));
      } else result = session->receive(request, requestSize, now, response, sizeof(response));
    }
    replied = result == SessionResult::Reply;
    pending = false;
    xSemaphoreGive(replyReady);
  }
  xSemaphoreGive(mutex);
}

SessionView wirelessControlView() { return session ? session->view() : SessionView{"local", "unknown", false, 0, 0}; }
const TaskScreen* wirelessTaskScreen() { return session ? session->taskScreen() : nullptr; }
MonitorOutput wirelessMonitorOutput() { return session ? session->monitorOutput() : MonitorOutput::Local; }
LocalLightCommand wirelessLocalLightCommand() { return session ? session->localLightCommand() : LocalLightCommand{}; }
void yieldWirelessMonitorToVoice() { if (session) session->yieldMonitorToVoice(); }
bool takeWirelessLocalSelection() { return session && session->takeLocalSelection(); }
}
#endif
