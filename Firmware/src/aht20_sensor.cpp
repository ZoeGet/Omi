#include "aht20_sensor.h"

namespace OmiPetSensor {
namespace {

//  AHT20 状态位和时序参数 / AHT20 status bits and timing parameters
constexpr uint8_t kStatusBusyMask = 0x80;  //  AHT20 状态字节 Busy 位掩码 / AHT20 status-byte busy-bit mask
constexpr uint8_t kStatusCalibrationMask = 0x08;  //  AHT20 状态字节校准使能位掩码 / AHT20 status-byte calibration-bit mask
constexpr uint32_t kPowerUpDelayMs = 100;  //  上电后等待传感器稳定的时间 / Sensor stabilization delay after power-up
constexpr uint32_t kCalibrationDelayMs = 10;  //  发送校准命令后的等待时间 / Delay after sending the calibration command
constexpr uint32_t kMeasurementStartDelayMs = 10;  //  发起测量后开始轮询前的等待时间 / Delay before polling after starting a measurement
constexpr uint32_t kMeasurementConversionDelayMs = 80;  //  测量转换的参考等待时间 / Reference measurement-conversion delay
constexpr uint32_t kMeasurementTimeoutMs = 120;  //  等待 AHT20 空闲的最大时间 / Maximum time to wait for AHT20 readiness
constexpr uint32_t kMeasurementPollIntervalMs = 5;  //  轮询 AHT20 Busy 位的间隔 / AHT20 busy-bit polling interval
constexpr uint32_t kRecoveryFailureThreshold = 3;  //  连续失败后触发软复位的次数阈值 / Consecutive-failure threshold for soft recovery
constexpr uint32_t kRecoveryIntervalMs = 5000;  //  两次自动恢复之间的最小间隔 / Minimum interval between automatic recoveries

//  AHT20 初始化、测量和软复位命令 / AHT20 initialization, measurement, and soft-reset commands
constexpr uint8_t kInitializeCommand[] = {0xBE, 0x08, 0x00};  //  AHT20 初始化校准命令帧 / AHT20 calibration-initialization command frame
constexpr uint8_t kMeasureCommand[] = {0xAC, 0x33, 0x00};  //  AHT20 触发测量命令帧 / AHT20 measurement-trigger command frame
constexpr uint8_t kSoftResetCommand[] = {0xBA};  //  AHT20 软复位命令帧 / AHT20 soft-reset command frame

}  //  匿名命名空间 / Anonymous namespace

//  初始化 AHT20 并完成 I2C 探测和校准 / Initialize AHT20, probe I2C, and complete calibration
bool Aht20Sensor::begin(TwoWire& wire, uint8_t sda, uint8_t scl,
                        uint32_t frequency) {
  //  保存总线配置并清空上一轮状态 / Save bus settings and clear the previous state
  wire_ = &wire;
  sdaPin_ = sda;
  sclPin_ = scl;
  frequency_ = frequency;
  initialized_ = false;
  recovering_ = false;
#if OMIPET_AHT20_ASYNC
  phase_ = MeasurementPhase::Idle;
#endif
  consecutiveFailures_ = 0;
  measurement_ = Aht20Measurement{};
  clearError();

  //  初始化 I2C 并设置总线频率 / Initialize I2C and set the bus frequency
  wire_->begin(sdaPin_, sclPin_);
  wire_->setClock(frequency_);
  //  等待传感器完成上电 / Wait for the sensor to complete power-up
  delay(kPowerUpDelayMs);

  //  先检测器件，再确认内部校准状态 / Probe the device, then verify internal calibration
  if (!probe() || !ensureCalibration()) {
    return false;
  }

  initialized_ = true;
  return true;
}

//  触发一次测量，校验数据并更新最近一次温湿度结果 / Trigger one measurement, validate it, and update the latest reading
bool Aht20Sensor::readMeasurement() {
#if OMIPET_AHT20_ASYNC
  if (phase_ != MeasurementPhase::Idle) return false;
#endif
  if (!initialized_ || wire_ == nullptr) {
    return fail(Aht20Error::NotInitialized);
  }

  clearError();
  //  按手册要求，触发测量前预留命令间隔 / Reserve the command interval required by the datasheet
  delay(kMeasurementStartDelayMs);
  if (!sendCommand(kMeasureCommand, sizeof(kMeasureCommand))) {
    return false;
  }
  //  按手册要求等待测量转换完成 / Wait for the conversion time required by the datasheet
  delay(kMeasurementConversionDelayMs);
  if (!waitUntilReady(kMeasurementTimeoutMs)) {
    return false;
  }
  return finishMeasurement();
}

#if OMIPET_AHT20_ASYNC
bool Aht20Sensor::startMeasurement() {
  if (phase_ != MeasurementPhase::Idle) return false;
  if (!initialized_ || wire_ == nullptr) return fail(Aht20Error::NotInitialized);
  clearError();
  phase_ = MeasurementPhase::StartDelay;
  phaseStartedAtMs_ = millis();
  return true;
}

bool Aht20Sensor::updateMeasurement() {
  if (phase_ == MeasurementPhase::Idle) return false;
  const uint32_t nowMs = millis();
  const uint32_t elapsedMs = nowMs - phaseStartedAtMs_;
  if (phase_ == MeasurementPhase::StartDelay) {
    if (elapsedMs < kMeasurementStartDelayMs) return false;
    if (!sendCommand(kMeasureCommand, sizeof(kMeasureCommand))) {
      phase_ = MeasurementPhase::Idle;
      return true;
    }
    phase_ = MeasurementPhase::Converting;
    phaseStartedAtMs_ = millis();
    lastPollAtMs_ = phaseStartedAtMs_;
    return false;
  }
  if (elapsedMs < kMeasurementConversionDelayMs) return false;
  if (elapsedMs >= kMeasurementConversionDelayMs + kMeasurementTimeoutMs) {
    phase_ = MeasurementPhase::Idle;
    fail(Aht20Error::BusyTimeout);
    return true;
  }
  if (nowMs - lastPollAtMs_ < kMeasurementPollIntervalMs) return false;
  lastPollAtMs_ = nowMs;
  uint8_t status = 0;
  if (!readStatus(status)) {
    phase_ = MeasurementPhase::Idle;
    return true;
  }
  if ((status & kStatusBusyMask) != 0) return false;
  phase_ = MeasurementPhase::Idle;
  finishMeasurement();
  return true;
}
#endif

bool Aht20Sensor::finishMeasurement() {
  //  读取状态、湿度、温度和 CRC 共 7 个字节 / Read 7 bytes containing status, humidity, temperature, and CRC
  uint8_t frame[7] = {};
  if (!readFrame(frame, sizeof(frame))) {
    return false;
  }
  if (calculateCrc(frame, 6) != frame[6]) {
    return fail(Aht20Error::CrcMismatch);
  }

  //  检查测量完成和校准状态 / Check measurement completion and calibration status
  if ((frame[0] & kStatusBusyMask) != 0) {
    return fail(Aht20Error::BusyTimeout);
  }
  if ((frame[0] & kStatusCalibrationMask) == 0) {
    return fail(Aht20Error::CalibrationFailed);
  }

  //  从 20-bit 原始数据恢复湿度和温度 / Decode humidity and temperature from 20-bit raw values
  const uint32_t rawHumidity =
      ((static_cast<uint32_t>(frame[1]) << 12) |
       (static_cast<uint32_t>(frame[2]) << 4) | (frame[3] >> 4)) & 0xFFFFFU;
  const uint32_t rawTemperature =
      (((static_cast<uint32_t>(frame[3]) & 0x0FU) << 16) |
       (static_cast<uint32_t>(frame[4]) << 8) | frame[5]) & 0xFFFFFU;

  //  按 AHT20 公式换算为工程单位 / Convert to engineering units using the AHT20 formulas
  const float humidity =
      static_cast<float>(rawHumidity) * 100.0F / 1048576.0F;
  const float temperature =
      static_cast<float>(rawTemperature) * 200.0F / 1048576.0F - 50.0F;
  if (humidity < 0.0F || humidity > 100.0F || temperature < -40.0F ||
      temperature > 120.0F) {
    return fail(Aht20Error::OutOfRange);
  }

  //  应用当前整机的经验补偿，修正 PCB 热影响 / Apply the current device-specific empirical offsets to compensate for PCB thermal influence
  const float correctedHumidity = constrain(
      humidity + kHumidityCalibrationOffsetPercent, 0.0F, 100.0F);
  const float correctedTemperature =
      temperature + kTemperatureCalibrationOffsetC;

  //  只在 CRC 和范围均通过后发布新数据 / Publish new data only after CRC and range checks pass
  measurement_.temperatureC = correctedTemperature;
  measurement_.humidityPercent = correctedHumidity;
  measurement_.rawTemperature = rawTemperature;
  measurement_.rawHumidity = rawHumidity;
  measurement_.status = frame[0];
  measurement_.valid = true;
  measurement_.stale = false;
  measurement_.timestampMs = millis();
  consecutiveFailures_ = 0;
  return true;
}

//  返回最近一次测量结果；valid 和 stale 表示数据是否有效及是否过期 / Return the latest reading; valid and stale show whether it is valid and current
const Aht20Measurement& Aht20Sensor::measurement() const {
  return measurement_;
}

//  返回最近一次驱动错误码 / Return the most recent driver error code
Aht20Error Aht20Sensor::lastError() const {
  return lastError_;
}

//  返回连续读取失败次数，用于判断是否需要自动恢复 / Return consecutive read failures used to trigger recovery
uint32_t Aht20Sensor::consecutiveFailures() const {
  return consecutiveFailures_;
}

//  查询传感器驱动是否已经成功初始化 / Check whether the sensor driver initialized successfully
bool Aht20Sensor::initialized() const {
  return initialized_;
}

//  通过 I2C 地址探测传感器是否在线 / Probe whether the sensor responds at its I2C address
bool Aht20Sensor::probe() {
  //  发送空事务，仅用于确认 0x38 地址应答 / Send an empty transaction only to confirm address 0x38 responds
  wire_->beginTransmission(kAht20Address);
  if (wire_->endTransmission(true) != 0) {
    return fail(Aht20Error::NoResponse);
  }
  return true;
}

//  读取 AHT20 状态字节，供 Busy 和校准状态判断使用 / Read the AHT20 status byte for busy and calibration checks
bool Aht20Sensor::readStatus(uint8_t& status) {
  //  requestFrom 会在总线上生成 0x71 读地址，不要把 0x71 当作数据写入 / requestFrom generates the 0x71 read address on the bus; do not write 0x71 as payload data
  const size_t requested = wire_->requestFrom(
      static_cast<uint8_t>(kAht20Address), static_cast<size_t>(1), true);
  if (requested != 1U || wire_->available() < 1) {
    return fail(Aht20Error::StatusReadFailed);
  }
  status = wire_->read();
  return true;
}

//  检查校准位，必要时发送初始化命令并等待校准完成 / Check calibration and initialize the sensor when needed
bool Aht20Sensor::ensureCalibration() {
  //  校准位未置位时发送初始化校准命令 / Send the calibration initialization command when the calibration bit is clear
  uint8_t status = 0;
  if (!readStatus(status)) {
    return false;
  }
  if ((status & kStatusCalibrationMask) != 0) {
    return true;
  }

  if (!sendCommand(kInitializeCommand, sizeof(kInitializeCommand))) {
    return false;
  }
  //  初始化命令后等待内部校准完成 / Wait for internal calibration after the initialization command
  delay(kCalibrationDelayMs);
  if (!waitUntilReady(kMeasurementTimeoutMs)) {
    return fail(Aht20Error::CalibrationFailed);
  }
  if (!readStatus(status) || (status & kStatusCalibrationMask) == 0) {
    return fail(Aht20Error::CalibrationFailed);
  }
  return true;
}

//  向 AHT20 写入一帧命令，并检查 I2C 返回状态 / Write one command frame and check the I2C result
bool Aht20Sensor::sendCommand(const uint8_t* command, size_t length) {
  //  写入完整命令帧并检查 I2C 结束状态 / Write the complete command frame and check the I2C result
  wire_->beginTransmission(kAht20Address);
  if (wire_->write(command, length) != length ||
      wire_->endTransmission(true) != 0) {
    return fail(Aht20Error::WriteFailed);
  }
  return true;
}

//  轮询 Busy 位，直到传感器空闲或达到超时时间 / Poll the busy bit until the sensor is ready or times out
bool Aht20Sensor::waitUntilReady(uint32_t timeoutMs) {
  //  轮询 Busy 位，避免固定延时后盲目读取 / Poll the Busy bit instead of blindly reading after a fixed delay
  const uint32_t startMs = millis();
  while (millis() - startMs < timeoutMs) {
    uint8_t status = 0;
    if (!readStatus(status)) {
      return false;
    }
    if ((status & kStatusBusyMask) == 0) {
      return true;
    }
    delay(kMeasurementPollIntervalMs);
  }
  return fail(Aht20Error::BusyTimeout);
}

//  从 I2C 总线读取指定长度的数据帧并检查是否短读 / Read a fixed-length I2C frame and reject short reads
bool Aht20Sensor::readFrame(uint8_t* frame, size_t length) {
  //  检查返回长度，避免解析不完整数据 / Check the returned length to avoid parsing an incomplete frame
  const size_t received = wire_->requestFrom(
      static_cast<uint8_t>(kAht20Address), static_cast<size_t>(length), true);
  if (received != length) {
    while (wire_->available()) {
      wire_->read();
    }
    return fail(Aht20Error::ShortRead);
  }
  for (size_t index = 0; index < length; ++index) {
    frame[index] = wire_->read();
  }
  return true;
}

//  发送软复位并重新完成校准流程 / Send a soft reset and run calibration again
bool Aht20Sensor::softReset() {
  //  软复位后等待器件恢复，再重新确认校准 / Wait for recovery after soft reset, then verify calibration again
  if (!sendCommand(kSoftResetCommand, sizeof(kSoftResetCommand))) {
    return false;
  }
  delay(20);
  return ensureCalibration();
}

//  记录失败状态，保留旧测量值，并按条件尝试自动恢复 / Record an error, keep the old reading, and recover when needed
bool Aht20Sensor::fail(Aht20Error error) {
  //  失败时保留上次数值，但标记为过期 / Retain the previous value but mark it as stale on failure
  lastError_ = error;
  measurement_.stale = true;
  ++consecutiveFailures_;

  const uint32_t nowMs = millis();
  if (wire_ != nullptr && !recovering_ && consecutiveFailures_ >= kRecoveryFailureThreshold &&
      nowMs - lastRecoveryMs_ >= kRecoveryIntervalMs) {
    lastRecoveryMs_ = nowMs;
    recovering_ = true;
    if (softReset()) {
      //  恢复初始化资格，但本次失败读数仍保持过期 / Restore initialization eligibility while leaving the failed reading stale
      initialized_ = true;
      consecutiveFailures_ = 0;
    }
    recovering_ = false;
  }
  return false;
}

//  清除本轮错误，等待下一次测量重新设置结果状态 / Clear the current error before the next measurement sets a new result state
void Aht20Sensor::clearError() {
  lastError_ = Aht20Error::None;
}

//  按 AHT20 规定计算数据帧 CRC-8 / Calculate the AHT20 data-frame CRC-8
uint8_t Aht20Sensor::calculateCrc(const uint8_t* data, size_t length) {
  //  使用多项式 0x31、初始值 0xFF 计算 CRC-8 / Calculate CRC-8 with polynomial 0x31 and initial value 0xFF
  uint8_t crc = 0xFF;
  for (size_t index = 0; index < length; ++index) {
    crc ^= data[index];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      crc = (crc & 0x80U) != 0 ? static_cast<uint8_t>((crc << 1) ^ 0x31U)
                               : static_cast<uint8_t>(crc << 1);
    }
  }
  return crc;
}

Aht20Sensor aht20;

}  //  OmiPetSensor 命名空间 / OmiPetSensor namespace
