#pragma once
#include "device_protocol_session.h"

#ifndef OMIPET_WIFI_CONTROL
#define OMIPET_WIFI_CONTROL 0
#endif

#if OMIPET_WIFI_CONTROL
namespace OmiPetProtocol {
//  仅认证后的网络线程可投递；会话与灯光仅在主循环访问 / Only authenticated network callers enqueue; the main loop owns sessions and lights
bool exchangeWirelessControl(uint32_t connection, const char* data, size_t size, char* reply);
void closeWirelessControl(uint32_t connection);
void pollWirelessControl(bool connected, bool localAllowed, const char* reason);
SessionView wirelessControlView();
MonitorOutput wirelessMonitorOutput();
LocalLightCommand wirelessLocalLightCommand();
void yieldWirelessMonitorToVoice();
bool takeWirelessLocalSelection();
}
#endif
