#include <Arduino.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include "aht20_sensor.h"
#include "battery_monitor.h"
#include "buzzer.h"
#include "NV3007_Display.h"
#include "device_protocol_experiment.h"
#include "led_controller.h"
#if OMIPET_MONITOR_LIGHTS
#include "led_arbitration.h"
#if OMIPET_DESKTOP_CONTROL && OMIPET_MONITOR_GREEN_OFF
#include "monitor_light_profiles.h"
#endif
#endif
#include "omi_pet_ui.h"
#include "time_service.h"
#include "wifi_manager.h"
#include "wireless_pairing.h"
#include "wireless_control.h"
#include "monitor_transport_arbiter.h"

//  OmiPet 固件主循环和模块编排 / OmiPet firmware entry point and module orchestration
#include "ics43434_mic.h"
#include "pcm_audio_frame_buffer.h"
#include "multinet_command_recognizer.h"
#include "voice_controller.h"

namespace {

//  音频链路为 I2S、PCM 队列、AFE、VAD 和 MultiNet 的串联流程 / The audio path chains I2S, PCM queue, AFE, VAD, and MultiNet
//  麦克风诊断窗口和周期参数 / Microphone diagnostic window and periodic timing parameters
constexpr size_t kMicDiagnosticFrameCount = 160;  //  每个麦克风诊断窗口的采样帧数 / Audio frames per microphone diagnostic window
constexpr size_t kMicDiagnosticWordCount = kMicDiagnosticFrameCount * 2;  //  双声道原始槽的样本字数量 / Raw sample words for both channel slots
constexpr uint32_t kMicWindowIntervalMs = 10;  //  麦克风诊断窗口处理间隔 / Microphone diagnostic-window interval
constexpr uint32_t kMicLogIntervalMs = 1000;  //  麦克风诊断日志输出间隔 / Microphone diagnostic log interval
constexpr uint32_t kSpeechDetectionHangoverMs = 1200;  //  语音结束后继续允许 MultiNet 检测的尾窗时间 / MultiNet detection hangover after speech ends
constexpr size_t kMaxCommandFramesPerLoop = 4;  //  单次主循环最多处理的命令音频帧数 / Maximum command audio frames processed per loop
constexpr uint32_t kMinimumSpeechStartRms = 10000;  //  从静音进入语音状态的最小 RMS / Minimum RMS to start speech state
constexpr uint32_t kMinimumSpeechHoldRms = 5000;  //  保持语音状态的最小 RMS / Minimum RMS to hold speech state
constexpr uint8_t kSpeechStartWindowCount = 3;  //  连续语音窗口达到此数后进入语音状态 / Speech windows required to enter speech state
constexpr uint8_t kSpeechEndWindowCount = 8;  //  连续安静窗口达到此数后退出语音状态 / Quiet windows required to leave speech state

//  麦克风采样、噪声底和 VAD 状态 / Microphone samples, noise floor, and VAD state
int32_t gMicDiagnosticWords[kMicDiagnosticWordCount] = {};  //  麦克风双声道原始样本窗口 / Raw stereo microphone sample window
uint32_t gLastMicWindowMs = 0;  //  上一次麦克风窗口处理时间 / Last microphone-window processing time
uint32_t gLastMicLogMs = 0;  //  上一次麦克风日志时间 / Last microphone diagnostic log time
uint32_t gLastSystemHeartbeatMs = 0;  //  上一次系统心跳时间 / Last system heartbeat time
uint32_t gMicNoiseFloorRms = 0;  //  自适应噪声底 RMS / Adaptive microphone noise-floor RMS
bool gMicNoiseFloorInitialized = false;  //  是否已经初始化噪声底 / Whether the noise floor is initialized
uint8_t gSpeechStartWindows = 0;  //  连续语音候选窗口计数 / Consecutive speech-candidate window count
uint8_t gSpeechQuietWindows = 0;  //  连续安静窗口计数 / Consecutive quiet-window count
bool gSpeechActive = false;  //  当前是否处于语音活动状态 / Whether speech is currently active
//  记录最近一次 VAD 语音活动，用于维持检测尾窗 / Track the latest VAD activity to maintain the detection hangover
uint32_t gLastSpeechActivityMs = 0;  //  最近一次语音活动时间 / Most recent speech-activity time
uint32_t gLastMicThreshold = 0;  //  最近一次动态语音判定阈值 / Most recent adaptive speech threshold
bool gLastSpeechCandidate = false;  //  最近一次窗口是否为语音候选 / Whether the latest window was a speech candidate

struct MicLevelStats {
  uint32_t averageAbsolute = 0;  //  窗口平均绝对振幅 / Window average absolute amplitude
  uint32_t rms = 0;  //  窗口均方根音量 / Window root-mean-square level
  uint32_t peak = 0;  //  窗口峰值振幅 / Window peak amplitude
  size_t frameCount = 0;  //  已统计的采样帧数 / Number of sampled frames included
};

MicLevelStats gLastMicStats;

//  命令音频队列和识别时间戳 / Command audio queue and recognition timestamps
OmiPetAudio::PcmAudioFrameBuffer gCommandAudioBuffer;  //  送入 AFE/MultiNet 的 PCM 帧队列 / PCM frame queue feeding AFE/MultiNet
int16_t gCommandPcmFrame[OmiPetAudio::kPcmAudioFrameSamples] = {};  //  当前待处理的 PCM 帧 / Current PCM frame being processed
uint32_t gCommandFrameCount = 0;  //  已处理的命令 PCM 帧数量 / Number of processed command PCM frames
uint32_t gLastAudioFrameLogMs = 0;  //  上一次音频帧日志时间 / Last audio-frame log time
uint32_t gSpeechStartAtMs = 0;  //  当前语音片段开始时间 / Start time of the current speech segment
uint32_t gSpeechStopAtMs = 0;  //  当前语音片段结束时间 / End time of the current speech segment
uint32_t gWakeAcceptedAtMs = 0;  //  最近一次唤醒被状态机接受的时间 / Time when the latest wake was accepted
bool gSpeechTimingValid = false;  //  当前语音时间戳是否有效 / Whether current speech timestamps are valid
bool gWakeLightActive = false;  //  唤醒后等待指令时显示独立的白色跑马灯 / Show an independent white sweep while awaiting a command
#if OMIPET_DESKTOP_CONTROL
bool gVoiceLightAppliedThisLoop = false;  //  同一轮循环内语音动作优先于上位机设置 / Give a voice action priority over desktop settings in the same loop
#endif
OmiPetLed::EffectController gWakeEffects(OmiPetLed::strip);  //  避免唤醒提示改写原本灯效 / Keep the wake indication separate from the saved local effect
#if OMIPET_WIFI_CONTROL
OmiPetProtocol::MonitorTransportSelection gMonitorTransport;
#endif

#if OMIPET_MONITOR_LIGHTS
OmiPetLed::VoiceLightOverride gVoiceLightOverride;  //  语音接管保持到远端退出 / Voice takeover lasts until remote exit
OmiPetLed::LightOwner gLightOwner = OmiPetLed::LightOwner::Local;  //  上一帧的物理输出归属 / Physical output owner of the prior frame
OmiPetLed::MonitorLightStatus gMonitorLightStatus = OmiPetLed::MonitorLightStatus::Unknown;  //  上一帧监控状态 / Prior monitor status
#if OMIPET_DESKTOP_CONTROL && OMIPET_MONITOR_GREEN_OFF
uint32_t gMonitorProfileRevision = UINT32_MAX;
uint8_t gLocalBrightness = 16;
const char* gMonitorProfileStatus = "";
#endif
OmiPetLed::EffectController gMonitorEffects(OmiPetLed::strip);  //  与本地灯效分离的监控扩散时间轴 / Separate monitor-expansion timeline from local effects
#endif

//  唤醒被接受后立即由白色跑马灯接管，保留此前本地灯效供退出时恢复 / Show a white wake sweep immediately and preserve the prior local effect for restoration
void beginWakeLight() {
#if OMIPET_MONITOR_LIGHTS
  if (gLightOwner == OmiPetLed::LightOwner::Monitor) {
    Serial.println("[LED] owner=local reason=voice");
  }
#if OMIPET_DESKTOP_CONTROL && OMIPET_MONITOR_GREEN_OFF
  if (gLightOwner != OmiPetLed::LightOwner::Local) OmiPetLed::strip.setBrightness(gLocalBrightness);
#endif
  gVoiceLightOverride.onVoiceInteraction();
#if OMIPET_MONITOR_GREEN_OFF
  OmiPetProtocol::yieldUsbMonitorToVoice();
#if OMIPET_WIFI_CONTROL
  OmiPetProtocol::yieldWirelessMonitorToVoice();
#endif
#endif
  gLightOwner = OmiPetLed::LightOwner::Local;
#endif
  gWakeLightActive = true;
  gWakeEffects.begin();
  gWakeEffects.setSweep(255, 255, 255);
  Serial.println("[LED] owner=voice effect=sweep color=white");
}

//  唤醒等待结束时重绘原本本地灯效 / Restore the saved local effect when wake listening ends
void finishWakeLight() {
  if (!gWakeLightActive) return;
  gWakeLightActive = false;
  OmiPetLed::effects.refresh();
  Serial.println("[LED] owner=local reason=voice-ended");
}

//  执行一个已识别的灯带命令 / Execute one recognized LED command
bool executeLedCommand(int commandId) {
  using namespace OmiPetAudio;
  switch (commandId) {
    case kIncreaseBrightnessCommandId: {
      const int updatedBrightness = std::max(
          0, std::min(static_cast<int>(OmiPetLed::strip.brightness()) + 16,
                      255));
      OmiPetLed::strip.setBrightness(static_cast<uint8_t>(updatedBrightness));
      OmiPetLed::effects.refresh();
      Serial.printf("[LED] brightness=%d command=increase\n",
                    updatedBrightness);
      return true;
    }
    case kDecreaseBrightnessCommandId: {
      const int updatedBrightness = std::max(
          0, std::min(static_cast<int>(OmiPetLed::strip.brightness()) - 16,
                      255));
      OmiPetLed::strip.setBrightness(static_cast<uint8_t>(updatedBrightness));
      OmiPetLed::effects.refresh();
      Serial.printf("[LED] brightness=%d command=decrease\n",
                    updatedBrightness);
      return true;
    }
    case kRedColorCommandId:
      OmiPetLed::effects.setColor(255, 0, 0);
      Serial.println("[LED] color=red");
      return true;
    case kGreenColorCommandId:
      OmiPetLed::effects.setColor(0, 255, 0);
      Serial.println("[LED] color=green");
      return true;
    case kBlueColorCommandId:
      OmiPetLed::effects.setColor(0, 0, 255);
      Serial.println("[LED] color=blue");
      return true;
    case kYellowColorCommandId:
      OmiPetLed::effects.setColor(255, 160, 0);
      Serial.println("[LED] color=yellow");
      return true;
    case kPurpleColorCommandId:
      OmiPetLed::effects.setColor(180, 0, 255);
      Serial.println("[LED] color=purple");
      return true;
    case kCyanColorCommandId:
      OmiPetLed::effects.setColor(0, 220, 255);
      Serial.println("[LED] color=cyan");
      return true;
    case kWhiteColorCommandId:
      OmiPetLed::effects.setColor(255, 255, 255);
      Serial.println("[LED] color=white");
      return true;
    case kRainbowEffectCommandId:
      OmiPetLed::effects.setRainbow();
      Serial.println("[LED] effect=rainbow");
      return true;
    case kBreatheEffectCommandId:
      OmiPetLed::effects.setBreathe();
      Serial.println("[LED] effect=breathe");
      return true;
    case kSweepEffectCommandId:
      OmiPetLed::effects.setSweep();
      Serial.println("[LED] effect=sweep");
      return true;
    case kCenterExpandEffectCommandId:
      OmiPetLed::effects.setCenterExpand();
      Serial.println("[LED] effect=center_expand");
      return true;
    case kSolidEffectCommandId:
      OmiPetLed::effects.setSolid();
      Serial.println("[LED] effect=solid");
      return true;
    case kOffEffectCommandId:
      OmiPetLed::effects.setOff();
      Serial.println("[LED] effect=off");
      return true;
    default:
      return false;
  }
}

//  计算选定声道的音量统计 / Calculate level statistics for the selected channel
MicLevelStats analyzeMicrophoneLevel(const int32_t* words, size_t wordCount,
                                     OmiPetAudio::MicChannel channel) {
  MicLevelStats stats;
  const size_t selectedSlot = static_cast<size_t>(channel);
  uint64_t absoluteSum = 0;
  uint64_t squareSum = 0;

  const size_t frameCount = wordCount / 2;
  for (size_t frame = 0; frame < frameCount; ++frame) {
    const int32_t rawSample = words[frame * 2 + selectedSlot];
    const int32_t sample = rawSample >> 8;
    const int64_t signedSample = sample;
    const uint64_t magnitude = signedSample < 0
                                   ? static_cast<uint64_t>(-signedSample)
                                   : static_cast<uint64_t>(signedSample);
    absoluteSum += magnitude;
    squareSum += magnitude * magnitude;
    stats.peak = std::max(stats.peak, static_cast<uint32_t>(magnitude));
    ++stats.frameCount;
  }

  if (stats.frameCount == 0U) {
    return stats;
  }

  stats.averageAbsolute =
      static_cast<uint32_t>(absoluteSum / stats.frameCount);
  stats.rms = static_cast<uint32_t>(
      std::sqrt(static_cast<double>(squareSum) / stats.frameCount));
  return stats;
}

//  根据动态噪声底估算语音候选状态 / Estimate speech candidacy from the adaptive noise floor
bool detectSpeech(uint32_t rms, uint32_t& threshold) {
  if (!gMicNoiseFloorInitialized) {
    gMicNoiseFloorRms = rms;
    gMicNoiseFloorInitialized = true;
  }

  const uint32_t thresholdMultiplier = gSpeechActive ? 2U : 3U;
  threshold = std::max(gMicNoiseFloorRms * thresholdMultiplier,
                       gMicNoiseFloorRms + 1000U);
  const uint32_t minimumRms =
      gSpeechActive ? kMinimumSpeechHoldRms : kMinimumSpeechStartRms;
  const bool speechDetected = rms > threshold && rms >= minimumRms;
  if (!speechDetected) {
    gMicNoiseFloorRms = (gMicNoiseFloorRms * 15U + rms) / 16U;
  }
  return speechDetected;
}

//  更新连续语音状态并应用迟滞 / Update continuous speech state with hysteresis
bool updateSpeechState(bool speechCandidate) {
  if (speechCandidate) {
    gSpeechQuietWindows = 0;
    if (!gSpeechActive) {
      if (gSpeechStartWindows < 255U) {
        ++gSpeechStartWindows;
      }
      if (gSpeechStartWindows >= kSpeechStartWindowCount) {
        gSpeechActive = true;
        gSpeechStartWindows = 0;
      }
    }
  } else {
    gSpeechStartWindows = 0;
    if (gSpeechActive) {
      if (gSpeechQuietWindows < 255U) {
        ++gSpeechQuietWindows;
      }
      if (gSpeechQuietWindows >= kSpeechEndWindowCount) {
        gSpeechActive = false;
        gSpeechQuietWindows = 0;
      }
    }
  }
  return gSpeechActive;
}

//  读取麦克风窗口、更新 VAD 状态，并把 PCM 帧送入识别队列 / Read microphone windows, update VAD, and queue PCM frames
//  每 10 ms 处理音频窗口，每秒打印一次诊断状态 / Process an audio window every 10 ms and print diagnostics once per second
void updateMicrophoneDiagnostic() {
  const uint32_t nowMs = millis();
  if (nowMs - gLastMicWindowMs < kMicWindowIntervalMs) {
    return;
  }
  gLastMicWindowMs = nowMs;

  if (!OmiPetAudio::microphone.initialized()) {
    if (nowMs - gLastMicLogMs >= kMicLogIntervalMs) {
      gLastMicLogMs = nowMs;
      Serial.println("[MIC] unavailable");
    }
    return;
  }

  const size_t wordCount = OmiPetAudio::microphone.readRawWords(
      gMicDiagnosticWords, kMicDiagnosticWordCount);
  if (wordCount == 0U) {
    if (nowMs - gLastMicLogMs >= kMicLogIntervalMs) {
      gLastMicLogMs = nowMs;
      Serial.println("[MIC] no samples");
    }
    return;
  }

  gLastMicStats = analyzeMicrophoneLevel(
      gMicDiagnosticWords, wordCount, OmiPetAudio::microphone.channel());
  if (OmiPetAudio::multiNetCommandRecognizer.available()) {
    //  无论是否允许识别，都先把音频送入 AFE 处理链 / Always feed audio into the AFE pipeline, even when detection is gated off
    gCommandAudioBuffer.pushInterleavedWords(
        gMicDiagnosticWords, wordCount, OmiPetAudio::microphone.channel());
  }
  const bool speechWasActive = gSpeechActive;
  if (OmiPetVoice::voice.speechInputSuppressed()) {
    gLastSpeechCandidate = false;
    gSpeechActive = false;
    gSpeechStartWindows = 0;
    gSpeechQuietWindows = 0;
  } else {
    gLastSpeechCandidate =
        detectSpeech(gLastMicStats.rms, gLastMicThreshold);
    if (gLastSpeechCandidate) {
      gLastSpeechActivityMs = nowMs;
    }
    updateSpeechState(gLastSpeechCandidate);
  }
  if (speechWasActive != gSpeechActive) {
    Serial.printf("[VAD] event=%s rms=%lu threshold=%lu\n",
                  gSpeechActive ? "start" : "stop",
                  static_cast<unsigned long>(gLastMicStats.rms),
                  static_cast<unsigned long>(gLastMicThreshold));
    if (gSpeechActive) {
      gSpeechStartAtMs = nowMs;
      gSpeechTimingValid = true;
      Serial.printf("[TIMING] speech_start ms=%lu\n",
                    static_cast<unsigned long>(gSpeechStartAtMs));
    } else {
      gSpeechStopAtMs = nowMs;
      Serial.printf("[TIMING] speech_stop ms=%lu duration_ms=%lu\n",
                    static_cast<unsigned long>(gSpeechStopAtMs),
                    gSpeechTimingValid
                        ? static_cast<unsigned long>(gSpeechStopAtMs -
                                                     gSpeechStartAtMs)
                        : 0UL);
    }
  }
  if (nowMs - gLastMicLogMs < kMicLogIntervalMs) {
    return;
  }
  gLastMicLogMs = nowMs;
  Serial.printf(
      "[MIC] frames=%u avg_abs=%lu rms=%lu peak=%lu noise=%lu threshold=%lu candidate=%s speech=%s start=%u quiet=%u\n",
      static_cast<unsigned>(gLastMicStats.frameCount),
      static_cast<unsigned long>(gLastMicStats.averageAbsolute),
      static_cast<unsigned long>(gLastMicStats.rms),
      static_cast<unsigned long>(gLastMicStats.peak),
      static_cast<unsigned long>(gMicNoiseFloorRms),
      static_cast<unsigned long>(gLastMicThreshold),
      gLastSpeechCandidate ? "yes" : "no",
      gSpeechActive ? "yes" : "no",
      static_cast<unsigned>(gSpeechStartWindows),
      static_cast<unsigned>(gSpeechQuietWindows));
}

//  将连续采集的 PCM 帧送入离线命令识别器 / Submit continuously captured PCM frames to the offline command recognizer
//  AFE 始终接收音频，allowDetection 只控制 MultiNet 是否实际判定 / AFE always receives audio; allowDetection only gates MultiNet decisions
void updateCommandAudioFrames() {
  size_t processedFrameCount = 0;
  while (processedFrameCount < kMaxCommandFramesPerLoop &&
         gCommandAudioBuffer.popFrame(
             gCommandPcmFrame, OmiPetAudio::kPcmAudioFrameSamples)) {
    ++processedFrameCount;
    const uint32_t nowMs = millis();
    //  AFE 持续运行，但只有语音活动或尾窗内才调用 MultiNet 推理 / Keep AFE running continuously, but invoke MultiNet only during speech or hangover
    const bool speechDetectionWindowOpen =
        gSpeechActive ||
        (gLastSpeechActivityMs != 0U &&
         nowMs - gLastSpeechActivityMs <= kSpeechDetectionHangoverMs);
    const bool allowDetection =
        speechDetectionWindowOpen &&
        !OmiPetVoice::voice.speechInputSuppressed();
    const uint32_t detectStartedAtMs = millis();
    const int commandId = OmiPetAudio::multiNetCommandRecognizer.processFrame(
        gCommandPcmFrame, OmiPetAudio::kPcmAudioFrameSamples,
        allowDetection);
    const uint32_t detectFinishedAtMs = millis();
    //  自定义词 ID=1 作为待机入口，识别后清空上一段模型上下文 / Use custom phrase ID 1 as the idle entry and clear the previous model context
    if (commandId == OmiPetAudio::kWakePhraseCommandId &&
        OmiPetVoice::voice.state() == OmiPetVoice::VoiceState::Idle) {
      const uint32_t speechAgeMs =
          gSpeechTimingValid ? detectFinishedAtMs - gSpeechStartAtMs : 0U;
      const uint32_t speechStopAgeMs =
          gSpeechTimingValid && gSpeechStopAtMs >= gSpeechStartAtMs
              ? detectFinishedAtMs - gSpeechStopAtMs
              : 0U;
      Serial.printf(
          "[TIMING] wake_result ms=%lu infer_ms=%lu since_speech_start_ms=%lu "
          "since_speech_stop_ms=%lu\n",
          static_cast<unsigned long>(detectFinishedAtMs),
          static_cast<unsigned long>(detectFinishedAtMs - detectStartedAtMs),
          static_cast<unsigned long>(speechAgeMs),
          static_cast<unsigned long>(speechStopAgeMs));
      OmiPetAudio::multiNetCommandRecognizer.reset();
      gCommandAudioBuffer.reset();
      Serial.println("[VOICE] continuous wake phrase detected");
      if (OmiPetVoice::voice.notifyWakeWordDetected()) {
        beginWakeLight();
        gWakeAcceptedAtMs = millis();
        Serial.printf("[TIMING] wake_accepted ms=%lu\n",
                      static_cast<unsigned long>(gWakeAcceptedAtMs));
      }
      continue;
    }
    //  配对只由唤醒后的本机语音命令开放，不通过网络重置身份 / Open pairing only from a post-wake local voice command; never reset identity over the network
    if (OmiPetVoice::voice.listeningForCommand() && commandId == OmiPetAudio::kOpenPairingModeCommandId) {
      bool requested = false;
#if OMIPET_WIFI_PAIRING
      requested = OmiPetPairing::requestWirelessPairing();
#else
      Serial.println("[PAIR] open=0 reason=feature-disabled");
#endif
      finishWakeLight();
      OmiPetAudio::multiNetCommandRecognizer.reset();
      gCommandAudioBuffer.reset();
      OmiPetVoice::voice.notifyCommandCompleted();
      if (!requested) OmiPetUi::setVoiceStatus("PAIR UNREADY");
      continue;
    }
    //  唤醒后接受灯带控制命令，执行成功后回到持续监听 / Accept LED commands after wake-up, then return to continuous listening
    if (OmiPetVoice::voice.listeningForCommand() &&
        commandId >= OmiPetAudio::kIncreaseBrightnessCommandId &&
        commandId <= OmiPetAudio::kCenterExpandEffectCommandId) {
      const uint32_t speechAgeMs =
          gSpeechTimingValid ? detectFinishedAtMs - gSpeechStartAtMs : 0U;
      const uint32_t wakeAgeMs = gWakeAcceptedAtMs != 0U
                                      ? detectFinishedAtMs - gWakeAcceptedAtMs
                                      : 0U;
      Serial.printf(
          "[TIMING] command_result ms=%lu infer_ms=%lu "
          "since_speech_start_ms=%lu since_wake_accepted_ms=%lu\n",
          static_cast<unsigned long>(detectFinishedAtMs),
          static_cast<unsigned long>(detectFinishedAtMs - detectStartedAtMs),
          static_cast<unsigned long>(speechAgeMs),
          static_cast<unsigned long>(wakeAgeMs));
      //  命令在保留的本地灯效上执行，唤醒提示只在等待阶段显示 / Apply the command to the saved local effect; the wake sweep lasts only while listening
      const bool hadWakeLight = gWakeLightActive;
      gWakeLightActive = false;
      const bool executed = executeLedCommand(commandId);
      if (!executed) {
        gWakeLightActive = hadWakeLight;
        continue;
      }
#if OMIPET_DESKTOP_CONTROL
      gVoiceLightAppliedThisLoop = true;
#endif
      if (hadWakeLight) OmiPetLed::effects.refresh();
      Serial.printf("[TIMING] command_executed ms=%lu detect_to_led_ms=%lu\n",
                    static_cast<unsigned long>(millis()),
                    static_cast<unsigned long>(millis() - detectFinishedAtMs));
      OmiPetAudio::multiNetCommandRecognizer.reset();
      gCommandAudioBuffer.reset();
      OmiPetVoice::voice.notifyCommandCompleted();
    }
    //  每帧主动让出 CPU，确保系统空闲任务和看门狗获得调度 / Yield after each frame so idle tasks and the watchdog can run
    yield();
  }
  gCommandFrameCount += static_cast<uint32_t>(processedFrameCount);

  const uint32_t nowMs = millis();
  if (nowMs - gLastAudioFrameLogMs < kMicLogIntervalMs) {
    return;
  }
  gLastAudioFrameLogMs = nowMs;
  Serial.printf(
      "[AUDIO] command_frames=%lu samples_per_frame=%u rate=%lu channel=right queued=%u dropped=%lu\n",
      static_cast<unsigned long>(gCommandFrameCount),
      static_cast<unsigned>(OmiPetAudio::kPcmAudioFrameSamples),
      static_cast<unsigned long>(OmiPetAudio::kMicDefaultSampleRateHz),
      static_cast<unsigned>(gCommandAudioBuffer.queuedFrames()),
      static_cast<unsigned long>(gCommandAudioBuffer.droppedFrames()));
}
//  仅由帧外调试输入触发现有唤醒测试行为 / Trigger existing wake testing only from debug input outside protocol frames
void triggerVoiceDebugWake() {
  if (OmiPetVoice::voice.state() == OmiPetVoice::VoiceState::Idle) {
    gCommandAudioBuffer.reset();
    OmiPetAudio::multiNetCommandRecognizer.reset();
    Serial.println("[VOICE] serial wake trigger (debug fallback; continuous recognition active)");
    if (OmiPetVoice::voice.notifyWakeWordDetected()) beginWakeLight();
  }
}

//  实验关闭时保留原串口入口，开启时先隔离完整帧 / Preserve the original input path when disabled and isolate complete frames when enabled
void updateVoiceDebugInput() {
#if OMIPET_PROTOCOL_EXPERIMENT
  bool localLightAllowed = !gWakeLightActive;
#if OMIPET_DESKTOP_CONTROL
  localLightAllowed = localLightAllowed && !gVoiceLightAppliedThisLoop;
#endif
#if OMIPET_WIFI_CONTROL
  const bool wifiMonitor = OmiPetProtocol::monitorSessionActive(OmiPetProtocol::wirelessControlView()) &&
                           OmiPetProtocol::wirelessMonitorOutput() == OmiPetProtocol::MonitorOutput::Connected;
  OmiPetProtocol::pollSerialExperiment(triggerVoiceDebugWake, localLightAllowed && !wifiMonitor,
                                       wifiMonitor ? "monitor-mode-active" : "voice-active");
  const bool usbActive = OmiPetProtocol::usbExperimentView().leaseActive;
  OmiPetProtocol::pollWirelessControl(OmiPetNetwork::wifi.connected(), localLightAllowed && !gWakeLightActive && !usbActive,
                                      usbActive ? "usb-priority" : "voice-active");
  if (OmiPetProtocol::takeWirelessLocalSelection()) gMonitorTransport.local(OmiPetProtocol::MonitorTransport::Wifi);
  if (OmiPetProtocol::takeUsbLocalSelection()) gMonitorTransport.local(OmiPetProtocol::MonitorTransport::Usb);
#else
  OmiPetProtocol::pollSerialExperiment(triggerVoiceDebugWake, localLightAllowed);
#endif
#else
  while (Serial.available() > 0) {
    if (Serial.read() == 'w') triggerVoiceDebugWake();
  }
#endif
}
#if OMIPET_DESKTOP_CONTROL
//  仅应用新修订的本地命令，监控和唤醒期间由协议拒绝手动设置 / Apply only a new local-command revision; the protocol rejects manual settings during monitoring or wake listening
void updateDesktopLightCommand() {
  static uint32_t appliedRevision = 0;
  OmiPetProtocol::LocalLightCommand command = OmiPetProtocol::usbLocalLightCommand();
#if OMIPET_WIFI_CONTROL
  static uint32_t wifiRevision = 0;
  const auto wifi = OmiPetProtocol::wirelessLocalLightCommand();
  const bool usbChanged = command.revision != 0 && command.revision != appliedRevision;
  const bool wifiChanged = wifi.revision != 0 && wifi.revision != wifiRevision;
  appliedRevision = command.revision; wifiRevision = wifi.revision;
  if (!usbChanged && !wifiChanged) return;
  if (!usbChanged) command = wifi;
#else
  if (command.revision == 0 || command.revision == appliedRevision) return;
  appliedRevision = command.revision;
#endif
  using namespace OmiPetLed;
#if OMIPET_MONITOR_LIGHTS && OMIPET_MONITOR_GREEN_OFF
  gLocalBrightness = command.brightness;
#endif
  using OmiPetProtocol::LocalLightEffect;
  strip.setBrightness(command.brightness);
  EffectMode mode = EffectMode::Solid;
  switch (command.effect) {
    case LocalLightEffect::Solid: mode = EffectMode::Solid; break;
    case LocalLightEffect::Rainbow: mode = EffectMode::Rainbow; break;
    case LocalLightEffect::Breathe: mode = EffectMode::Breathe; break;
    case LocalLightEffect::Sweep: mode = EffectMode::Sweep; break;
    case LocalLightEffect::CenterExpand: mode = EffectMode::CenterExpand; break;
    case LocalLightEffect::Off: mode = EffectMode::Off; break;
  }
  effects.setConfiguration(mode, command.red, command.green, command.blue);
  Serial.printf("[LED] owner=desktop revision=%lu effect=%u rgb=%u,%u,%u brightness=%u\n",
                static_cast<unsigned long>(command.revision), static_cast<unsigned>(command.effect),
                command.red, command.green, command.blue, command.brightness);
}
#endif
#if OMIPET_MONITOR_LIGHTS
//  仅在隔离构建中把有效协议状态映射到实体灯带 / Map valid protocol state to physical LEDs only in isolated builds
void updateMonitorLights() {
  using namespace OmiPetLed;
  OmiPetProtocol::SessionView view = OmiPetProtocol::usbExperimentView();
  auto monitorOutput = OmiPetProtocol::usbMonitorOutput();
  const auto* taskScreen = OmiPetProtocol::usbTaskScreen();
#if OMIPET_WIFI_CONTROL
  const auto wifi = OmiPetProtocol::wirelessControlView();
  if (gMonitorTransport.select(view, wifi, true) == OmiPetProtocol::MonitorTransport::Wifi) {
    view = wifi;
    monitorOutput = OmiPetProtocol::wirelessMonitorOutput();
    taskScreen = OmiPetProtocol::wirelessTaskScreen();
  }
#endif
  const bool voiceOverride = gVoiceLightOverride.observe(view);
  OmiPetUi::setTaskScreen(monitorOutput != OmiPetProtocol::MonitorOutput::Local && !voiceOverride && !gWakeLightActive,
                         monitorOutput == OmiPetProtocol::MonitorOutput::Connected, taskScreen);
  if (gWakeLightActive) return;
#if OMIPET_MONITOR_GREEN_OFF
  const LightArbitrationPolicy policy{LightFallback::Green, LightFallback::Green};
  const LightDecision decision = arbitrateLight(view, voiceOverride, policy, monitorOutput);
#else
  const LightArbitrationPolicy policy{LightFallback::Local, LightFallback::Local};
  const LightDecision decision = arbitrateLight(view, voiceOverride, policy);
#endif
  if (decision.owner == LightOwner::Off) {
    if (gLightOwner != LightOwner::Off) {
      strip.clear();
      Serial.println("[LED] owner=off reason=monitor-disconnected");
    }
    gLightOwner = LightOwner::Off;
    gMonitorLightStatus = MonitorLightStatus::Unknown;
    return;
  }
  if (decision.owner != LightOwner::Monitor) {
    if (gLightOwner != LightOwner::Local) {
#if OMIPET_DESKTOP_CONTROL && OMIPET_MONITOR_GREEN_OFF
      strip.setBrightness(gLocalBrightness);
#endif
      effects.refresh();
      Serial.printf("[LED] owner=local reason=%s\n", voiceOverride ? "voice" : "fallback");
    }
    gLightOwner = LightOwner::Local;
    gMonitorLightStatus = MonitorLightStatus::Unknown;
    return;
  }
#if OMIPET_DESKTOP_CONTROL && OMIPET_MONITOR_GREEN_OFF
  const auto& profiles = OmiPetProtocol::monitorProfiles.current();
  if (gLightOwner != LightOwner::Monitor || std::strcmp(gMonitorProfileStatus, view.displayStatus) != 0 ||
      gMonitorProfileRevision != profiles.revision) {
    if (gLightOwner == LightOwner::Local) gLocalBrightness = strip.brightness();
    const auto& light = profiles.forStatus(view.displayStatus);
    strip.setBrightness(light.brightness);
    gMonitorEffects.begin();
    gMonitorEffects.setConfiguration(static_cast<EffectMode>(light.effect), light.red, light.green, light.blue);
    gMonitorProfileRevision = profiles.revision;
    gMonitorProfileStatus = view.displayStatus;
    Serial.printf("[LED] owner=monitor status=%s profile_revision=%lu effect=%u brightness=%u\n",
      view.displayStatus, static_cast<unsigned long>(profiles.revision), static_cast<unsigned>(light.effect), light.brightness);
  }
#else
  if (gLightOwner != LightOwner::Monitor || gMonitorLightStatus != decision.status) {
    MonitorLightRgb color{};
    if (!monitorLightRgb(decision.status, color)) return;
    if (gLightOwner != LightOwner::Monitor) {
      gMonitorEffects.begin();
      gMonitorEffects.setCenterExpand(color.red, color.green, color.blue);
    } else {
      gMonitorEffects.setColor(color.red, color.green, color.blue);
    }
    Serial.printf("[LED] owner=monitor effect=center_expand status=%s brightness=%u\n", view.displayStatus,
                  static_cast<unsigned>(strip.brightness()));
  }
#endif
  gLightOwner = LightOwner::Monitor;
  gMonitorLightStatus = decision.status;
}
#endif
void refreshNetworkAndTimeUi() {
  const bool wifiConnected = OmiPetNetwork::wifi.connected();
  OmiPetTime::ntp.update(wifiConnected);
  const OmiPetTime::DateTime currentDateTime = OmiPetTime::ntp.current();
  OmiPetUi::setDateTime(currentDateTime.valid, currentDateTime.year,
                        currentDateTime.month, currentDateTime.day,
                        currentDateTime.hour, currentDateTime.minute);
  const String currentWifiSsid = OmiPetNetwork::wifi.ssid();
  OmiPetUi::setNetworkStatus(wifiConnected,
                             OmiPetNetwork::wifi.provisioning(),
                             currentWifiSsid.c_str());
}
//  持续输出系统心跳，帮助区分识别失败和系统停滞 / Print a persistent heartbeat to distinguish recognition failures from a stalled system
void updateSystemHeartbeat() {
  if (millis() - gLastSystemHeartbeatMs < 2000U) {
    return;
  }
  gLastSystemHeartbeatMs = millis();
  Serial.printf("[SYS] alive ms=%lu mic=%s wifi=%s\n",
                static_cast<unsigned long>(millis()),
                OmiPetAudio::microphone.initialized() ? "ok" : "off",
                OmiPetNetwork::wifi.connected() ? "connected" : "offline");
#if OMIPET_PROTOCOL_USB
  OmiPetProtocol::reportUsbExperiment();
#endif
}

}  //  匿名命名空间 / Anonymous namespace

