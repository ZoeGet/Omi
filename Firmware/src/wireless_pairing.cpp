#include "wireless_pairing.h"
#include "wireless_control.h"
#if OMIPET_WIFI_PAIRING
#include <Arduino.h>
#include <WiFi.h>
#include <atomic>
#include <memory>
#include <new>
#include <cJSON.h>
#include <esp_http_server.h>
#include <esp_timer.h>
#include <esp_system.h>
#include <lwip/sockets.h>
#include <mbedtls/base64.h>
#include <mbedtls/ssl.h>
#include <mbedtls/net_sockets.h>
#include <mbedtls/x509_crt.h>
#include <mbedtls/pk.h>
#include "omi_pet_ui.h"
#include "pairing_boot.h"
#include "pairing_exchange.h"
#include "pairing_auth_gate.h"
#include "pairing_nvs_store.h"
#include "pairing_tls_store.h"
#include "pairing_identity_state.h"

#if !CONFIG_HTTPD_WS_SUPPORT || !CONFIG_MBEDTLS_ECJPAKE_C || !CONFIG_MBEDTLS_HKDF_C
#error "Wireless pairing requires the isolated WebSocket, ECJPAKE and HKDF configuration"
#endif

namespace OmiPetPairing {
namespace {
constexpr uint32_t kStepMs = 10000;
constexpr uint32_t kIoMs = 2000;
constexpr size_t kFrameBytes = 4096;
uint64_t nowMs() { return esp_timer_get_time() / 1000; }
int randomBytes(void*, unsigned char* output, size_t size) { esp_fill_random(output, size); return 0; }
bool randomWord(uint32_t* value, void*) { *value = esp_random(); return true; }

httpd_handle_t server = nullptr;
SemaphoreHandle_t mutex = nullptr;
std::atomic<bool> started{false};
std::atomic<int> liveSocket{-1};
std::atomic<bool> closeQueued{false};
std::atomic<bool> pairingRequested{false};
std::atomic<uint32_t> deadlineMs{0};
uint8_t certificate[1024], privateKey[256], pin[32], dailyKey[32];
mbedtls_x509_crt tlsCertificate;
mbedtls_pk_context tlsKey;
mbedtls_ssl_config tlsConfig;
PairingBoot boot;
bool paired = false;
uint64_t openedAt = 0;

struct Lock {
  Lock() { xSemaphoreTake(mutex, portMAX_DELAY); }
  ~Lock() { xSemaphoreGive(mutex); }
};

//  TLS 回调按绝对截止时间限制整次握手，避免分段发送不断续期 / TLS callbacks bound the entire handshake by an absolute deadline, preventing trickle traffic from extending it
struct TlsConnection {
  mbedtls_ssl_context ssl;
  int fd;
  uint64_t deadline;
  explicit TlsConnection(int socket) : fd(socket), deadline(nowMs() + kStepMs) { mbedtls_ssl_init(&ssl); }
  ~TlsConnection() { mbedtls_ssl_free(&ssl); }
};

int socketIo(void* context, unsigned char* buffer, size_t length, bool sending) {
  auto* connection = static_cast<TlsConnection*>(context);
  const uint64_t now = nowMs();
  if (now >= connection->deadline) return MBEDTLS_ERR_SSL_TIMEOUT;
  const uint64_t remaining = connection->deadline - now;
  timeval timeout{static_cast<long>(remaining / 1000), static_cast<long>((remaining % 1000) * 1000)};
  if (setsockopt(connection->fd, SOL_SOCKET, sending ? SO_SNDTIMEO : SO_RCVTIMEO, &timeout, sizeof(timeout)) != 0) return MBEDTLS_ERR_NET_RECV_FAILED;
  const int result = sending ? ::send(connection->fd, buffer, length, 0) : ::recv(connection->fd, buffer, length, 0);
  if (result >= 0) return result;
  return errno == EAGAIN || errno == EWOULDBLOCK ? MBEDTLS_ERR_SSL_TIMEOUT : MBEDTLS_ERR_NET_RECV_FAILED;
}
int tlsSend(void* context, const unsigned char* buffer, size_t length) {
  return socketIo(context, const_cast<unsigned char*>(buffer), length, true);
}
int tlsReceive(void* context, unsigned char* buffer, size_t length) { return socketIo(context, buffer, length, false); }
int tlsReceiveTimeout(void* context, unsigned char* buffer, size_t length, uint32_t) { return tlsReceive(context, buffer, length); }
void freeTls(void* context) { delete static_cast<TlsConnection*>(context); liveSocket = -1; closeQueued = false; }
int transportReceive(httpd_handle_t handle, int fd, char* data, size_t size, int) {
  auto* connection = static_cast<TlsConnection*>(httpd_sess_get_transport_ctx(handle, fd));
  connection->deadline = nowMs() + kIoMs;
  const int result = mbedtls_ssl_read(&connection->ssl, reinterpret_cast<unsigned char*>(data), size);
  return result >= 0 ? result : result == MBEDTLS_ERR_SSL_TIMEOUT ? HTTPD_SOCK_ERR_TIMEOUT : HTTPD_SOCK_ERR_FAIL;
}
int transportSend(httpd_handle_t handle, int fd, const char* data, size_t size, int) {
  auto* connection = static_cast<TlsConnection*>(httpd_sess_get_transport_ctx(handle, fd));
  connection->deadline = nowMs() + kIoMs;
  size_t sent = 0;
  while (sent < size) {
    const int result = mbedtls_ssl_write(&connection->ssl, reinterpret_cast<const unsigned char*>(data) + sent, size - sent);
    if (result <= 0) return -1;
    sent += result;
  }
  return sent;
}
int transportPending(httpd_handle_t handle, int fd) {
  auto* connection = static_cast<TlsConnection*>(httpd_sess_get_transport_ctx(handle, fd));
  return mbedtls_ssl_check_pending(&connection->ssl);
}
esp_err_t openTls(httpd_handle_t handle, int fd) {
  if (WiFi.status() != WL_CONNECTED) return ESP_FAIL;
  std::unique_ptr<TlsConnection> connection(new (std::nothrow) TlsConnection(fd));
  if (!connection || mbedtls_ssl_setup(&connection->ssl, &tlsConfig) != 0) return ESP_FAIL;
  mbedtls_ssl_set_bio(&connection->ssl, connection.get(), tlsSend, tlsReceive, tlsReceiveTimeout);
  if (mbedtls_ssl_handshake(&connection->ssl) != 0 || nowMs() >= connection->deadline) return ESP_FAIL;
  httpd_sess_set_transport_ctx(handle, fd, connection.release(), freeTls);
  httpd_sess_set_send_override(handle, fd, transportSend);
  httpd_sess_set_recv_override(handle, fd, transportReceive);
  httpd_sess_set_pending_override(handle, fd, transportPending);
  deadlineMs = static_cast<uint32_t>(nowMs() + kStepMs);
  liveSocket = fd;
  return ESP_OK;
}

struct Peer {
  PairingExchange exchange;
  PairingAuthGate auth;
  mbedtls_sha256_context hash;
  uint8_t digest[32] = {}, key[32] = {}, nonce[32] = {};
  int phase = 0;
  bool attempt = false;
  uint32_t connection = 0;
  Peer() { mbedtls_sha256_init(&hash); }
  ~Peer() {
    mbedtls_sha256_free(&hash);
    mbedtls_platform_zeroize(key, sizeof(key));
  }
};
void freePeer(void* value) {
  auto* peer = static_cast<Peer*>(value);
#if OMIPET_WIFI_CONTROL
  OmiPetProtocol::closeWirelessControl(peer->connection);
#endif
  Lock lock;
  if (peer->attempt) boot.finishAttempt(false, nowMs());
  delete peer;
}
using Json = std::unique_ptr<cJSON, decltype(&cJSON_Delete)>;
Json jsonObject() { return Json(cJSON_CreateObject(), cJSON_Delete); }
const char* stringField(cJSON* object, const char* name) {
  cJSON* field = cJSON_GetObjectItemCaseSensitive(object, name);
  return cJSON_IsString(field) ? field->valuestring : nullptr;
}
bool shape(cJSON* object, const char* kind, int fields) {
  cJSON* version = cJSON_GetObjectItemCaseSensitive(object, "v");
  const char* type = stringField(object, "type");
  return cJSON_GetArraySize(object) == fields + 2 && cJSON_IsNumber(version) &&
         version->valuedouble == 1 && type && std::strcmp(type, kind) == 0;
}
Json parse(char* text, size_t size) {
  //  认证消息仅允许一层 ASCII 对象，先排除嵌套和转义再解析 / Authentication accepts flat ASCII objects only; reject nesting and escapes before parsing
  bool quoted = false;
  int depth = 0;
  for (size_t i = 0; i < size; ++i) {
    const unsigned char c = text[i];
    if (c == '\\' || c == 0 || c > 126) return Json(nullptr, cJSON_Delete);
    if (c == '"') quoted = !quoted;
    if (!quoted && (c == '[' || c == ']' || (c == '{' && ++depth > 1))) return Json(nullptr, cJSON_Delete);
    if (!quoted && c == '}') --depth;
  }
  const char* end = nullptr;
  Json object(cJSON_ParseWithLengthOpts(text, size + 1, &end, true), cJSON_Delete);
  if (!object || !cJSON_IsObject(object.get())) return Json(nullptr, cJSON_Delete);
  for (cJSON* a = object->child; a; a = a->next) {
    if (!a->string) return Json(nullptr, cJSON_Delete);
    for (cJSON* b = a->next; b; b = b->next)
      if (std::strcmp(a->string, b->string) == 0) return Json(nullptr, cJSON_Delete);
  }
  return object;
}
bool decode(cJSON* object, const char* name, uint8_t* output, size_t capacity, size_t& size) {
  const char* text = stringField(object, name);
  if (!text || std::strlen(text) > ((capacity + 2) / 3) * 4) return false;
  return mbedtls_base64_decode(output, capacity, &size, reinterpret_cast<const uint8_t*>(text), std::strlen(text)) == 0 && size > 0;
}
bool encoded(cJSON* object, const char* name, const uint8_t* input, size_t size) {
  unsigned char buffer[(kPairingRoundBytes + 2) / 3 * 4 + 1];
  size_t length = 0;
  if (size > kPairingRoundBytes || mbedtls_base64_encode(buffer, sizeof(buffer), &length, input, size) != 0) return false;
  buffer[length] = 0;
  return cJSON_AddStringToObject(object, name, reinterpret_cast<char*>(buffer)) != nullptr;
}
bool appendRound(Peer& peer, const uint8_t* data, size_t size) {
  const uint8_t length[] = {static_cast<uint8_t>(size >> 8), static_cast<uint8_t>(size)};
  return mbedtls_sha256_update_ret(&peer.hash, length, 2) == 0 && mbedtls_sha256_update_ret(&peer.hash, data, size) == 0;
}
esp_err_t sendReply(httpd_req_t* req, const char* kind, Json& object) {
  if (!cJSON_AddNumberToObject(object.get(), "v", 1) || !cJSON_AddStringToObject(object.get(), "type", kind)) return ESP_FAIL;
  char* text = cJSON_PrintUnformatted(object.get());
  if (!text) return ESP_FAIL;
  httpd_ws_frame_t frame{};
  frame.type = HTTPD_WS_TYPE_TEXT;
  frame.payload = reinterpret_cast<uint8_t*>(text);
  frame.len = std::strlen(text);
  const esp_err_t result = frame.len <= kFrameBytes ? httpd_ws_send_frame(req, &frame) : ESP_FAIL;
  cJSON_free(text);
  return result;
}

esp_err_t handleMessage(httpd_req_t* req, Peer& peer, cJSON* request) {
  auto reply = jsonObject();
  if (!reply) return ESP_FAIL;
  if (peer.phase == 0 && shape(request, "status", 0)) {
    cJSON_AddBoolToObject(reply.get(), "paired", paired);
    peer.phase = 1;
    return sendReply(req, "status", reply);
  }
  uint8_t data[kPairingRoundBytes], other[kPairingRoundBytes], received[32], expected[32];
  size_t size = 0, otherSize = 0, proofSize = 0;
  boot.advance(nowMs());
  if (peer.phase == 1 && paired && !boot.visibleCode() && shape(request, "challenge", 0)) {
    randomBytes(nullptr, peer.nonce, 32);
    if (!peer.auth.begin(true, dailyKey, pin, peer.nonce) || !encoded(reply.get(), "nonce", peer.nonce, 32)) return ESP_FAIL;
    peer.phase = 4;
    return sendReply(req, "challenge", reply);
  }
  if (peer.phase == 4 && shape(request, "authenticate", 2)) {
    if (!decode(request, "nonce", data, 32, size) || size != 32 ||
        !decode(request, "proof", received, 32, proofSize) ||
        !peer.auth.finish(data, received, proofSize, expected) || !encoded(reply.get(), "proof", expected, 32)) return ESP_FAIL;
    peer.phase = 5;
    return sendReply(req, "authenticated", reply);
  }
  if (peer.phase == 1 && ((!paired && shape(request, "pair1", 1)) || shape(request, "repair1", 1))) {
    if (!boot.beginAttempt(nowMs())) return ESP_FAIL;
    peer.attempt = true;
    if (!peer.exchange.begin(true, boot.visibleCode(), randomBytes, nullptr) ||
        !decode(request, "data", data, sizeof(data), size)) return ESP_FAIL;
    constexpr char domain[] = "OmiPet pairing transcript v1";
    if (mbedtls_sha256_starts_ret(&peer.hash, 0) != 0 ||
        mbedtls_sha256_update_ret(&peer.hash, reinterpret_cast<const uint8_t*>(domain), sizeof(domain) - 1) != 0 ||
        mbedtls_sha256_update_ret(&peer.hash, pin, 32) != 0 || !appendRound(peer, data, size) ||
        !peer.exchange.write(other, sizeof(other), &otherSize) || !peer.exchange.read(data, size) ||
        !appendRound(peer, other, otherSize) || !encoded(reply.get(), "one", other, otherSize) ||
        !peer.exchange.write(other, sizeof(other), &otherSize) || !appendRound(peer, other, otherSize) ||
        !encoded(reply.get(), "two", other, otherSize)) return ESP_FAIL;
    peer.phase = 2;
    return sendReply(req, "pair1", reply);
  }
  if (peer.phase == 2 && shape(request, "pair2", 2)) {
    if (boot.advance(nowMs()) != WindowState::InProgress || !decode(request, "data", data, sizeof(data), size) ||
        !decode(request, "proof", received, 32, proofSize) || proofSize != 32 || !appendRound(peer, data, size) ||
        mbedtls_sha256_finish_ret(&peer.hash, peer.digest) != 0 || !peer.exchange.read(data, size) ||
        !peer.exchange.derive(peer.key)) return ESP_FAIL;
    bool valid = pairingConfirmation(peer.key, 'H', peer.digest, pin, expected) && fixedTimeEqual(expected, received, 32);
    if (!valid || !pairingConfirmation(peer.key, 'D', peer.digest, pin, expected) ||
        !encoded(reply.get(), "proof", expected, 32) ||
        !derivePairingDailyKey(peer.key, 32, peer.digest, pin, data)) return ESP_FAIL;
    std::memcpy(peer.key, data, 32);
    mbedtls_platform_zeroize(data, sizeof(data));
    peer.phase = 3;
    return sendReply(req, "pair2", reply);
  }
  if (peer.phase == 3 && shape(request, "commit", 1)) {
    if (boot.advance(nowMs()) != WindowState::InProgress || !decode(request, "proof", received, 32, proofSize) ||
        proofSize != 32 || !pairingConfirmation(peer.key, 'C', peer.digest, pin, expected) ||
        !fixedTimeEqual(expected, received, 32)) return ESP_FAIL;
    const bool replacing = paired;
    const bool stored = replacing ? replacePairingCredential(peer.key, pin, dailyKey) : savePairingCredentialOnce(peer.key, pin);
    uint8_t storedPin[32];
    const auto state = loadPairingCredential(dailyKey, storedPin);
    paired = state == CredentialLoadState::Present && fixedTimeEqual(pin, storedPin, 32);
    if (!stored || !paired || !fixedTimeEqual(dailyKey, peer.key, 32)) {
      boot.finishAttempt(false, nowMs());
      peer.attempt = false;
      if (state == CredentialLoadState::Unknown || (state == CredentialLoadState::Present && !paired)) boot.invalidateIdentity();
      return ESP_FAIL;
    }
    boot.finishAttempt(true, nowMs());
    peer.attempt = false;
    peer.phase = 5;
    if (!pairingConfirmation(peer.key, 'S', peer.digest, pin, expected) || !encoded(reply.get(), "proof", expected, 32)) return ESP_FAIL;
    Serial.printf("[PAIR] committed=1 replaced=%u\n", replacing);
    return sendReply(req, "committed", reply);
  }
  return ESP_FAIL;
}

esp_err_t websocketHandler(httpd_req_t* req) {
  if (req->method == HTTP_GET) {
    auto* peer = new (std::nothrow) Peer;
    if (!peer) return ESP_ERR_NO_MEM;
    static uint32_t nextConnection = 0;
    if (++nextConnection == 0) ++nextConnection;
    peer->connection = nextConnection;
    req->sess_ctx = peer;
    req->free_ctx = freePeer;
    return ESP_OK;
  }
  httpd_ws_frame_t frame{};
  if (httpd_ws_recv_frame(req, &frame, 0) != ESP_OK || frame.len == 0 || frame.len > kFrameBytes ||
      frame.type != HTTPD_WS_TYPE_TEXT || !frame.final) return ESP_FAIL;
  std::unique_ptr<uint8_t[]> buffer(new (std::nothrow) uint8_t[frame.len + 1]());
  if (!buffer) return ESP_ERR_NO_MEM;
  frame.payload = buffer.get();
  if (httpd_ws_recv_frame(req, &frame, frame.len) != ESP_OK) return ESP_FAIL;
#if OMIPET_WIFI_CONTROL
  auto* peer = static_cast<Peer*>(req->sess_ctx);
  if (peer && peer->auth.authorized()) {
    if (static_cast<int32_t>(static_cast<uint32_t>(nowMs()) - deadlineMs.load()) >= 0) return ESP_FAIL;
    std::unique_ptr<char[]> reply(new (std::nothrow) char[kFrameBytes + 1]);
    if (!reply || !OmiPetProtocol::exchangeWirelessControl(peer->connection,
        reinterpret_cast<char*>(buffer.get()), frame.len, reply.get())) return ESP_FAIL;
    httpd_ws_frame_t response{};
    response.type = HTTPD_WS_TYPE_TEXT;
    response.payload = reinterpret_cast<uint8_t*>(reply.get());
    response.len = std::strlen(reply.get());
    deadlineMs = static_cast<uint32_t>(nowMs() + kStepMs);
    return httpd_ws_send_frame(req, &response);
  }
#endif
  auto request = parse(reinterpret_cast<char*>(buffer.get()), frame.len);
  if (!request || !req->sess_ctx) return ESP_FAIL;
  Lock lock;
  if (static_cast<int32_t>(static_cast<uint32_t>(nowMs()) - deadlineMs.load()) >= 0) return ESP_FAIL;
  const esp_err_t result = handleMessage(req, *static_cast<Peer*>(req->sess_ctx), request.get());
  if (static_cast<int32_t>(static_cast<uint32_t>(nowMs()) - deadlineMs.load()) >= 0) return ESP_FAIL;
  deadlineMs = static_cast<uint32_t>(nowMs() + kStepMs);
  return result;
}

bool startService() {
  uint8_t storedPin[32];
  auto credential = loadPairingCredential(dailyKey, storedPin);
  size_t certSize = 0, keySize = 0;
  auto identity = loadTlsIdentity(certificate, sizeof(certificate), &certSize, privateKey, sizeof(privateKey), &keySize, pin);
  const auto stored = classifyStoredIdentity(credential, identity, fixedTimeEqual(pin, storedPin, 32));
  if (stored == StoredIdentityState::Unknown) return false;
  if (identity == TlsIdentityReadState::Absent) {
    if (!generateTlsIdentity(randomBytes, nullptr, "20260101000000", "20500101000000", certificate,
        sizeof(certificate), &certSize, privateKey, sizeof(privateKey), &keySize, pin) ||
        !saveTlsIdentityOnce(certificate, certSize, privateKey, keySize, pin)) return false;
  }
  paired = stored == StoredIdentityState::Present;
  mbedtls_x509_crt_init(&tlsCertificate);
  mbedtls_pk_init(&tlsKey);
  mbedtls_ssl_config_init(&tlsConfig);
  if (mbedtls_x509_crt_parse_der(&tlsCertificate, certificate, certSize) != 0 ||
      mbedtls_pk_parse_key(&tlsKey, privateKey, keySize, nullptr, 0) != 0 ||
      mbedtls_ssl_config_defaults(&tlsConfig, MBEDTLS_SSL_IS_SERVER, MBEDTLS_SSL_TRANSPORT_STREAM, MBEDTLS_SSL_PRESET_DEFAULT) != 0 ||
      mbedtls_ssl_conf_own_cert(&tlsConfig, &tlsCertificate, &tlsKey) != 0) return false;
  mbedtls_ssl_conf_rng(&tlsConfig, randomBytes, nullptr);
  mbedtls_ssl_conf_min_version(&tlsConfig, MBEDTLS_SSL_MAJOR_VERSION_3, MBEDTLS_SSL_MINOR_VERSION_3);
  mbedtls_ssl_conf_authmode(&tlsConfig, MBEDTLS_SSL_VERIFY_NONE);
  mbedtls_ssl_conf_read_timeout(&tlsConfig, kStepMs);
  mbedtls_platform_zeroize(privateKey, sizeof(privateKey));
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 8443;
  config.stack_size = 10240;
  config.max_open_sockets = 1;
  config.lru_purge_enable = false;
  config.recv_wait_timeout = config.send_wait_timeout = 2;
  config.open_fn = openTls;
  if (httpd_start(&server, &config) != ESP_OK) return false;
  httpd_uri_t uri{};
  uri.uri = "/pair";
  uri.method = HTTP_GET;
  uri.handler = websocketHandler;
  uri.is_websocket = true;
  if (httpd_register_uri_handler(server, &uri) != ESP_OK) { httpd_stop(server); server = nullptr; return false; }
  Lock lock;
  boot.onBoot(stored);
  started = true;
  Serial.printf("[PAIR] ready=1 paired=%u ip=%s port=8443\n", paired, WiFi.localIP().toString().c_str());
  return true;
}
void startTask(void*) {
  if (!startService()) {
    Serial.println("[PAIR] ready=0 reason=identity-or-service");
    mbedtls_platform_zeroize(privateKey, sizeof(privateKey));
  }
  vTaskDelete(nullptr);
}
}  //  私有服务状态 / Private service state

bool requestWirelessPairing() {
  if (WiFi.status() != WL_CONNECTED || !started.load()) {
    Serial.println("[PAIR] open=0 reason=offline-or-not-ready");
    return false;
  }
  pairingRequested = true;
  return true;
}

void updateWirelessPairing(bool connected) {
  static bool attempted = false;
  if (connected && !attempted) {
    attempted = true;
    mutex = xSemaphoreCreateMutex();
    if (!mutex || xTaskCreate(startTask, "omi-pair-init", 10240, nullptr, tskIDLE_PRIORITY + 5, nullptr) != pdPASS)
      Serial.println("[PAIR] ready=0 reason=memory");
  }
  if (!started) return;
  const int fd = liveSocket.load();
  if (fd >= 0 && (!connected || pairingRequested.load() || static_cast<int32_t>(static_cast<uint32_t>(nowMs()) - deadlineMs.load()) >= 0) && !closeQueued.exchange(true)) {
    if (httpd_sess_trigger_close(server, fd) != ESP_OK) closeQueued = false;
  }
  if (xSemaphoreTake(mutex, 0) != pdTRUE) return;
  bool openFailed = false;
  if (!connected) pairingRequested = false;
  if (connected && liveSocket.load() < 0 && pairingRequested.exchange(false)) {
    openedAt = nowMs();
    const bool opened = boot.openByRequest(openedAt, randomWord, nullptr);
    openFailed = !opened;
    Serial.printf("[PAIR] open=%u source=voice paired=%u ip=%s port=8443\n", opened, paired, WiFi.localIP().toString().c_str());
  }
  boot.advance(nowMs());
  char code[7] = {};
  const char* visible = connected ? boot.visibleCode() : nullptr;
  if (visible) std::memcpy(code, visible, sizeof(code));
  const uint64_t remaining = nowMs() < openedAt + kPairingValidityMs ? openedAt + kPairingValidityMs - nowMs() : 0;
  xSemaphoreGive(mutex);
  if (openFailed) OmiPetUi::setVoiceStatus("PAIR UNREADY");
  OmiPetUi::setPairingCode(code[0] ? code : nullptr, (remaining + 999) / 1000, WiFi.localIP().toString().c_str());
}
}  //  配对命名空间 / Pairing namespace
#endif
