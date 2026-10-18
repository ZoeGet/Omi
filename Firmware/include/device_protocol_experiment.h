#pragma once

#include "protocol_experiment_config.h"
#if OMIPET_PROTOCOL_USB
#include "device_protocol_session.h"
#endif

#if OMIPET_PROTOCOL_EXPERIMENT
namespace OmiPetProtocol {

//  有界处理完整串口协议帧，非协议输入交给调试回调 / Process complete serial protocol frames within a budget; route nonprotocol input to the debug callback
void pollSerialExperiment(void (*debugWake)(), bool localLightAllowed = true, const char* reason = "voice-active");

#if OMIPET_PROTOCOL_USB
//  串口 begin 前设置实验缓冲，启动后只读汇报运行状态 / Configure experimental buffers before serial begin and report runtime state afterward
bool configureUsbExperiment();
void reportUsbExperiment();
//  提供当前逻辑状态供隔离灯光仲裁读取 / Expose the current logical state for isolated LED arbitration
SessionView usbExperimentView();
LocalLightCommand usbLocalLightCommand();
MonitorOutput usbMonitorOutput();
void yieldUsbMonitorToVoice();
bool takeUsbLocalSelection();
#endif

}  //  协议命名空间 / Protocol namespace
#endif
