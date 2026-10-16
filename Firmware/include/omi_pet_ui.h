#pragma once

#include <stdint.h>

namespace OmiPetUi {

//  初始化桌面仪表盘界面 / Initialize the desktop dashboard user interface
void begin();

//  更新温湿度显示 / Update the temperature and humidity display
void setEnvironment(float temperatureC, float humidityPercent, bool valid);
//  更新估算电量百分比显示 / Update the estimated battery-percentage display
void setBatteryStatus(uint8_t percent, bool valid);

//  更新 Wi-Fi 状态和名称显示 / Update the Wi-Fi status and name display
void setNetworkStatus(bool connected, bool provisioning, const char* ssid);

//  更新联网时间和日期显示 / Update the network time and date display
void setDateTime(bool valid, int year, int month, int day, int hour, int minute);

//  更新语音交互状态显示 / Update the voice interaction status display
void setVoiceStatus(const char* statusText);

//  绘制或清除六位配对码；仅负责显示，不开启网络配对 / Show or clear a six-digit pairing code; display only, without enabling network pairing
void setPairingCode(const char* sixDigits, uint16_t secondsRemaining, const char* address = nullptr);

//  按秒更新时钟 / Update the clock once per second
void update();

}  //  OmiPetUi 命名空间 / OmiPetUi namespace