//  初始化所有硬件驱动和业务模块 / Initialize all hardware drivers and application modules
void setup() {
#if OMIPET_PROTOCOL_USB
  OmiPetProtocol::configureUsbExperiment();
#endif
  Serial.begin(115200);
  delay(1500);
  Serial.println("[BOOT] setup entered");
  Serial.flush();

  //  初始化灯带和非阻塞动效 / Initialize the strip and non-blocking effects
#if OMIPET_DESKTOP_CONTROL && OMIPET_MONITOR_LIGHTS && OMIPET_MONITOR_GREEN_OFF
  OmiPetProtocol::beginMonitorProfiles();
#endif
  OmiPetLed::strip.begin(16);
  OmiPetLed::effects.begin();
  OmiPetLed::effects.setRainbow();

  //  初始化无源蜂鸣器，但不自动播放声音 / Initialize the passive buzzer without playing sound automatically
  OmiPetBuzzer::buzzer.begin();
  OmiPetVoice::voice.begin();
  //  在启动 Wi-Fi 前先采集一次电池电压 / Take an initial battery reading before starting Wi-Fi
  OmiPetBattery::battery.begin();
  const OmiPetBattery::BatteryMeasurement& initialBatteryReading =
      OmiPetBattery::battery.measurement();
  OmiPetUi::setBatteryStatus(initialBatteryReading.percent,
                             initialBatteryReading.valid);

  //  初始化 LCD 并打开背光 / Initialize the LCD and enable the backlight
  OmiPetDisplay::lcd.begin(8000000UL);
  OmiPetDisplay::lcd.setBacklight(true);

  //  初始化 AHT20 并尝试获取首个测量值 / Initialize AHT20 and try to obtain the first measurement
  const bool sensorReady = OmiPetSensor::aht20.begin();
  if (sensorReady) {
    OmiPetSensor::aht20.readMeasurement();
  }
  const OmiPetSensor::Aht20Measurement& initialReading =
      OmiPetSensor::aht20.measurement();
  OmiPetUi::setEnvironment(initialReading.temperatureC,
                           initialReading.humidityPercent,
                           initialReading.valid && !initialReading.stale);
  //  初始化联网时间服务，未同步前显示占位符 / Initialize network time service and show placeholders until synchronized
  OmiPetTime::ntp.begin();
  OmiPetUi::setDateTime(false, 0, 0, 0, 0, 0);
  //  先绘制界面，再执行可能等待 Wi-Fi 的连接流程 / Draw the UI before starting the potentially waiting Wi-Fi connection flow
  OmiPetUi::setNetworkStatus(false, false, nullptr);
  OmiPetUi::begin();

  //  初始化 Wi-Fi；无已保存配置时开启网页配网热点 / Initialize Wi-Fi; start the web portal when no saved configuration exists
  OmiPetNetwork::wifi.begin();
  OmiPetTime::ntp.update(OmiPetNetwork::wifi.connected());
  const OmiPetTime::DateTime initialDateTime = OmiPetTime::ntp.current();
  OmiPetUi::setDateTime(initialDateTime.valid, initialDateTime.year,
                        initialDateTime.month, initialDateTime.day,
                        initialDateTime.hour, initialDateTime.minute);
  const String initialWifiSsid = OmiPetNetwork::wifi.ssid();
  OmiPetUi::setNetworkStatus(OmiPetNetwork::wifi.connected(),
                             OmiPetNetwork::wifi.provisioning(),
                             initialWifiSsid.c_str());
  //  初始化麦克风采集诊断 / Initialize the microphone capture diagnostic
  //  当前硬件使用右声道槽 / The current hardware uses the right I2S slot
  const bool microphoneReady = OmiPetAudio::microphone.begin(
      OmiPetAudio::kMicDefaultSampleRateHz, OmiPetAudio::MicChannel::Right);
  Serial.printf("[MIC] init=%s rate=%lu sck=%u ws=%u sd=%u\n",
                microphoneReady ? "ok" : "failed",
                static_cast<unsigned long>(OmiPetAudio::microphone.sampleRateHz()),
                static_cast<unsigned>(OmiPetAudio::kMicSckPin),
                static_cast<unsigned>(OmiPetAudio::kMicWsPin),
                static_cast<unsigned>(OmiPetAudio::kMicSdPin));

  const bool recognizerReady = OmiPetAudio::multiNetCommandRecognizer.begin(
      OmiPetAudio::kMicDefaultSampleRateHz, OmiPetAudio::kPcmAudioFrameSamples);
  Serial.printf("[ASR] init=%s frame=%u\n",
                recognizerReady ? "ready" : "unavailable",
                static_cast<unsigned>(OmiPetAudio::kPcmAudioFrameSamples));
}

