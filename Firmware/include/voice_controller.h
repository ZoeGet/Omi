#pragma once

#include <Arduino.h>

namespace OmiPetVoice {

//  唤醒确认音配置 / Wake acknowledgement tone configuration
constexpr uint32_t kWakeAcknowledgementHighFrequencyHz = 2600;  //  唤醒确认音高音频率 / Wake acknowledgement high-tone frequency
constexpr uint32_t kWakeAcknowledgementLowFrequencyHz = 1800;  //  唤醒确认音低音频率 / Wake acknowledgement low-tone frequency
constexpr uint32_t kWakeAcknowledgementHighDurationMs = 100;  //  唤醒确认音高音持续时间 / Wake acknowledgement high-tone duration
constexpr uint32_t kWakeAcknowledgementLowDurationMs = 60;  //  唤醒确认音低音持续时间 / Wake acknowledgement low-tone duration
constexpr uint32_t kWakeAcknowledgementSilenceDurationMs = 20;  //  唤醒确认音高低音之间的静音间隔 / Silence gap between acknowledgement tones
constexpr uint32_t kPostAcknowledgementSpeechSuppressionMs = 200;  //  确认音结束后的语音抑制时间 / Speech suppression after acknowledgement
constexpr uint32_t kCommandListenTimeoutMs = 5000;  //  唤醒后等待亮度指令的超时时间 / Timeout for a brightness command after wake-up

//  唤醒后的语音交互状态 / Post-wake voice interaction states
enum class VoiceState : uint8_t {
  Idle,
  ListeningForCommand,
};

//  非阻塞确认音播放阶段 / Non-blocking acknowledgement playback phases
enum class AcknowledgementPhase : uint8_t {
  None,
  LowTone,
  SilenceGap,
  HighTone,
};

//  管理唤醒后的语音交互状态 / Manage the voice interaction state after wake-up
class VoiceController {
 public:
  //  初始化语音交互状态机 / Initialize the voice interaction state machine
  bool begin();

  //  更新确认音序列和唤醒后的语音超时 / Update the acknowledgement sequence and post-wake timeout
  void update(bool speechActive);

  //  通知状态机检测到唤醒词 / Notify the state machine that a wake word was detected
  bool notifyWakeWordDetected();

  //  通知状态机命令处理完成 / Notify the state machine that command processing is complete
  bool notifyCommandCompleted();

  //  获取当前语音交互状态 / Get the current voice interaction state
  VoiceState state() const;

  //  查询是否正在等待用户指令 / Check whether a user command is expected
  bool listeningForCommand() const;

  //  查询确认音是否暂时屏蔽麦克风判定 / Check whether microphone decisions are temporarily suppressed
  bool speechInputSuppressed() const;

 private:
  //  推进低音、静音间隔和高音播放 / Advance low tone, silence gap, and high tone playback
  void updateAcknowledgement(uint32_t nowMs);
  //  停止确认音并复位监听状态 / Stop acknowledgement and reset listening state
  void enterIdle();

  VoiceState state_ = VoiceState::Idle;
  AcknowledgementPhase acknowledgementPhase_ = AcknowledgementPhase::None;
  uint32_t acknowledgementPhaseStartedAtMs_ = 0;
  uint32_t lastActivityAtMs_ = 0;
  uint32_t speechSuppressedUntilMs_ = 0;
  bool initialized_ = false;
};

extern VoiceController voice;

}  //  OmiPetVoice 命名空间 / OmiPetVoice namespace
