#pragma once

#include <Arduino.h>
#include <Wire.h>

//  分步采样仅用于隔离验证，默认保留同步路径 / Staged sampling is for isolated validation; preserve the synchronous path by default
#ifndef OMIPET_AHT20_ASYNC
#define OMIPET_AHT20_ASYNC 0
#endif
#if OMIPET_AHT20_ASYNC != 0 && OMIPET_AHT20_ASYNC != 1
#error "OMIPET_AHT20_ASYNC must be 0 or 1"
#endif

namespace OmiPetSensor {

//  AHT20 默认 I2C 地址和项目硬件引脚 / AHT20 default I2C address and project hardware pins
constexpr uint8_t kAht20Address = 0x38;  //  AHT20 的 7-bit I2C 地址 / AHT20 7-bit I2C address
constexpr uint8_t kAht20SdaPin = 39;  //  AHT20 I2C SDA 引脚 / AHT20 I2C SDA pin
constexpr uint8_t kAht20SclPin = 38;  //  AHT20 I2C SCL 引脚 / AHT20 I2C SCL pin

//  根据当前整机实测结果设置的现场补偿值，不是 AHT20 手册参数 / Field calibration offsets based on the current assembled device, not AHT20 datasheet values
constexpr float kTemperatureCalibrationOffsetC = -4.0F;  //  温度现场补偿值，单位摄氏度 / Field temperature calibration offset in degrees Celsius
constexpr float kHumidityCalibrationOffsetPercent = 9.0F;  //  湿度现场补偿值，单位百分比 / Field humidity calibration offset in percent

//  AHT20 驱动错误类型 / AHT20 driver error types
enum class Aht20Error : uint8_t {
  None,
  NotInitialized,
  NoResponse,
  WriteFailed,
  StatusReadFailed,
  CalibrationFailed,
  BusyTimeout,
  ShortRead,
  CrcMismatch,
  OutOfRange,
};

//  最近一次温湿度测量结果 / Most recent temperature and humidity measurement
struct Aht20Measurement {
  float temperatureC = 0.0F;
  float humidityPercent = 0.0F;
  uint32_t rawTemperature = 0;
  uint32_t rawHumidity = 0;
  uint8_t status = 0;
  bool valid = false;
  bool stale = true;
  uint32_t timestampMs = 0;
};

//  AHT20 温湿度传感器驱动 / AHT20 temperature and humidity sensor driver
class Aht20Sensor {
 public:
  //  初始化 I2C、检测器件并确认校准状态 / Initialize I2C, probe the device, and verify calibration
  bool begin(TwoWire& wire = Wire, uint8_t sda = kAht20SdaPin,  //  I2C 总线对象和 SDA 引脚 / I2C bus object and SDA pin
             uint8_t scl = kAht20SclPin, uint32_t frequency = 100000UL);  //  SCL 引脚和总线频率 / SCL pin and bus frequency

  //  触发并读取一次测量 / Trigger and read one measurement
  bool readMeasurement();

#if OMIPET_AHT20_ASYNC
  //  开始分步测量，忙碌时不覆盖当前转换 / Start a staged measurement without replacing an active conversion
  bool startMeasurement();
  //  转换等待期间立即返回，成功或失败完成时返回 true；故障恢复沿用同步路径 / Return immediately while converting, true on completion or failure; fault recovery remains synchronous
  bool updateMeasurement();
#endif

  //  获取最近一次测量 / Get the most recent measurement
  const Aht20Measurement& measurement() const;

  //  获取最近一次错误 / Get the most recent error
  Aht20Error lastError() const;

  //  获取连续失败次数 / Get the consecutive failure count
  uint32_t consecutiveFailures() const;

  //  查询驱动是否已初始化 / Check whether the driver is initialized
  bool initialized() const;

 private:
  //  检测 I2C 总线上是否存在传感器 / Check whether the sensor responds on the I2C bus
  bool probe();
  //  读取传感器状态字节 / Read the sensor status byte
  bool readStatus(uint8_t& status);
  //  检查并完成内部校准 / Check and complete internal calibration
  bool ensureCalibration();
  //  发送一个 I2C 命令帧 / Send one I2C command frame
  bool sendCommand(const uint8_t* command, size_t length);
  //  轮询 Busy 状态直到传感器就绪或超时 / Poll Busy status until ready or timeout
  bool waitUntilReady(uint32_t timeoutMs);
  //  读取指定长度的数据帧 / Read a data frame of the requested length
  bool readFrame(uint8_t* frame, size_t length);
  //  同步与分步测量共用读取、校验和补偿 / Share frame reading, validation, and compensation between both sampling paths
  bool finishMeasurement();
  //  执行传感器软复位并重新校准 / Perform a sensor soft reset and recalibration
  bool softReset();
  //  记录错误并保留最近一次有效数据 / Record an error while retaining the last valid data
  bool fail(Aht20Error error);
  //  清除当前错误状态 / Clear the current error state
  void clearError();

  //  计算 AHT20 数据帧 CRC-8 / Calculate the AHT20 data-frame CRC-8
  static uint8_t calculateCrc(const uint8_t* data, size_t length);

  TwoWire* wire_ = nullptr;
  uint8_t sdaPin_ = kAht20SdaPin;
  uint8_t sclPin_ = kAht20SclPin;
  uint32_t frequency_ = 100000UL;
  Aht20Measurement measurement_;
  Aht20Error lastError_ = Aht20Error::None;
  uint32_t consecutiveFailures_ = 0;
  uint32_t lastRecoveryMs_ = 0;
  bool initialized_ = false;
  bool recovering_ = false;  //  防止恢复错误再次递归触发恢复 / Prevent recovery errors from recursively starting recovery
#if OMIPET_AHT20_ASYNC
  enum class MeasurementPhase : uint8_t { Idle, StartDelay, Converting };
  MeasurementPhase phase_ = MeasurementPhase::Idle;
  uint32_t phaseStartedAtMs_ = 0;
  uint32_t lastPollAtMs_ = 0;
#endif
};

extern Aht20Sensor aht20;

}  //  OmiPetSensor 命名空间 / OmiPetSensor namespace