//  按固定顺序执行非阻塞更新：网络、灯效、采集、识别、传感器和 UI / Run non-blocking updates in order: network, effects, capture, recognition, sensors, and UI
void loop() {
#if OMIPET_DESKTOP_CONTROL
  gVoiceLightAppliedThisLoop = false;
#endif
  //  处理 WiFiManager 网页配网和连接状态 / Process WiFiManager provisioning and connection state
  OmiPetNetwork::wifi.update();
#if OMIPET_WIFI_PAIRING
  OmiPetPairing::updateWirelessPairing(OmiPetNetwork::wifi.connected());
#endif
  refreshNetworkAndTimeUi();
  //  先推进灯效，避免语音识别处理占用主循环时延后动画刷新 / Advance effects first so speech processing delays animation refresh less
#if OMIPET_MONITOR_LIGHTS
  if (gWakeLightActive) gWakeEffects.update();
  else if (gLightOwner == OmiPetLed::LightOwner::Monitor) gMonitorEffects.update();
  else if (gLightOwner == OmiPetLed::LightOwner::Local) OmiPetLed::effects.update();
#else
  if (gWakeLightActive) gWakeEffects.update();
  else OmiPetLed::effects.update();
#endif
  updateSystemHeartbeat();
  updateMicrophoneDiagnostic();
  updateCommandAudioFrames();
  updateVoiceDebugInput();
#if OMIPET_DESKTOP_CONTROL
  updateDesktopLightCommand();
#endif
#if OMIPET_MONITOR_LIGHTS
  updateMonitorLights();
#endif
  const bool wasListeningForCommand =
      OmiPetVoice::voice.listeningForCommand();
  OmiPetVoice::voice.update(gSpeechActive);
  if (wasListeningForCommand &&
      !OmiPetVoice::voice.listeningForCommand()) {
    finishWakeLight();
    OmiPetAudio::multiNetCommandRecognizer.reset();
    gCommandAudioBuffer.reset();
  }
  refreshNetworkAndTimeUi();
  //  每 5 秒读取一次温湿度，降低传感器自热和总线占用 / Read every 5 seconds to reduce sensor self-heating and bus usage
  static uint32_t lastSensorReadMs = millis();
  if (millis() - lastSensorReadMs >= 5000U) {
    lastSensorReadMs = millis();
    OmiPetSensor::aht20.readMeasurement();
    const OmiPetSensor::Aht20Measurement& reading =
        OmiPetSensor::aht20.measurement();
    OmiPetUi::setEnvironment(reading.temperatureC, reading.humidityPercent,
                             reading.valid && !reading.stale);
  }
  if (OmiPetBattery::battery.update()) {
    const OmiPetBattery::BatteryMeasurement& batteryReading =
        OmiPetBattery::battery.measurement();
    OmiPetUi::setBatteryStatus(batteryReading.percent,
                               batteryReading.valid);
    if (batteryReading.lastReadSucceeded) {
      Serial.printf("[BAT] voltage=%.3fV percent=%u adc_gpio=%u sample=ok\n",
                    batteryReading.voltageV,
                    static_cast<unsigned>(batteryReading.percent),
                    static_cast<unsigned>(OmiPetBattery::kBatteryAdcPin));
    } else {
      Serial.printf("[BAT] sample=failed adc_gpio=%u valid=%s\n",
                    static_cast<unsigned>(OmiPetBattery::kBatteryAdcPin),
                    batteryReading.valid ? "stale" : "no");
    }
  }
  //  维护蜂鸣器非阻塞播放状态 / Maintain the buzzer's non-blocking playback state
  OmiPetBuzzer::buzzer.update();
  OmiPetUi::update();
}
