#include "voice_controller.h"

#include "buzzer.h"
#include "omi_pet_ui.h"

//  唤醒确认音和指令监听状态机实现 / Wake acknowledgement and command-listening state machine implementation
namespace OmiPetVoice {

//  初始化语音状态机并把界面设置为待机 / Initialize the voice state machine and show idle
bool VoiceController::begin() {
  state_ = VoiceState::Idle;
  acknowledgementPhase_ = AcknowledgementPhase::None;
  acknowledgementPhaseStartedAtMs_ = 0;
  lastActivityAtMs_ = millis();
  speechSuppressedUntilMs_ = 0;
  initialized_ = true;
  OmiPetUi::setVoiceStatus("IDLE");
  return true;
}

//  按当前状态推进语音交互流程 / Advance the voice interaction flow by state
void VoiceController::update(bool speechActive) {
  if (!initialized_) {
    return;
  }

  const uint32_t nowMs = millis();
  updateAcknowledgement(nowMs);

  if (state_ != VoiceState::ListeningForCommand) {
    return;
  }

  if (speechActive) {
    lastActivityAtMs_ = nowMs;
    return;
  }

  if (nowMs - lastActivityAtMs_ >= kCommandListenTimeoutMs) {
    Serial.println("[VOICE] command timeout");
    enterIdle();
  }
}

//  接收一次唤醒词事件并开始确认音 / Accept a wake event and start acknowledgement
bool VoiceController::notifyWakeWordDetected() {
  if (!initialized_ || state_ != VoiceState::Idle) {
    return false;
  }

  const uint32_t nowMs = millis();
  state_ = VoiceState::ListeningForCommand;
  acknowledgementPhase_ = AcknowledgementPhase::LowTone;
  acknowledgementPhaseStartedAtMs_ = nowMs;
  lastActivityAtMs_ = nowMs;
  if (!OmiPetBuzzer::buzzer.startTone(
          kWakeAcknowledgementLowFrequencyHz,
          kWakeAcknowledgementLowDurationMs)) {
    Serial.println("[VOICE] low acknowledgement tone failed");
  }
  OmiPetUi::setVoiceStatus("LISTENING");
  Serial.println("[VOICE] wake accepted, acknowledgement=low, listening for command");
  return true;
}

//  标记当前指令采集已经完成 / Mark the current command capture as complete
bool VoiceController::notifyCommandCompleted() {
  if (!initialized_ || state_ != VoiceState::ListeningForCommand) {
    return false;
  }

  Serial.println("[VOICE] command completed");
  enterIdle();
  return true;
}

//  返回当前语音交互状态 / Return the current voice interaction state
VoiceState VoiceController::state() const {
  return state_;
}

//  查询是否正在等待用户命令 / Check whether a user command is expected
bool VoiceController::listeningForCommand() const {
  return state_ == VoiceState::ListeningForCommand;
}

//  查询确认音期间是否暂时屏蔽语音判定 / Check whether speech decisions are temporarily suppressed
bool VoiceController::speechInputSuppressed() const {
  if (acknowledgementPhase_ != AcknowledgementPhase::None) {
    return true;
  }

  return static_cast<int32_t>(speechSuppressedUntilMs_ - millis()) > 0;
}

//  按时间推进低音、静音和高音三个确认阶段 / Advance the low, silence, and high acknowledgement phases
void VoiceController::updateAcknowledgement(uint32_t nowMs) {
  if (acknowledgementPhase_ == AcknowledgementPhase::None) {
    return;
  }

  if (acknowledgementPhase_ == AcknowledgementPhase::LowTone &&
      nowMs - acknowledgementPhaseStartedAtMs_ >=
          kWakeAcknowledgementLowDurationMs) {
    OmiPetBuzzer::buzzer.stop();
    acknowledgementPhase_ = AcknowledgementPhase::SilenceGap;
    acknowledgementPhaseStartedAtMs_ = nowMs;
    Serial.println("[VOICE] acknowledgement=silence");
    return;
  }

  if (acknowledgementPhase_ == AcknowledgementPhase::SilenceGap &&
      nowMs - acknowledgementPhaseStartedAtMs_ >=
          kWakeAcknowledgementSilenceDurationMs) {
    acknowledgementPhase_ = AcknowledgementPhase::HighTone;
    acknowledgementPhaseStartedAtMs_ = nowMs;
    Serial.println("[VOICE] acknowledgement=high");
    if (!OmiPetBuzzer::buzzer.startTone(
            kWakeAcknowledgementHighFrequencyHz,
            kWakeAcknowledgementHighDurationMs)) {
      Serial.println("[VOICE] high acknowledgement tone failed");
      acknowledgementPhase_ = AcknowledgementPhase::None;
    }
    return;
  }

  if (acknowledgementPhase_ == AcknowledgementPhase::HighTone &&
      nowMs - acknowledgementPhaseStartedAtMs_ >=
          kWakeAcknowledgementHighDurationMs) {
    OmiPetBuzzer::buzzer.stop();
    acknowledgementPhase_ = AcknowledgementPhase::None;
    speechSuppressedUntilMs_ = nowMs + kPostAcknowledgementSpeechSuppressionMs;
    Serial.println("[VOICE] acknowledgement=complete");
  }
}

//  停止提示音并清理所有等待状态 / Stop acknowledgement audio and clear waiting state
void VoiceController::enterIdle() {
  OmiPetBuzzer::buzzer.stop();
  state_ = VoiceState::Idle;
  acknowledgementPhase_ = AcknowledgementPhase::None;
  acknowledgementPhaseStartedAtMs_ = 0;
  speechSuppressedUntilMs_ = 0;
  lastActivityAtMs_ = millis();
  OmiPetUi::setVoiceStatus("IDLE");
}

VoiceController voice;

}  //  OmiPetVoice 命名空间 / OmiPetVoice namespace
