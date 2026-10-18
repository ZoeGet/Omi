#pragma once

#include <cstddef>

namespace OmiPetAudio {

struct VoiceCommandPhrase {
  int commandId;
  const char* phonemes;
};

//  个人语音命令配置入口；修改或新增命令后直接编译即可自动同步词表并打包模型 / Personal voice-command configuration entry; edit or add commands here, then build to synchronize the phrase list and package the model automatically
constexpr VoiceCommandPhrase kVoiceCommandPhrases[] = {
    {1, "lao shu fei fei"},  //  自定义唤醒词 / Custom wake phrase
    {2, "liang yi dian"},  //  增加亮度 / Increase brightness
    {2, "tiao liang yi dian"},  //  调亮一点 / Make it brighter
    {2, "zeng jia liang du"},  //  增加亮度同义表达 / Increase-brightness synonym
    {2, "ba deng tiao liang"},  //  增加亮度同义表达 / Increase-brightness synonym
    {2, "deng tai an le tiao liang"},  //  灯太暗了调亮 / Make the light brighter because it is too dim
    {3, "an yi dian"},  //  降低亮度 / Decrease brightness
    {3, "tiao an yi dian"},  //  调暗一点 / Make it dimmer
    {3, "jiang di liang du"},  //  降低亮度同义表达 / Decrease-brightness synonym
    {3, "ba deng tiao an"},  //  降低亮度同义表达 / Decrease-brightness synonym
    {3, "deng tai liang le tiao an"},  //  灯太亮了调暗 / Make the light dimmer because it is too bright
    {4, "hong se"},  //  红色 / Red
    {4, "hong se deng guang"},  //  红色灯光 / Red light
    {4, "hong se deng"},  //  红色灯 / Red light
    {5, "lv se"},  //  绿色 / Green
    {5, "lv se deng guang"},  //  绿色灯光 / Green light
    {5, "lv se deng"},  //  绿色灯 / Green light
    {6, "lan se"},  //  蓝色 / Blue
    {6, "lan se deng guang"},  //  蓝色灯光 / Blue light
    {6, "lan se deng"},  //  蓝色灯 / Blue light
    {7, "huang se"},  //  黄色 / Yellow
    {7, "huang se deng guang"},  //  黄色灯光 / Yellow light
    {7, "huang se deng"},  //  黄色灯 / Yellow light
    {8, "zi se"},  //  紫色 / Purple
    {8, "zi se deng guang"},  //  紫色灯光 / Purple light
    {8, "zi se deng"},  //  紫色灯 / Purple light
    {9, "qing se"},  //  青色 / Cyan
    {9, "qing se deng guang"},  //  青色灯光 / Cyan light
    {9, "qing se deng"},  //  青色灯 / Cyan light
    {10, "bai se"},  //  白色 / White
    {10, "bai se deng guang"},  //  白色灯光 / White light
    {10, "bai se deng"},  //  白色灯 / White light
    {11, "cai se"},  //  彩色 / Colorful
    {11, "cai se deng guang"},  //  彩色灯光 / Colorful lights
    {11, "cai se deng"},  //  彩色灯 / Colorful lights
    {12, "hu xi deng"},  //  呼吸灯 / Breathing lights
    {12, "hu xi deng guang"},  //  呼吸灯光 / Breathing light effect
    {13, "pao ma deng"},  //  跑马灯 / Running lights
    {13, "pao ma deng guang"},  //  跑马灯光 / Running light effect
    {14, "kai deng"},  //  开灯 / Turn on the lights
    {14, "kai qi deng guang"},  //  开启灯光 / Turn on the lighting
    {14, "yi zhi liang"},  //  一直亮 / Stay on
    {15, "guan deng"},  //  关灯 / Turn off the lights
    {15, "guan bi deng guang"},  //  关闭灯光 / Turn off the lighting
    {16, "kuo san deng"},  //  扩散灯 / Expanding lights
    {16, "kuo san deng guang"},  //  扩散灯光 / Expanding light effect
    {17, "kai qi pei dui mo shi"},  //  开启配对模式 / Open pairing mode
};

constexpr size_t kVoiceCommandPhraseCount =
    sizeof(kVoiceCommandPhrases) / sizeof(kVoiceCommandPhrases[0]);

}  //  OmiPetAudio 命名空间 / OmiPetAudio namespace
