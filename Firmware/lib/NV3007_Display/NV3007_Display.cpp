#include "NV3007_Display.h"

#include <cmath>

namespace OmiPetDisplay {
namespace {

uint16_t blendColor565(uint16_t foreground, uint16_t background,
                       uint8_t coverage) {
  const uint16_t inverse = static_cast<uint16_t>(255U - coverage);
  const uint16_t red = static_cast<uint16_t>(
      ((((foreground >> 11) & 0x1FU) * coverage) +
       (((background >> 11) & 0x1FU) * inverse) + 127U) /
      255U);
  const uint16_t green = static_cast<uint16_t>(
      ((((foreground >> 5) & 0x3FU) * coverage) +
       (((background >> 5) & 0x3FU) * inverse) + 127U) /
      255U);
  const uint16_t blue = static_cast<uint16_t>(
      (((foreground & 0x1FU) * coverage) +
       ((background & 0x1FU) * inverse) + 127U) /
      255U);
  return static_cast<uint16_t>((red << 11) | (green << 5) | blue);
}

void drawRoundedCorner(Display& display, int16_t centerX, int16_t centerY,
                       int16_t radius, int8_t directionX,
                       int8_t directionY, uint16_t color,
                       uint16_t background) {
  const int16_t scanLimit = radius + 1;
  for (int16_t offsetX = 0; offsetX <= scanLimit; ++offsetX) {
    for (int16_t offsetY = 0; offsetY <= scanLimit; ++offsetY) {
      const float distance = std::sqrt(static_cast<float>(
          offsetX * offsetX + offsetY * offsetY));
      const float edgeDistance = std::fabs(distance - radius);
      if (edgeDistance >= 1.0F) {
        continue;
      }

      const uint8_t coverage = static_cast<uint8_t>(
          (1.0F - edgeDistance) * 255.0F + 0.5F);
      display.drawPixel(centerX + directionX * offsetX,
                        centerY + directionY * offsetY,
                        blendColor565(color, background, coverage));
    }
  }
}

//  NV3007 常用命令 / Common NV3007 commands
constexpr uint8_t kCommandMemoryAccessControl = 0x36;  //  MADCTL 显存访问控制命令 / MADCTL memory-access-control command
constexpr uint8_t kCommandColumnAddressSet = 0x2A;  //  设置显示列地址命令 / Column-address-set command
constexpr uint8_t kCommandPageAddressSet = 0x2B;  //  设置显示行地址命令 / Page-address-set command
constexpr uint8_t kCommandMemoryWrite = 0x2C;  //  开始写入显存命令 / Memory-write command

//  各旋转方向对应的 MADCTL 值 / MADCTL values for each rotation
constexpr uint8_t kMadctlValues[] = {0x00, 0xC0, 0x60, 0xA0};  //  四种旋转方向的 MADCTL 值 / MADCTL values for the four rotations

//  厂家提供的 NV3007 初始化序列 / NV3007 initialization sequence from the panel vendor
constexpr Display::InitCommand kInitSequence[] = {  //  厂家提供的面板初始化命令序列 / Vendor-provided panel initialization command sequence
    {0xFF, {0xA5, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x9A, {0x08, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x9B, {0x08, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x9C, {0xB0, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x9D, {0x16, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x9E, {0xC4, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x8F, {0x55, 0x04, 0x0, 0x0, 0x0}, 2, 0},
    {0x84, {0x90, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x83, {0x7B, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x85, {0x33, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x60, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x70, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x61, {0x02, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x71, {0x02, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x62, {0x04, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x72, {0x04, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x6C, {0x29, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x7C, {0x29, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x6D, {0x31, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x7D, {0x31, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x6E, {0x0F, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x7E, {0x0F, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x66, {0x21, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x76, {0x21, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x68, {0x3A, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x78, {0x3A, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x63, {0x07, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x73, {0x07, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x64, {0x05, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x74, {0x05, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x65, {0x02, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x75, {0x02, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x67, {0x23, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x77, {0x23, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x69, {0x08, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x79, {0x08, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x6A, {0x13, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x7A, {0x13, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x6B, {0x13, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x7B, {0x13, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x6F, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x7F, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x50, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x52, {0xD6, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x53, {0x08, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x54, {0x08, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x55, {0x1E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x56, {0x1C, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xA0, {0x2B, 0x24, 0x00, 0x0, 0x0}, 3, 0},
    {0xA1, {0x87, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xA2, {0x86, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xA5, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xA6, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xA7, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xA8, {0x36, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xA9, {0x7E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xAA, {0x7E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xB9, {0x85, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xBA, {0x84, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xBB, {0x83, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xBC, {0x82, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xBD, {0x81, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xBE, {0x80, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xBF, {0x01, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xC0, {0x02, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xC1, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xC2, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xC3, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xC4, {0x33, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xC5, {0x7E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xC6, {0x7E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xC8, {0x33, 0x33, 0x0, 0x0, 0x0}, 2, 0},
    {0xC9, {0x68, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xCA, {0x69, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xCB, {0x6A, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xCC, {0x6B, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xCD, {0x33, 0x33, 0x0, 0x0, 0x0}, 2, 0},
    {0xCE, {0x6C, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xCF, {0x6D, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xD0, {0x6E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xD1, {0x6F, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xAB, {0x03, 0x67, 0x0, 0x0, 0x0}, 2, 0},
    {0xAC, {0x03, 0x6B, 0x0, 0x0, 0x0}, 2, 0},
    {0xAD, {0x03, 0x68, 0x0, 0x0, 0x0}, 2, 0},
    {0xAE, {0x03, 0x6C, 0x0, 0x0, 0x0}, 2, 0},
    {0xB3, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xB4, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xB5, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xB6, {0x32, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xB7, {0x7E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xB8, {0x7E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xE0, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xE1, {0x03, 0x0F, 0x0, 0x0, 0x0}, 2, 0},
    {0xE2, {0x04, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xE3, {0x01, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xE4, {0x0E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xE5, {0x01, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xE6, {0x19, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xE7, {0x10, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xE8, {0x10, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xEA, {0x12, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xEB, {0xD0, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xEC, {0x04, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xED, {0x07, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xEE, {0x07, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xEF, {0x09, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xF0, {0xD0, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xF1, {0x0E, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xF9, {0x17, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xF2, {0x2C, 0x1B, 0x0B, 0x20, 0x0}, 4, 0},
    {0xE9, {0x29, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xEC, {0x04, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x35, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x44, {0x00, 0x10, 0x0, 0x0, 0x0}, 2, 0},
    {0x46, {0x10, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0xFF, {0x00, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x3A, {0x05, 0x0, 0x0, 0x0, 0x0}, 1, 0},
    {0x11, {0x0, 0x0, 0x0, 0x0, 0x0}, 0, 220},
    {0x29, {0x0, 0x0, 0x0, 0x0, 0x0}, 0, 200},
};

}  //  匿名命名空间 / Anonymous namespace

//  创建显示驱动对象，默认使用 8 MHz、MSB 优先的 SPI 配置 / Create the display driver with default 8 MHz MSB-first SPI settings
Display::Display()
    : spi_(SPI), settings_(SPISettings(8000000UL, MSBFIRST, SPI_MODE0)) {}

//  初始化 GPIO、SPI、复位时序和厂家寄存器 / Initialize GPIO, SPI, reset timing, and vendor registers
bool Display::begin(uint32_t frequency) {
  frequency_ = frequency;
  settings_ = SPISettings(frequency_, MSBFIRST, SPI_MODE0);

  //  配置控制引脚并设置安全默认电平 / Configure control pins and safe default levels
  pinMode(kCsPin, OUTPUT);
  pinMode(kDcPin, OUTPUT);
  pinMode(kResetPin, OUTPUT);
  pinMode(kBacklightPin, OUTPUT);
  digitalWrite(kCsPin, HIGH);
  digitalWrite(kDcPin, HIGH);
  digitalWrite(kResetPin, HIGH);
  setBacklight(false);

  spi_.begin(kSckPin, -1, kMosiPin, kCsPin);

  //  执行硬件复位 / Perform a hardware reset
  digitalWrite(kResetPin, LOW);
  delay(100);
  digitalWrite(kResetPin, HIGH);
  delay(100);

  //  先设置方向，再写入厂家面板寄存器 / Set orientation before writing the vendor panel registers
  setRotation(3);
  writeInitSequence();
  initialized_ = true;
  return true;
}

//  设置旋转方向、逻辑尺寸和对应的 MADCTL 寄存器值 / Set rotation, logical size, and the matching MADCTL value
void Display::setRotation(uint8_t rotation) {
  rotation_ = rotation & 0x03U;
  madctl_ = kMadctlValues[rotation_];

  if (rotation_ <= 1U) {
    width_ = kPanelWidth;
    height_ = kPanelHeight;
    xOffset_ = 12;
    yOffset_ = 0;
  } else if (rotation_ == 2U) {
    width_ = kPanelHeight;
    height_ = kPanelWidth;
    xOffset_ = 0;
    yOffset_ = 14;
  } else {
    width_ = kPanelHeight;
    height_ = kPanelWidth;
    xOffset_ = 0;
    yOffset_ = 12;
  }

  const uint8_t data[] = {madctl_};
  writeCommandData(kCommandMemoryAccessControl, data, sizeof(data));
}

//  按硬件有效电平打开或关闭 LCD 背光 / Enable or disable the LCD backlight using the hardware active level
void Display::setBacklight(bool enabled) {
  const bool level = enabled ? kBacklightActiveHigh : !kBacklightActiveHigh;
  digitalWrite(kBacklightPin, level ? HIGH : LOW);
}

//  通过 SPI 发送不带参数的 LCD 命令 / Send a parameterless LCD command over SPI
void Display::writeCommand(uint8_t command) {
  //  发送无参数命令 / Send a command without parameters
  spi_.beginTransaction(settings_);
  digitalWrite(kCsPin, LOW);
  digitalWrite(kDcPin, LOW);
  spi_.transfer(command);
  digitalWrite(kCsPin, HIGH);
  spi_.endTransaction();
}

//  通过 SPI 发送 LCD 命令及其参数数据 / Send an LCD command and its parameter bytes over SPI
void Display::writeCommandData(uint8_t command, const uint8_t* data,
                               size_t length) {
  //  发送命令及参数 / Send a command followed by parameters
  spi_.beginTransaction(settings_);
  digitalWrite(kCsPin, LOW);
  digitalWrite(kDcPin, LOW);
  spi_.transfer(command);
  if (length > 0) {
    digitalWrite(kDcPin, HIGH);
    for (size_t index = 0; index < length; ++index) {
      spi_.transfer(data[index]);
    }
  }
  digitalWrite(kCsPin, HIGH);
  spi_.endTransaction();
}

//  按厂家提供的顺序写入整套 NV3007 初始化命令 / Write the complete vendor NV3007 initialization sequence in order
void Display::writeInitSequence() {
  //  按顺序执行厂家初始化表 / Execute the vendor initialization table in order
  for (const InitCommand& item : kInitSequence) {
    writeCommandData(item.command, item.data, item.dataLength);
    if (item.delayMs > 0) {
      delay(item.delayMs);
    }
  }
}

//  不再重复检查坐标，直接设置 LCD 显存写入窗口 / Set the LCD memory window without repeating coordinate checks
void Display::setAddressWindowUnchecked(uint16_t x0, uint16_t y0,
                                         uint16_t x1, uint16_t y1) {
  //  坐标已经过调用方检查 / Coordinates are validated by the caller
  const uint8_t columnData[] = {
      static_cast<uint8_t>((x0 + xOffset_) >> 8),
      static_cast<uint8_t>(x0 + xOffset_),
      static_cast<uint8_t>((x1 + xOffset_) >> 8),
      static_cast<uint8_t>(x1 + xOffset_),
  };
  const uint8_t rowData[] = {
      static_cast<uint8_t>((y0 + yOffset_) >> 8),
      static_cast<uint8_t>(y0 + yOffset_),
      static_cast<uint8_t>((y1 + yOffset_) >> 8),
      static_cast<uint8_t>(y1 + yOffset_),
  };
  writeCommandData(kCommandColumnAddressSet, columnData, sizeof(columnData));
  writeCommandData(kCommandPageAddressSet, rowData, sizeof(rowData));
  writeCommand(kCommandMemoryWrite);
}

//  检查并设置包含首尾坐标的 LCD 显存窗口 / Validate and set the inclusive LCD memory window
void Display::setAddressWindow(uint16_t x0, uint16_t y0, uint16_t x1,
                               uint16_t y1) {
  if (!initialized_ || x0 > x1 || y0 > y1 || x1 >= width_ || y1 >= height_) {
    return;
  }
  setAddressWindowUnchecked(x0, y0, x1, y1);
}

//  连续发送指定数量的 RGB565 像素颜色 / Send one RGB565 color for a specified number of pixels
void Display::writeColor(uint16_t color, uint32_t count) {
  const uint8_t high = static_cast<uint8_t>(color >> 8);
  const uint8_t low = static_cast<uint8_t>(color);
  spi_.beginTransaction(settings_);
  digitalWrite(kCsPin, LOW);
  digitalWrite(kDcPin, HIGH);
  while (count-- > 0) {
    spi_.transfer(high);
    spi_.transfer(low);
  }
  digitalWrite(kCsPin, HIGH);
  spi_.endTransaction();
}

//  设置整屏窗口并填充同一种颜色 / Set the full-screen window and fill it with one color
void Display::fillScreen(uint16_t color) {
  if (!initialized_) {
    return;
  }
  setAddressWindowUnchecked(0, 0, width_ - 1, height_ - 1);
  writeColor(color, static_cast<uint32_t>(width_) * height_);
}

//  裁剪矩形到屏幕范围后填充颜色 / Clip a rectangle to the display and fill it
void Display::fillRect(int16_t x, int16_t y, int16_t width, int16_t height,
                       uint16_t color) {
  if (!initialized_ || width <= 0 || height <= 0) {
    return;
  }
  if (x < 0) {
    width += x;
    x = 0;
  }
  if (y < 0) {
    height += y;
    y = 0;
  }
  if (x + width > this->width_) {
    width = this->width_ - x;
  }
  if (y + height > this->height_) {
    height = this->height_ - y;
  }
  if (width <= 0 || height <= 0) {
    return;
  }
  setAddressWindowUnchecked(static_cast<uint16_t>(x), static_cast<uint16_t>(y),
                            static_cast<uint16_t>(x + width - 1),
                            static_cast<uint16_t>(y + height - 1));
  writeColor(color, static_cast<uint32_t>(width) * height);
}

//  裁剪并发送 RGB565 位图像素 / Clip and transmit an RGB565 bitmap
void Display::drawBitmap(int16_t x, int16_t y, uint16_t width,
                         uint16_t height, const uint16_t* pixels) {
  if (!initialized_ || width == 0 || height == 0 || pixels == nullptr) {
    return;
  }

  const uint16_t sourceWidth = width;
  int16_t sourceX = 0;
  int16_t sourceY = 0;
  if (x < 0) {
    sourceX = -x;
    width = static_cast<uint16_t>(width + x);
    x = 0;
  }
  if (y < 0) {
    sourceY = -y;
    height = static_cast<uint16_t>(height + y);
    y = 0;
  }
  if (x + width > this->width_) {
    width = static_cast<uint16_t>(this->width_ - x);
  }
  if (y + height > this->height_) {
    height = static_cast<uint16_t>(this->height_ - y);
  }
  if (width == 0 || height == 0) {
    return;
  }

  setAddressWindowUnchecked(static_cast<uint16_t>(x), static_cast<uint16_t>(y),
                            static_cast<uint16_t>(x + width - 1),
                            static_cast<uint16_t>(y + height - 1));

  spi_.beginTransaction(settings_);
  digitalWrite(kCsPin, LOW);
  digitalWrite(kDcPin, HIGH);
  for (uint16_t row = 0; row < height; ++row) {
    const uint16_t* sourceRow =
        pixels + static_cast<size_t>(sourceY + row) * sourceWidth + sourceX;
    for (uint16_t column = 0; column < width; ++column) {
      const uint16_t color = sourceRow[column];
      spi_.transfer(static_cast<uint8_t>(color >> 8));
      spi_.transfer(static_cast<uint8_t>(color));
    }
  }
  digitalWrite(kCsPin, HIGH);
  spi_.endTransaction();
}

//  在坐标有效时绘制一个 RGB565 像素 / Draw one RGB565 pixel when the coordinate is valid
void Display::drawPixel(int16_t x, int16_t y, uint16_t color) {
  if (!initialized_ || x < 0 || y < 0 || x >= width_ || y >= height_) {
    return;
  }
  setAddressWindowUnchecked(static_cast<uint16_t>(x), static_cast<uint16_t>(y),
                            static_cast<uint16_t>(x), static_cast<uint16_t>(y));
  writeColor(color, 1);
}

//  绘制经过边界裁剪的水平线 / Draw a horizontally clipped line
void Display::drawFastHLine(int16_t x, int16_t y, int16_t width,
                            uint16_t color) {
  if (!initialized_ || y < 0 || y >= height_ || width <= 0) {
    return;
  }
  if (x < 0) {
    width += x;
    x = 0;
  }
  if (x + width > this->width_) {
    width = this->width_ - x;
  }
  if (width <= 0) {
    return;
  }
  setAddressWindowUnchecked(static_cast<uint16_t>(x), static_cast<uint16_t>(y),
                            static_cast<uint16_t>(x + width - 1),
                            static_cast<uint16_t>(y));
  writeColor(color, static_cast<uint32_t>(width));
}

//  绘制经过边界裁剪的垂直线 / Draw a vertically clipped line
void Display::drawFastVLine(int16_t x, int16_t y, int16_t height,
                            uint16_t color) {
  if (!initialized_ || x < 0 || x >= width_ || height <= 0) {
    return;
  }
  if (y < 0) {
    height += y;
    y = 0;
  }
  if (y + height > this->height_) {
    height = this->height_ - y;
  }
  if (height <= 0) {
    return;
  }
  setAddressWindowUnchecked(static_cast<uint16_t>(x), static_cast<uint16_t>(y),
                            static_cast<uint16_t>(x),
                            static_cast<uint16_t>(y + height - 1));
  writeColor(color, static_cast<uint32_t>(height));
}

//  组合四条边绘制矩形边框 / Draw a rectangle outline from four edges
void Display::drawRect(int16_t x, int16_t y, int16_t width, int16_t height,
                       uint16_t color) {
  if (width <= 0 || height <= 0) return;
  drawFastHLine(x, y, width, color);
  drawFastHLine(x, y + height - 1, width, color);
  drawFastVLine(x, y, height, color);
  drawFastVLine(x + width - 1, y, height, color);
}

//  绘制圆角矩形边缘 / Draw the perimeter of a rounded rectangle
void Display::drawRoundRect(int16_t x, int16_t y, int16_t width,
                            int16_t height, int16_t radius,
                            uint16_t color, uint16_t background) {
  if (width <= 0 || height <= 0) return;
  const int16_t maxRadius = (width < height ? width : height) / 2;
  if (radius < 0) radius = 0;
  if (radius > maxRadius) radius = maxRadius;
  if (radius == 0) {
    drawRect(x, y, width, height, color);
    return;
  }

  drawFastHLine(x + radius, y, width - radius * 2, color);
  drawFastHLine(x + radius, y + height - 1, width - radius * 2, color);
  drawFastVLine(x, y + radius, height - radius * 2, color);
  drawFastVLine(x + width - 1, y + radius, height - radius * 2, color);

  const int16_t leftCenterX = x + radius;
  const int16_t rightCenterX = x + width - radius - 1;
  const int16_t topCenterY = y + radius;
  const int16_t bottomCenterY = y + height - radius - 1;

  drawRoundedCorner(*this, leftCenterX, topCenterY, radius, -1, -1, color,
                    background);
  drawRoundedCorner(*this, rightCenterX, topCenterY, radius, 1, -1, color,
                    background);
  drawRoundedCorner(*this, leftCenterX, bottomCenterY, radius, -1, 1, color,
                    background);
  drawRoundedCorner(*this, rightCenterX, bottomCenterY, radius, 1, 1, color,
                    background);
}

//  返回当前旋转方向下的逻辑宽度 / Return the logical width for the current rotation
uint16_t Display::width() const { return width_; }
//  返回当前旋转方向下的逻辑高度 / Return the logical height for the current rotation
uint16_t Display::height() const { return height_; }
//  查询显示驱动是否已完成初始化 / Check whether the display driver is initialized
bool Display::initialized() const { return initialized_; }

Display lcd;

}  //  OmiPetDisplay 命名空间 / OmiPetDisplay namespace
