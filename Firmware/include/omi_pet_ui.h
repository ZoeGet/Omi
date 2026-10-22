#pragma once

#include <stdint.h>
#include "task_screen.h"

namespace OmiPetUi {

//  初始化伙伴仪表盘与区域缓冲 / Initialize the companion dashboard and region buffer
void begin();

//  更新温湿度显示 / Update the temperature and humidity display
void setEnvironment(float temperatureC, float humidityPercent, bool valid);
//  更新由估算电量驱动的电池图标 / Update the battery icon using the estimated charge level
void setBatteryStatus(uint8_t percent, bool valid);

//  更新顶部 Wi-Fi 状态；保留名称参数以兼容调用方 / Update header Wi-Fi status; retain the name argument for caller compatibility
void setNetworkStatus(bool connected, bool provisioning, const char* ssid);

//  更新联网时间和日期显示 / Update the network time and date display
void setDateTime(bool valid, int year, int month, int day, int hour, int minute);

//  更新语音交互状态显示 / Update the voice interaction status display
void setVoiceStatus(const char* statusText);

//  绘制或清除六位配对码；仅负责显示，不开启网络配对 / Show or clear a six-digit pairing code; display only, without enabling network pairing
void setPairingCode(const char* sixDigits, uint16_t secondsRemaining, const char* address = nullptr);

//  刷新变化区域，整页切换分轮传输；时间由有效联网状态提供 / Refresh changed regions and split page transitions across calls; use valid network time
void update();
//  Codex模式切换为四槽任务屏，断联清除旧任务 / Switch Codex mode to a four-slot task screen and clear tasks on disconnect
void setTaskScreen(bool enabled, bool connected, const OmiPetProtocol::TaskScreen* screen);

}  //  OmiPetUi 命名空间 / OmiPetUi namespace
