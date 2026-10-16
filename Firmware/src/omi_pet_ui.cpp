#include "omi_pet_ui.h"

//  OmiPet 屏幕界面绘制实现 / OmiPet screen user-interface rendering implementation

#include <Arduino.h>

#include <cstring>
#include <cstdio>
#include <cstdint>

#include "NV3007_Display.h"

namespace OmiPetUi {
namespace {

struct Glyph {
  char character;
  uint8_t rows[7];
};

//  简单 5×7 字模 / Simple 5x7 bitmap font
constexpr Glyph kFont[] = {  //  内置 ASCII 5×7 字模表 / Built-in ASCII 5x7 glyph table
    {' ', {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}},
    {'-', {0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00}},
    {':', {0x00, 0x04, 0x04, 0x00, 0x04, 0x04, 0x00}},
    {'/', {0x01, 0x01, 0x02, 0x04, 0x08, 0x10, 0x10}},
    {'.', {0x00, 0x00, 0x00, 0x00, 0x00, 0x06, 0x06}},
    {'%', {0x19, 0x19, 0x02, 0x04, 0x08, 0x13, 0x13}},
    {'0', {0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E}},
    {'1', {0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E}},
    {'2', {0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F}},
    {'3', {0x1E, 0x01, 0x01, 0x0E, 0x01, 0x01, 0x1E}},
    {'4', {0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02}},
    {'5', {0x1F, 0x10, 0x10, 0x1E, 0x01, 0x01, 0x1E}},
    {'6', {0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E}},
    {'7', {0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08}},
    {'8', {0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E}},
    {'9', {0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C}},
    {'A', {0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11}},
    {'B', {0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E}},
    {'C', {0x0F, 0x10, 0x10, 0x10, 0x10, 0x10, 0x0F}},
    {'D', {0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E}},
    {'E', {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F}},
    {'F', {0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10}},
    {'G', {0x0F, 0x10, 0x10, 0x17, 0x11, 0x11, 0x0F}},
    {'H', {0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11}},
    {'I', {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x1F}},
    {'J', {0x01, 0x01, 0x01, 0x01, 0x11, 0x11, 0x0E}},
    {'K', {0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11}},
    {'L', {0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F}},
    {'M', {0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11}},
    {'N', {0x11, 0x19, 0x19, 0x15, 0x13, 0x13, 0x11}},
    {'O', {0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E}},
    {'P', {0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10}},
    {'Q', {0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D}},
    {'R', {0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11}},
    {'S', {0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E}},
    {'T', {0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04}},
    {'U', {0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E}},
    {'V', {0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04}},
    {'W', {0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11}},
    {'X', {0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11}},
    {'Y', {0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04}},
    {'Z', {0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F}},
};

constexpr uint16_t kBackground = 0x0000;  //  纯黑页面背景 / Pure-black page background
constexpr uint16_t kCardFill = OmiPetDisplay::Display::color565(190, 195, 202);  //  淡灰卡片填充色 / Light-gray card fill color
constexpr uint16_t kCardText = OmiPetDisplay::Display::color565(20, 27, 36);  //  卡片深色文字 / Dark card text color
constexpr uint16_t kAccent = OmiPetDisplay::Display::color565(72, 220, 255);  //  UI 强调色 / UI accent color
constexpr uint16_t kWhite = OmiPetDisplay::Display::color565(245, 248, 255);  //  UI 白色文字颜色 / UI white text color
constexpr uint16_t kGreen = OmiPetDisplay::Display::color565(100, 235, 150);  //  正常状态颜色 / Normal-status color
constexpr uint16_t kYellow = OmiPetDisplay::Display::color565(255, 220, 80);  //  提示状态颜色 / Attention-status color
constexpr uint16_t kRed = OmiPetDisplay::Display::color565(255, 90, 90);  //  错误状态颜色 / Error-status color
constexpr uint16_t kPanelLine = OmiPetDisplay::Display::color565(30, 70, 100);  //  模块边框颜色 / Module-border color

constexpr int16_t kScreenWidth = OmiPetDisplay::kPanelHeight;  //  横屏逻辑宽度 / Landscape logical width
constexpr int16_t kScreenHeight = OmiPetDisplay::kPanelWidth;  //  横屏逻辑高度 / Landscape logical height
constexpr int16_t kSideCardWidth = 106;
constexpr int16_t kSideCardHeight = 63;
constexpr int16_t kSideCardLeft = 4;
constexpr int16_t kSideCardRight = kScreenWidth - kSideCardLeft - kSideCardWidth;
constexpr int16_t kTopCardY = 5;
constexpr int16_t kBottomCardY = kScreenHeight - kSideCardHeight - kTopCardY;
constexpr int16_t kCenterCardLeft = kSideCardLeft + kSideCardWidth + 6;
constexpr int16_t kCenterCardTop = kTopCardY;
constexpr int16_t kCenterCardWidth =
    kSideCardRight - kCenterCardLeft - 6;
constexpr int16_t kCenterCardHeight = kScreenHeight - kTopCardY * 2;
constexpr int16_t kCardRadius = 9;
char gRenderedClockText[6] = {};
char gRenderedDateText[11] = {};
char gRenderedPairingCountdown[6] = {};
bool gDateTimeRendered = false;
bool gPairingCountdownRendered = false;
bool gPairingVisible = false;
char gPairingCode[7] = {};
char gPairingAddress[16] = {};
uint16_t gPairingSecondsRemaining = 0;
bool gDateTimeValid = false;
int gDateTimeYear = 0;
int gDateTimeMonth = 0;
int gDateTimeDay = 0;
int gDateTimeHour = 0;
int gDateTimeMinute = 0;
bool gUiStarted = false;
bool gEnvironmentValid = false;
float gTemperatureC = 0.0F;
float gHumidityPercent = 0.0F;
bool gBatteryValid = false;
uint8_t gBatteryPercent = 0;
bool gNetworkConnected = false;
bool gNetworkProvisioning = false;
char gWifiName[33] = {};
const char* gVoiceStatus = "IDLE";
uint16_t gGlyphBitmap[20 * 28] = {};

//  查找内置字模 / Find a glyph in the built-in font
const Glyph* findGlyph(char character) {
  if (character >= 'a' && character <= 'z') {
    character = static_cast<char>(character - ('a' - 'A'));
  }
  for (const Glyph& glyph : kFont) {
    if (glyph.character == character) {
      return &glyph;
    }
  }
  return &kFont[0];
}

//  计算一行文本按指定缩放比例绘制时的像素宽度 / Calculate the pixel width of text at the requested scale
int16_t textWidth(const char* text, uint8_t scale) {
  const size_t length = std::strlen(text);
  if (length == 0) {
    return 0;
  }
  return static_cast<int16_t>((length * 6U - 1U) * scale);
}

//  从指定左上角绘制一行文本 / Draw one line of text from the specified top-left position
void drawText(int16_t x, int16_t y, const char* text, uint8_t scale,
              uint16_t color, uint16_t backgroundColor = kBackground) {
  const uint16_t glyphWidth = static_cast<uint16_t>(5U * scale);
  const uint16_t glyphHeight = static_cast<uint16_t>(7U * scale);
  for (size_t characterIndex = 0; text[characterIndex] != '\0';
       ++characterIndex) {
    const Glyph* glyph = findGlyph(text[characterIndex]);
    for (uint8_t row = 0; row < 7; ++row) {
      for (uint8_t column = 0; column < 5; ++column) {
        const uint16_t pixelColor =
            (glyph->rows[row] & (0x10U >> column)) != 0 ? color : backgroundColor;
        for (uint8_t scaleY = 0; scaleY < scale; ++scaleY) {
          for (uint8_t scaleX = 0; scaleX < scale; ++scaleX) {
            const uint16_t bitmapX =
                static_cast<uint16_t>(column * scale + scaleX);
            const uint16_t bitmapY =
                static_cast<uint16_t>(row * scale + scaleY);
            gGlyphBitmap[bitmapY * glyphWidth + bitmapX] = pixelColor;
          }
        }
      }
    }
    OmiPetDisplay::lcd.drawBitmap(x, y, glyphWidth, glyphHeight,
                                  gGlyphBitmap);
    x += static_cast<int16_t>(6 * scale);
  }
}

//  在指定矩形区域内水平居中绘制文本 / Draw text centered horizontally inside a specified rectangle
void drawCenteredTextInArea(int16_t left, int16_t width, int16_t y,
                            const char* text, uint8_t scale,
                            uint16_t color,
                            uint16_t backgroundColor = kBackground) {
  const int16_t textPixelWidth = textWidth(text, scale);
  drawText(left + (width - textPixelWidth) / 2, y, text, scale, color,
           backgroundColor);
}

//  根据同步状态格式化时间和日期文本 / Format time and date text from synchronization state
void formatDateTimeTexts(char* clockText, size_t clockTextSize, char* dateText,
                         size_t dateTextSize) {
  if (!gDateTimeValid) {
    std::snprintf(clockText, clockTextSize, "--:--");
    std::snprintf(dateText, dateTextSize, "----/--/--");
    return;
  }

  std::snprintf(clockText, clockTextSize, "%02d:%02d", gDateTimeHour,
                gDateTimeMinute);
  std::snprintf(dateText, dateTextSize, "%04d/%02d/%02d", gDateTimeYear,
                gDateTimeMonth, gDateTimeDay);
}

//  更新一行文本，只重绘发生变化的字符 / Update one line and redraw only changed characters
void drawChangedText(int16_t x, int16_t y, const char* text, uint8_t scale,
                     char* renderedText, size_t renderedTextSize,
                     uint16_t color, bool rendered) {
  for (size_t index = 0; text[index] != '\0'; ++index) {
    if (!rendered || text[index] != renderedText[index]) {
      char changedCharacter[2] = {text[index], '\0'};
      drawText(x + static_cast<int16_t>(index * 6U * scale), y,
               changedCharacter, scale, color, kBackground);
    }
  }
  std::strncpy(renderedText, text, renderedTextSize - 1U);
  renderedText[renderedTextSize - 1U] = '\0';
}

//  更新时间和日期，只重绘发生变化的字符 / Update time and date, redrawing only changed characters
void drawDateTime() {
  if (gPairingVisible) return;
  char clockText[6] = {};
  char dateText[11] = {};
  formatDateTimeTexts(clockText, sizeof(clockText), dateText, sizeof(dateText));
  constexpr uint8_t kClockScale = 4;
  constexpr int16_t kClockY = 53;
  const int16_t clockX = kCenterCardLeft +
      (kCenterCardWidth - textWidth(clockText, kClockScale)) / 2;
  drawChangedText(clockX, kClockY, clockText, kClockScale, gRenderedClockText,
                  sizeof(gRenderedClockText), kWhite, gDateTimeRendered);

  constexpr uint8_t kDateScale = 1;
  constexpr int16_t kDateY = 104;
  const int16_t dateX = kCenterCardLeft +
      (kCenterCardWidth - textWidth(dateText, kDateScale)) / 2;
  drawChangedText(dateX, kDateY, dateText, kDateScale, gRenderedDateText,
                  sizeof(gRenderedDateText), kWhite, gDateTimeRendered);
  gDateTimeRendered = true;
}

//  只刷新配对倒计时中发生变化的数字 / Refresh only the changed pairing-countdown digits
void drawPairingCountdown() {
  char countdown[6] = "00:00";
  const uint8_t minutes =
      static_cast<uint8_t>((gPairingSecondsRemaining / 60U) % 100U);
  const uint8_t seconds =
      static_cast<uint8_t>(gPairingSecondsRemaining % 60U);
  countdown[0] = static_cast<char>('0' + minutes / 10U);
  countdown[1] = static_cast<char>('0' + minutes % 10U);
  countdown[3] = static_cast<char>('0' + seconds / 10U);
  countdown[4] = static_cast<char>('0' + seconds % 10U);
  constexpr uint8_t kScale = 2;
  const int16_t x = kCenterCardLeft +
      (kCenterCardWidth - textWidth(countdown, kScale)) / 2;
  drawChangedText(x, 108, countdown, kScale, gRenderedPairingCountdown,
                  sizeof(gRenderedPairingCountdown), kYellow,
                  gPairingCountdownRendered);
  gPairingCountdownRendered = true;
}

//  在中央卡片单独绘制配对码，避免侧边状态和语音提示被覆盖 / Draw the pairing code in the center card without covering side status or voice feedback
void drawPairingCard() {
  OmiPetDisplay::lcd.fillRect(kCenterCardLeft + 2, kCenterCardTop + 2,
                              kCenterCardWidth - 4, kCenterCardHeight - 4,
                              kBackground);
  drawCenteredTextInArea(kCenterCardLeft, kCenterCardWidth, 20,
                         "PAIR CODE", 1, kAccent);
  drawCenteredTextInArea(kCenterCardLeft, kCenterCardWidth, 51,
                         gPairingCode, 4, kWhite);
  drawCenteredTextInArea(kCenterCardLeft, kCenterCardWidth, 91,
                         gPairingAddress[0] ? gPairingAddress : "EXPIRES", 1, kYellow);
  gPairingCountdownRendered = false;
  drawPairingCountdown();
}

//  把摄氏温度格式化为带一位小数的屏幕文本 / Format Celsius temperature as one-decimal display text
void formatTemperature(float temperatureC, char* output, size_t outputSize) {
  int32_t tenths = static_cast<int32_t>(temperatureC * 10.0F +
                                        (temperatureC >= 0.0F ? 0.5F : -0.5F));
  const bool negative = tenths < 0;
  const uint32_t absoluteTenths =
      static_cast<uint32_t>(negative ? -tenths : tenths);
  const uint32_t whole = absoluteTenths / 10U;
  const uint32_t fraction = absoluteTenths % 10U;
  if (negative) {
    std::snprintf(output, outputSize, "T -%lu.%luC",
                  static_cast<unsigned long>(whole),
                  static_cast<unsigned long>(fraction));
  } else {
    std::snprintf(output, outputSize, "T %lu.%luC",
                  static_cast<unsigned long>(whole),
                  static_cast<unsigned long>(fraction));
  }
}

//  准备温湿度显示字符串，无效时生成占位文本 / Prepare environment strings or placeholders when invalid
void formatEnvironmentValues(bool valid, float temperatureC,
                             float humidityPercent, char* temperatureText,
                             size_t temperatureSize, char* humidityText,
                             size_t humiditySize) {
  if (valid) {
    formatTemperature(temperatureC, temperatureText, temperatureSize);
    const int32_t humidity = static_cast<int32_t>(humidityPercent + 0.5F);
    std::snprintf(humidityText, humiditySize, "H %ld%%",
                  static_cast<long>(humidity));
  } else {
    std::strncpy(temperatureText, "T --C", temperatureSize - 1U);
    std::strncpy(humidityText, "H --%", humiditySize - 1U);
  }
}

//  只刷新温湿度卡片中发生变化的数值区域 / Refresh only changed value areas in the environment card
void drawEnvironmentValues(bool drawTemperature, bool drawHumidity) {
  char temperatureText[12] = {};
  char humidityText[10] = {};
  formatEnvironmentValues(gEnvironmentValid, gTemperatureC, gHumidityPercent,
                          temperatureText, sizeof(temperatureText),
                          humidityText, sizeof(humidityText));
  const int16_t x = kSideCardLeft;
  const int16_t y = kTopCardY;
  if (drawTemperature) {
    OmiPetDisplay::lcd.fillRect(x + 5, y + 27, kSideCardWidth - 10, 10,
                                kBackground);
    drawText(x + 5 + (kSideCardWidth - 10 - textWidth(temperatureText, 1)) / 2,
             y + 28, temperatureText, 1, kWhite, kBackground);
  }
  if (drawHumidity) {
    OmiPetDisplay::lcd.fillRect(x + 5, y + 43, kSideCardWidth - 10, 10,
                                kBackground);
    drawText(x + 5 + (kSideCardWidth - 10 - textWidth(humidityText, 1)) / 2,
             y + 44, humidityText, 1, kWhite, kBackground);
  }
}

//  绘制模块边框和标题 / Draw a module frame and title
void drawModuleFrame(int16_t x, int16_t y, int16_t width, int16_t height,
                     const char* title, uint16_t titleColor) {
  OmiPetDisplay::lcd.drawRoundRect(x, y, width, height, kCardRadius, kPanelLine,
                                   kBackground);
  drawText(x + 7, y + 8, title, 1, titleColor, kBackground);
}

//  绘制温湿度卡片及其当前数值 / Draw the environment card and current values
void drawEnvironment() {
  drawModuleFrame(kSideCardLeft, kTopCardY, kSideCardWidth, kSideCardHeight,
                  "ENVIRONMENT", kGreen);
  drawEnvironmentValues(true, true);
}

//  绘制网络卡片，并按需创建卡片边框 / Draw the network card and optionally create its frame
void drawNetworkStatus(bool drawFrame) {
  const char* statusText = "WIFI NOT";
  uint16_t statusColor = kRed;
  if (gNetworkConnected) {
    statusText = gWifiName[0] != '\0' ? gWifiName : "WIFI CONNECTED";
    statusColor = kGreen;
  }

  const int16_t x = kSideCardLeft;
  const int16_t y = kBottomCardY;
  if (drawFrame) {
    drawModuleFrame(x, y, kSideCardWidth, kSideCardHeight, "NETWORK", kAccent);
  }
  OmiPetDisplay::lcd.fillRect(x + 5, y + 28, kSideCardWidth - 10, 24,
                              kBackground);
  if (gNetworkConnected) {
    char displayName[17] = {};
    std::strncpy(displayName, statusText, sizeof(displayName) - 1U);
    if (std::strlen(statusText) >= sizeof(displayName)) {
      displayName[13] = '.';
      displayName[14] = '.';
      displayName[15] = '.';
      displayName[16] = '\0';
    }
    drawCenteredTextInArea(x + 5, kSideCardWidth - 10, y + 35, displayName,
                           1, statusColor, kBackground);
  } else {
    drawCenteredTextInArea(x + 5, kSideCardWidth - 10, y + 31, statusText, 1,
                           statusColor, kBackground);
    drawCenteredTextInArea(x + 5, kSideCardWidth - 10, y + 43, "CONNECTED", 1,
                           statusColor, kBackground);
  }
}

//  绘制语音状态卡片，并按需创建卡片边框 / Draw the voice card and optionally create its frame
void drawVoiceStatus(bool drawFrame) {
  const int16_t x = kSideCardRight;
  const int16_t y = kTopCardY;
  if (drawFrame) {
    drawModuleFrame(x, y, kSideCardWidth, kSideCardHeight, "VOICE", kYellow);
  }
  OmiPetDisplay::lcd.fillRect(x + 5, y + 30, kSideCardWidth - 10, 17,
                              kBackground);
  drawCenteredTextInArea(x + 5, kSideCardWidth - 10, y + 35, gVoiceStatus, 1,
                         kYellow, kBackground);
}

//  仅绘制电池百分比，并按需创建卡片边框 / Draw only the battery percentage and optionally create its frame
void drawBatteryStatus(bool drawFrame) {
  const int16_t x = kSideCardRight;
  const int16_t y = kBottomCardY;
  if (drawFrame) {
    drawModuleFrame(x, y, kSideCardWidth, kSideCardHeight, "BATTERY", kYellow);
  }
  OmiPetDisplay::lcd.fillRect(x + 5, y + 28, kSideCardWidth - 10, 24,
                              kBackground);
  char percentText[8] = {};
  if (gBatteryValid) {
    std::snprintf(percentText, sizeof(percentText), "%u%%",
                  static_cast<unsigned>(gBatteryPercent));
  } else {
    std::snprintf(percentText, sizeof(percentText), "--%%");
  }
  const uint16_t percentColor =
      !gBatteryValid || gBatteryPercent <= 20U ? kRed
      : gBatteryPercent <= 40U                  ? kYellow
                                                : kGreen;
  drawCenteredTextInArea(x + 5, kSideCardWidth - 10, y + 35, percentText, 1,
                         percentColor, kBackground);
}

//  绘制仪表盘首屏和所有静态卡片 / Draw the dashboard first frame and all static cards
void drawStaticUi() {
  OmiPetDisplay::lcd.fillScreen(kBackground);
  drawModuleFrame(kCenterCardLeft, kCenterCardTop, kCenterCardWidth,
                  kCenterCardHeight, "", kAccent);
  if (gPairingVisible) {
    drawPairingCard();
  } else {
    drawCenteredTextInArea(kCenterCardLeft, kCenterCardWidth, 19, "OMIPET", 1,
                           kAccent, kBackground);
    drawDateTime();
  }

  drawEnvironment();
  drawNetworkStatus(true);
  drawVoiceStatus(true);
  drawBatteryStatus(true);
}
}  //  匿名命名空间 / Anonymous namespace

//  初始化界面时钟、静态布局和首帧内容 / Initialize the UI clock, static layout, and first frame
void begin() {
  gDateTimeRendered = false;
  drawStaticUi();
  gUiStarted = true;
}

//  保存温湿度数据并只更新变化的读数 / Store environment data and update only changed readings
void setEnvironment(float temperatureC, float humidityPercent, bool valid) {
  char oldTemperatureText[12] = {};
  char oldHumidityText[10] = {};
  formatEnvironmentValues(gEnvironmentValid, gTemperatureC, gHumidityPercent,
                          oldTemperatureText, sizeof(oldTemperatureText),
                          oldHumidityText, sizeof(oldHumidityText));
  gTemperatureC = temperatureC;
  gHumidityPercent = humidityPercent;
  gEnvironmentValid = valid;
  if (gUiStarted) {
    char newTemperatureText[12] = {};
    char newHumidityText[10] = {};
    formatEnvironmentValues(gEnvironmentValid, gTemperatureC, gHumidityPercent,
                            newTemperatureText, sizeof(newTemperatureText),
                            newHumidityText, sizeof(newHumidityText));
    const bool temperatureChanged =
        std::strcmp(oldTemperatureText, newTemperatureText) != 0;
    const bool humidityChanged =
        std::strcmp(oldHumidityText, newHumidityText) != 0;
    if (temperatureChanged || humidityChanged) {
      drawEnvironmentValues(temperatureChanged, humidityChanged);
    }
  }
}

//  保存电量状态，仅在有效性或可见百分比变化时刷新 / Store battery state and refresh only when validity or the visible percentage changes
void setBatteryStatus(uint8_t percent, bool valid) {
  if (gBatteryValid == valid && (!valid || gBatteryPercent == percent)) {
    return;
  }
  gBatteryPercent = percent;
  gBatteryValid = valid;
  if (gUiStarted) {
    drawBatteryStatus(false);
  }
}

//  保存联网状态，仅在状态变化时刷新屏幕 / Store network state and refresh only when it changes
void setNetworkStatus(bool connected, bool provisioning, const char* ssid) {
  const char* safeSsid = ssid == nullptr ? "" : ssid;
  if (gNetworkConnected == connected &&
      gNetworkProvisioning == provisioning &&
      std::strcmp(gWifiName, safeSsid) == 0) {
    return;
  }

  gNetworkConnected = connected;
  gNetworkProvisioning = provisioning;
  std::strncpy(gWifiName, safeSsid, sizeof(gWifiName) - 1U);
  gWifiName[sizeof(gWifiName) - 1U] = '\0';
  if (gUiStarted) {
    drawNetworkStatus(false);
  }
}

//  保存联网时间和日期，仅在显示内容变化时刷新 / Store network time and date and refresh only when the display changes
void setDateTime(bool valid, int year, int month, int day, int hour,
                 int minute) {
  const bool changed =
      gDateTimeValid != valid || gDateTimeYear != year ||
      gDateTimeMonth != month || gDateTimeDay != day ||
      gDateTimeHour != hour || gDateTimeMinute != minute;
  if (!changed) {
    return;
  }

  gDateTimeValid = valid;
  gDateTimeYear = year;
  gDateTimeMonth = month;
  gDateTimeDay = day;
  gDateTimeHour = hour;
  gDateTimeMinute = minute;
  if (gUiStarted) {
    drawDateTime();
  }
}

//  保存语音状态文本，仅在文本变化时刷新屏幕 / Store voice-status text and refresh only when it changes
void setVoiceStatus(const char* statusText) {
  if (statusText == nullptr || std::strcmp(gVoiceStatus, statusText) == 0) {
    return;
  }

  gVoiceStatus = statusText;
  if (gUiStarted) {
    drawVoiceStatus(false);
  }
}

//  只接受恰好六位数字；清除后恢复原时钟和日期 / Accept exactly six decimal digits; restore the clock and date when cleared
void setPairingCode(const char* sixDigits, uint16_t secondsRemaining, const char* address) {
  bool valid = sixDigits != nullptr && secondsRemaining > 0U &&
               secondsRemaining <= 300U && std::strlen(sixDigits) == 6U;
  if (valid) {
    for (size_t index = 0; index < 6; ++index) {
      if (sixDigits[index] < '0' || sixDigits[index] > '9') valid = false;
    }
  }
  if (!valid) {
    if (!gPairingVisible) return;
    gPairingVisible = false;
    volatile char* codeBytes = gPairingCode;
    for (size_t index = 0; index < sizeof(gPairingCode); ++index) {
      codeBytes[index] = '\0';
    }
    gPairingSecondsRemaining = 0;
    gPairingCountdownRendered = false;
    if (gUiStarted) {
      OmiPetDisplay::lcd.fillRect(kCenterCardLeft + 2, kCenterCardTop + 2,
                                  kCenterCardWidth - 4, kCenterCardHeight - 4,
                                  kBackground);
      drawCenteredTextInArea(kCenterCardLeft, kCenterCardWidth, 19, "OMIPET",
                             1, kAccent);
      gDateTimeRendered = false;
      drawDateTime();
    }
    return;
  }

  char nextAddress[sizeof(gPairingAddress)] = {};
  if (address) std::strncpy(nextAddress, address, sizeof(nextAddress) - 1);
  const bool codeChanged = !gPairingVisible || std::strcmp(gPairingAddress, nextAddress) != 0 ||
                           std::strcmp(gPairingCode, sixDigits) != 0;
  if (!codeChanged && gPairingSecondsRemaining == secondsRemaining) return;
  gPairingVisible = true;
  gPairingSecondsRemaining = secondsRemaining;
  if (codeChanged) {
    std::memcpy(gPairingAddress, nextAddress, sizeof(gPairingAddress));
    std::memcpy(gPairingCode, sixDigits, sizeof(gPairingCode));
    if (gUiStarted) drawPairingCard();
  } else if (gUiStarted) {
    drawPairingCountdown();
  }
}
//  保留 UI 更新入口，时间内容由联网时间状态驱动 / Keep the UI update entry point driven by network time state
void update() {
  if (!gPairingVisible) drawDateTime();
}
}  //  OmiPetUi 命名空间 / OmiPetUi namespace
