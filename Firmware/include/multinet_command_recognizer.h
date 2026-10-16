#pragma once

#include <Arduino.h>

#include <cstddef>
#include <cstdint>

namespace OmiPetAudio {

//  命令 ID 是稳定的业务接口；词表中的 ID=1 行是唯一唤醒词配置入口 / Command IDs are stable business interfaces; the ID=1 row in the phrase file is the single wake-phrase configuration entry
constexpr int kWakePhraseCommandId = 1;  //  自定义唤醒词命令 ID / Custom wake-phrase command ID
constexpr int kIncreaseBrightnessCommandId = 2;  //  增加亮度命令 ID / Increase-brightness command ID
constexpr int kDecreaseBrightnessCommandId = 3;  //  降低亮度命令 ID / Decrease-brightness command ID
constexpr int kRedColorCommandId = 4;  //  红色命令 ID / Red color command ID
constexpr int kGreenColorCommandId = 5;  //  绿色命令 ID / Green color command ID
constexpr int kBlueColorCommandId = 6;  //  蓝色命令 ID / Blue color command ID
constexpr int kYellowColorCommandId = 7;  //  黄色命令 ID / Yellow color command ID
constexpr int kPurpleColorCommandId = 8;  //  紫色命令 ID / Purple color command ID
constexpr int kCyanColorCommandId = 9;  //  青色命令 ID / Cyan color command ID
constexpr int kWhiteColorCommandId = 10;  //  白色命令 ID / White color command ID
constexpr int kRainbowEffectCommandId = 11;  //  彩虹动效命令 ID / Rainbow effect command ID
constexpr int kBreatheEffectCommandId = 12;  //  呼吸动效命令 ID / Breathing effect command ID
constexpr int kSweepEffectCommandId = 13;  //  左右扫描动效命令 ID / Left-to-right sweep effect command ID
constexpr int kSolidEffectCommandId = 14;  //  常亮动效命令 ID / Solid effect command ID
constexpr int kOffEffectCommandId = 15;  //  关闭灯带命令 ID / Turn-off command ID
constexpr int kCenterExpandEffectCommandId = 16;  //  中心扩散动效命令 ID / Center-expand effect command ID

class MultiNetCommandRecognizer {
 public:
  //  初始化 AFE、MultiNet 和当前项目的命令词表 / Initialize AFE, MultiNet, and the project's command phrase list
  bool begin(uint32_t sampleRateHz, size_t inputFrameSamples);
  //  始终推进 AFE，按语音活动状态选择是否执行 MultiNet 推理 / Always advance AFE and gate MultiNet inference by speech activity
  int processFrame(const int16_t* samples, size_t sampleCount,
                   bool allowDetection);
  //  清空 AFE 和 MultiNet 的上下文，开始新的语音片段 / Clear AFE and MultiNet state before a new speech segment
  void reset();
  //  查询识别器是否已完成初始化 / Check whether the recognizer is initialized
  bool available() const;

 private:
  void* modelList_ = nullptr;
  void* afeHandle_ = nullptr;
  void* afeData_ = nullptr;
  void* multiNet_ = nullptr;
  void* multiNetData_ = nullptr;
  size_t feedFrameSamples_ = 0;
  size_t fetchFrameSamples_ = 0;
  size_t modelFrameSamples_ = 0;
  size_t feedFramesPerFetch_ = 0;
  size_t feedSamplesSinceFetch_ = 0;
  bool ready_ = false;
};

extern MultiNetCommandRecognizer multiNetCommandRecognizer;

}  //  OmiPetAudio 命名空间 / OmiPetAudio namespace
