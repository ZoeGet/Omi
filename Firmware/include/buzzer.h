#pragma once

#include <Arduino.h>

namespace OmiPetBuzzer {

//  无源蜂鸣器硬件配置 / Passive buzzer hardware configuration
constexpr uint8_t kBuzzerPin = 4;  //  无源蜂鸣器 GPIO 引脚 / Passive buzzer GPIO pin
constexpr uint8_t kBuzzerPwmChannel = 0;  //  蜂鸣器使用的 LEDC PWM 通道 / LEDC PWM channel used by the buzzer
constexpr uint8_t kBuzzerPwmResolutionBits = 10;  //  蜂鸣器 PWM 分辨率位数 / Buzzer PWM resolution in bits
constexpr uint32_t kBuzzerDefaultFrequencyHz = 2500;  //  蜂鸣器默认频率 / Buzzer default frequency
constexpr uint8_t kBuzzerDefaultDutyPercent = 50;  //  蜂鸣器默认占空比百分比 / Buzzer default duty-cycle percentage

//  蜂鸣器驱动错误类型 / Buzzer driver error types
enum class BuzzerError : uint8_t {
  None,
  NotInitialized,
  InvalidFrequency,
  InvalidDutyCycle,
  PwmSetupFailed,
};

//  基于 LEDC 硬件 PWM 的无源蜂鸣器驱动 / Passive buzzer driver using LEDC hardware PWM
class PassiveBuzzer {
 public:
  //  初始化 GPIO 和 LEDC，初始化后保持静音 / Initialize GPIO and LEDC, remaining silent after initialization
  bool begin(uint8_t pin = kBuzzerPin, uint8_t channel = kBuzzerPwmChannel);  //  蜂鸣器 GPIO 和 LEDC 通道 / Buzzer GPIO and LEDC channel

  //  启动指定频率和时长的非阻塞提示音，时长为 0 表示持续播放 / Start a non-blocking tone; duration 0 means continuous playback
  bool startTone(uint32_t frequencyHz,
                 uint32_t durationMs,
                 uint8_t dutyPercent = kBuzzerDefaultDutyPercent);  //  音调频率、时长和占空比 / Tone frequency, duration, and duty cycle

  //  停止输出并将 GPIO 拉低 / Stop output and drive the GPIO low
  void stop();

  //  更新非阻塞播放状态，应在主循环中周期调用 / Update non-blocking playback state; call periodically from the main loop
  void update();

  //  获取最近一次错误 / Get the most recent error
  BuzzerError lastError() const;

 private:
  //  将频率和占空比应用到 LEDC / Apply frequency and duty cycle to LEDC
  bool applyTone(uint32_t frequencyHz, uint8_t dutyPercent);

  //  记录错误并停止危险输出 / Record an error and stop unsafe output
  bool fail(BuzzerError error);

  uint8_t pin_ = kBuzzerPin;
  uint8_t channel_ = kBuzzerPwmChannel;
  uint32_t startedAtMs_ = 0;
  uint32_t durationMs_ = 0;
  BuzzerError lastError_ = BuzzerError::None;
  bool initialized_ = false;
  bool playing_ = false;
};

extern PassiveBuzzer buzzer;

}  //  OmiPetBuzzer 命名空间 / OmiPetBuzzer namespace
