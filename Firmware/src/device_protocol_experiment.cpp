#include "device_protocol_experiment.h"

#if OMIPET_PROTOCOL_EXPERIMENT
#include <Arduino.h>
#include "device_protocol_envelope.h"
#include "device_protocol_framer.h"

#if OMIPET_PROTOCOL_USB
#include "device_protocol_transport.h"
#include "esp_system.h"
#include "esp_timer.h"
#include <new>
#include <atomic>
#endif

namespace OmiPetProtocol {
namespace {
#if OMIPET_PROTOCOL_USB
using UsbTransport = ProtocolTransport<OMIPET_PROTOCOL_MAX_JSON_BYTES>;
alignas(UsbTransport) uint8_t gTransportStorage[sizeof(UsbTransport)];
UsbTransport* gTransport = nullptr;
std::atomic<bool> gBusReset{false};
uint64_t gMaxPollUs = 0;
bool gBuffersReady = false;
uint32_t gBusResets = 0;

void newToken(char* output) {
  uint8_t bytes[16];
  esp_fill_random(bytes, sizeof(bytes));
  const char* hex = "0123456789abcdef";
  for (std::size_t i = 0; i < sizeof(bytes); ++i) {
    output[2 * i] = hex[bytes[i] >> 4];
    output[2 * i + 1] = hex[bytes[i] & 15];
  }
  output[32] = '\0';
}

struct UsbPort {
  bool plugged() const { return Serial.isPlugged(); }
  bool ready() const { return static_cast<bool>(Serial); }
  int available() const { return Serial.available(); }
  int read() const { return Serial.read(); }
  int availableForWrite() const { return Serial.availableForWrite(); }
  std::size_t write(const uint8_t* data, std::size_t size) const { return Serial.write(data, size); }
};
#else
SerialFramer<OMIPET_PROTOCOL_MAX_JSON_BYTES> gFramer;
#endif
}  //  内部命名空间 / Internal namespace

void pollSerialExperiment(void (*debugWake)(), bool localLightAllowed) {
#if OMIPET_PROTOCOL_USB
  if (!gBuffersReady) return;
  const uint64_t start = static_cast<uint64_t>(esp_timer_get_time());
  if (!gTransport) {
    char boot[33];
    newToken(boot);
    gTransport = new (gTransportStorage) UsbTransport(boot, OMIPET_PROTOCOL_MAX_SESSIONS,
                                                    OMIPET_PROTOCOL_MAX_JSON_DEPTH, OMIPET_PROTOCOL_LEASE_MS);
  }
  if (gBusReset.exchange(false)) { ++gBusResets; gTransport->disconnect(); }
  UsbPort port;
  gTransport->allowLocalLightCommand(localLightAllowed);
  gTransport->poll(port, start / 1000, OMIPET_PROTOCOL_RX_BYTES_PER_LOOP, newToken, debugWake);
  const uint64_t elapsed = static_cast<uint64_t>(esp_timer_get_time()) - start;
  if (elapsed > gMaxPollUs) gMaxPollUs = elapsed;
#else
  (void)localLightAllowed;
  for (std::size_t count = 0; count < OMIPET_PROTOCOL_RX_BYTES_PER_LOOP && Serial.available() > 0; ++count) {
    const int input = Serial.read();
    if (input < 0) return;
    const FeedResult result = gFramer.feed(static_cast<uint8_t>(input));
    if (result == FeedResult::DebugWake) {
      if (debugWake) debugWake();
    } else if (result == FeedResult::FrameReady) {
      EnvelopeInfo info;
      const EnvelopeResult inspected = inspectEnvelope(gFramer.frame(), gFramer.frameLength(),
                                                       OMIPET_PROTOCOL_MAX_JSON_DEPTH, info);
      Serial.printf("[PROTO] result=%s bytes=%u type=%s seq=%lu execution=disabled\n",
                    envelopeResultName(inspected), static_cast<unsigned>(gFramer.frameLength()),
                    commandTypeName(info.type), static_cast<unsigned long>(info.sequence));
      return;
    } else if (result != FeedResult::None) {
      Serial.printf("[PROTO] result=frame_rejected reason=%u execution=disabled\n",
                    static_cast<unsigned>(result));
      return;
    }
  }
#endif
}

#if OMIPET_PROTOCOL_USB
bool configureUsbExperiment() {
  //  当前 USB_MODE=1 在 setup 中首次 begin 前设置缓冲，运行后不得重设 / Current USB_MODE=1 configures buffers before the first begin in setup; never resize at runtime
  const std::size_t rx = Serial.setRxBufferSize(OMIPET_PROTOCOL_MAX_JSON_BYTES + 8);
  const std::size_t tx = Serial.setTxBufferSize(OMIPET_PROTOCOL_TX_BUFFER_BYTES);
  Serial.setTxTimeoutMs(OMIPET_PROTOCOL_WRITE_WAIT_MS);
  Serial.onEvent(ARDUINO_HW_CDC_BUS_RESET_EVENT, [](void*, esp_event_base_t, int32_t, void*) { gBusReset.store(true); });
  gBuffersReady = rx == OMIPET_PROTOCOL_MAX_JSON_BYTES + 8 && tx == OMIPET_PROTOCOL_TX_BUFFER_BYTES;
  return gBuffersReady;
}

void reportUsbExperiment() {
  if (!gTransport) { Serial.printf("[PROTO] usb=unavailable buffers=%s\n", gBuffersReady ? "ready" : "failed"); return; }
  const SessionView state = gTransport->view();
  const TransportStats& stats = gTransport->stats();
  Serial.printf("[PROTO] usb=experimental mode=%s display=%s lease=%u seq=%lu probes=%lu requests=%lu sent=%lu rejected=%lu stalled=%lu stale=%lu write_failures=%lu session_failure=%lu frame_failure=%lu link_losses=%lu reopens=%lu bus_resets=%lu link_down_polls=%lu last_link_down_ms=%llu max_link_down_ms=%llu max_poll_us=%llu heap=%u\n",
                state.mode, state.displayStatus, state.leaseActive ? 1U : 0U,
                static_cast<unsigned long>(state.lastSequence), static_cast<unsigned long>(stats.probes),
                static_cast<unsigned long>(stats.requests), static_cast<unsigned long>(stats.sent),
                static_cast<unsigned long>(stats.rejected), static_cast<unsigned long>(stats.stalled),
                static_cast<unsigned long>(stats.staleReplies), static_cast<unsigned long>(stats.writeFailures),
                static_cast<unsigned long>(stats.lastSessionFailure), static_cast<unsigned long>(stats.lastFrameFailure),
                static_cast<unsigned long>(stats.linkLosses), static_cast<unsigned long>(stats.reopens), static_cast<unsigned long>(gBusResets),
                static_cast<unsigned long>(stats.linkDownPolls),
                static_cast<unsigned long long>(stats.lastLinkDownMs), static_cast<unsigned long long>(stats.maxLinkDownMs),
                static_cast<unsigned long long>(gMaxPollUs), static_cast<unsigned>(esp_get_free_heap_size()));
}

SessionView usbExperimentView() {
  if (!gTransport) return {"local", "unknown", false, 0, 0};
  return gTransport->view();
}

LocalLightCommand usbLocalLightCommand() {
  return gTransport ? gTransport->localLightCommand() : LocalLightCommand{};
}

MonitorOutput usbMonitorOutput() {
  return gTransport ? gTransport->monitorOutput() : MonitorOutput::Local;
}

void yieldUsbMonitorToVoice() {
  if (gTransport) gTransport->yieldMonitorToVoice();
}
#endif

}  //  协议命名空间 / Protocol namespace
#endif
