#include "wifi_manager.h"

//  Wi-Fi 配网、重连和热点管理实现 / Wi-Fi provisioning, reconnection, and portal management implementation

namespace OmiPetNetwork {

size_t WifiManagerService::networkCount() const {
  size_t count = 0;
  while (count < 5 && saved_.entries[count].ssid[0]) ++count;
  return count;
}

void WifiManagerService::rememberNetwork(const String& ssid, const String& password) {
  if (ssid.isEmpty() || ssid.length() > 32 || password.length() > 64) return;
  size_t index = 0;
  while (index < networkCount() && ssid != saved_.entries[index].ssid) ++index;
  if (index == 0 && ssid == saved_.entries[0].ssid &&
      password == saved_.entries[0].password) return;
  if (index >= 5) index = 4;
  for (size_t i = index; i > 0; --i) saved_.entries[i] = saved_.entries[i - 1];
  ssid.toCharArray(saved_.entries[0].ssid, sizeof(saved_.entries[0].ssid));
  password.toCharArray(saved_.entries[0].password, sizeof(saved_.entries[0].password));
  if (!storageReady_ || preferences_.putBytes("networks", &saved_, sizeof(saved_)) != sizeof(saved_)) {
    Serial.println("[WIFI] credential storage failed; history is RAM-only");
  } else {
    Serial.printf("[WIFI] saved networks=%u\n", static_cast<unsigned>(networkCount()));
  }
}

void WifiManagerService::tryNextNetwork() {
  if (networkCount() == 0) return;
  nextNetwork_ %= networkCount();
  const auto& network = saved_.entries[nextNetwork_++];
  //  禁止驱动自动重试上一组凭据与轮换连接竞争 / Prevent driver retries of the previous credentials from competing with rotation
  WiFi.setAutoReconnect(false);
  WiFi.persistent(false);
  WiFi.disconnect();
  WiFi.begin(network.ssid, network.password);
  lastReconnectAttemptMs_ = millis();
  Serial.printf("[WIFI] trying saved network=%u/%u\n",
                static_cast<unsigned>(nextNetwork_), static_cast<unsigned>(networkCount()));
}

//  初始化 Wi-Fi 状态和配网服务 / Initialize Wi-Fi state and provisioning service
bool WifiManagerService::begin() {
  //  显式使用 STA 模式，避免正常联网时保持 AP+STA / Explicitly use STA mode instead of keeping AP+STA during normal operation
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(false);
  storageReady_ = preferences_.begin("omi-wifi", false);
  if (storageReady_ && preferences_.getBytesLength("networks") == sizeof(saved_)) {
    SavedNetworks loaded;
    if (preferences_.getBytes("networks", &loaded, sizeof(loaded)) == sizeof(loaded) && loaded.version == 1) {
      bool valid = true;
      for (const auto& entry : loaded.entries) {
        valid = valid && memchr(entry.ssid, 0, sizeof(entry.ssid)) &&
                memchr(entry.password, 0, sizeof(entry.password));
      }
      if (valid) saved_ = loaded;
    }
  }
  //  升级时保留驱动中唯一的旧凭据；不会恢复更早已被覆盖的网络 / Preserve the driver's legacy credential on upgrade; overwritten networks cannot be recovered
  if (networkCount() == 0) rememberNetwork(manager_.getWiFiSSID(true), manager_.getWiFiPass(true));

  //  非阻塞模式只适用于配置门户；autoConnect 仍可能同步等待连接 / Non-blocking mode applies to the portal, while autoConnect can still wait synchronously
  manager_.setConfigPortalBlocking(false);
  manager_.setWiFiAutoReconnect(false);
  manager_.setConfigPortalTimeout(kProvisioningTimeoutSeconds);
  manager_.setConnectTimeout(kWifiConnectTimeoutSeconds);

  //  只启动已保存凭据的异步连接，不在 setup 中调用 autoConnect / Start an asynchronous connection with saved credentials without calling autoConnect from setup
  tryNextNetwork();
  connectStartedAtMs_ = millis();
  lastReconnectAttemptMs_ = connectStartedAtMs_;
  disconnectedAtMs_ = 0;
  initialized_ = true;
  provisioning_ = false;
  portalStarted_ = false;
  everConnected_ = false;
  wasConnected_ = false;
  lastPortalAttemptMs_ = 0;
  return connected();
}

//  驱动连接重试和配网状态机 / Advance connection retries and the provisioning state machine
void WifiManagerService::update() {
  if (!initialized_) {
    return;
  }

  if (WiFi.status() == WL_CONNECTED) {
    if (!wasConnected_) {
      rememberNetwork(WiFi.SSID(), WiFi.psk());
      Serial.println("[WIFI] connected");
      nextNetwork_ = 0;
    }
    wasConnected_ = true;
    everConnected_ = true;
    disconnectedAtMs_ = 0;
    provisioning_ = false;
    if (portalStarted_) {
      //  连接成功后停止配置门户，避免继续占用 AP 和 Web 资源 / Stop the portal after connection to release AP and web resources
      if (manager_.getConfigPortalActive()) manager_.stopConfigPortal();
      portalStarted_ = false;
    }
    return;
  }

  wasConnected_ = false;

  if (portalStarted_) {
    //  门户处理提交后继续轮换旧网络，避免环境恢复时一直等待 / Continue rotating saved networks after portal processing so recovery need not wait
    manager_.process();
    portalStarted_ = manager_.getConfigPortalActive();
    provisioning_ = portalStarted_;
    if (WiFi.status() == WL_CONNECTED) return;
    if (millis() - lastReconnectAttemptMs_ >= kWifiReconnectIntervalMs) tryNextNetwork();
    return;
  }

  if (!everConnected_ &&
      millis() - connectStartedAtMs_ >= (networkCount() ? networkCount() * kWifiConnectTimeoutSeconds * 1000U : kInitialWifiConnectWindowMs) &&
      (lastPortalAttemptMs_ == 0 || millis() - lastPortalAttemptMs_ >= kProvisioningTimeoutSeconds * 1000U)) {
    lastPortalAttemptMs_ = millis();
    //  超时后才启动门户，避免启动阶段被 Wi-Fi 连接阻塞 / Start the portal only after timeout so Wi-Fi cannot block startup
    manager_.startConfigPortal(kProvisioningSsid, kProvisioningPassword);
    portalStarted_ = manager_.getConfigPortalActive();
    provisioning_ = portalStarted_;
    Serial.printf("[WIFI] config portal active=%s ap_ip=%s ssid=%s\n",
                  portalStarted_ ? "yes" : "no", WiFi.softAPIP().toString().c_str(),
                  kProvisioningSsid);
    return;
  }

  if (everConnected_) {
    const uint32_t nowMs = millis();
    if (disconnectedAtMs_ == 0U) {
      disconnectedAtMs_ = nowMs;
      Serial.println("[WIFI] connection lost, retry window started");
    }

    if (nowMs - disconnectedAtMs_ >= kWifiReconnectGracePeriodMs &&
        (lastPortalAttemptMs_ == 0 || nowMs - lastPortalAttemptMs_ >= kProvisioningTimeoutSeconds * 1000U)) {
      lastPortalAttemptMs_ = nowMs;
      //  重连超时后开启配网门户 / Start provisioning after the reconnect grace period expires
      manager_.startConfigPortal(kProvisioningSsid, kProvisioningPassword);
      portalStarted_ = manager_.getConfigPortalActive();
      provisioning_ = portalStarted_;
      Serial.printf("[WIFI] config portal active=%s ap_ip=%s ssid=%s\n",
                    portalStarted_ ? "yes" : "no", WiFi.softAPIP().toString().c_str(),
                    kProvisioningSsid);
      return;
    }

  }
  if (millis() - lastReconnectAttemptMs_ >= kWifiReconnectIntervalMs) {
    tryNextNetwork();
  }
}

//  查询当前是否已连接到路由器 / Check whether the device is connected to a router
bool WifiManagerService::connected() const {
  return WiFi.status() == WL_CONNECTED;
}

//  获取当前已连接的 Wi-Fi 名称 / Get the currently connected Wi-Fi name
String WifiManagerService::ssid() const {
  return connected() ? WiFi.SSID() : String();
}

//  查询网页配网门户是否正在运行 / Check whether the provisioning portal is running
bool WifiManagerService::provisioning() const {
  return provisioning_;
}

WifiManagerService wifi;

}  //  OmiPetNetwork 命名空间 / OmiPetNetwork namespace
