#pragma once

#include "protocol_experiment_config.h"
#if OMIPET_PROTOCOL_USB
#include "device_protocol_session.h"
#endif

#if OMIPET_PROTOCOL_EXPERIMENT
namespace OmiPetProtocol {

//  有界处理串口输入，仅完整帧诊断和帧外调试回调 / Process serial input within a budget, diagnosing frames and forwarding only external debug input
void pollSerialExperiment(void (*debugWake)(), bool localLightAllowed = true);

#if OMIPET_PROTOCOL_USB
//  串口 begin 前设置实验缓冲，启动后只读汇报运行状态 / Configure experimental buffers before serial begin and report runtime state afterward
bool configureUsbExperiment();
void reportUsbExperiment();
//  提供当前逻辑状态供隔离灯光仲裁读取 / Expose the current logical state for isolated LED arbitration
SessionView usbExperimentView();
LocalLightCommand usbLocalLightCommand();
MonitorOutput usbMonitorOutput();
void yieldUsbMonitorToVoice();
#endif

}  //  协议命名空间 / Protocol namespace
#endif
