#include "omi_pet_ui.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>

#include "NV3007_Display.h"
#include "omi_ui_font.h"

namespace OmiPetUi {
namespace {
constexpr int kWidth = OmiPetDisplay::kPanelHeight;
constexpr int kHeight = OmiPetDisplay::kPanelWidth;
constexpr uint16_t kBackground = OmiPetDisplay::Display::color565(8, 12, 17);
constexpr uint16_t kSurface = OmiPetDisplay::Display::color565(21, 28, 36);
constexpr uint16_t kLine = OmiPetDisplay::Display::color565(39, 49, 59);
constexpr uint16_t kText = OmiPetDisplay::Display::color565(237, 241, 243);
constexpr uint16_t kMuted = OmiPetDisplay::Display::color565(183, 197, 208);
constexpr uint16_t kAccent = OmiPetDisplay::Display::color565(113, 225, 209);
constexpr uint16_t kRed = OmiPetDisplay::Display::color565(255, 139, 135);
constexpr uint16_t kAmber = OmiPetDisplay::Display::color565(244, 199, 107);

//  复用原任务卡大小的静态缓冲，所有页面先合成再传输 / Reuse the original card-sized static buffer; composite every page region before transfer
uint16_t gBuffer[206 * 50];
int gX = 0, gY = 0, gWidth = 0, gHeight = 0;
bool gStarted = false;
enum class Page { Dashboard, Tasks, Listening, Pairing };
struct UiState {
  char temperature[16] = "--";
  char humidity[8] = "--";
  char clock[6] = "--:--";
  char date[11] = "----/--/--";
  char voice[24] = "IDLE";
  bool timeValid = false;
  bool network = false;
  bool provisioning = false;
  bool batteryValid = false;
  uint8_t battery = 0;
  bool tasks = false;
  char pairingCode[7] = {};
  char pairingAddress[16] = {};
  uint16_t pairingSeconds = 0;
};
UiState gState, gRendered;
OmiPetProtocol::TaskScreen gTasks, gRenderedTasks;
Page gRenderedPage = Page::Dashboard;
bool gRenderedValid = false;
int gFullRow = -1;
bool gFullStale = false;

Page page() {
  if (gState.pairingSeconds) return Page::Pairing;
  if (gState.tasks) return Page::Tasks;
  if (std::strcmp(gState.voice, "LISTENING") == 0) return Page::Listening;
  return Page::Dashboard;
}

void pixel(int x, int y, uint16_t color) {
  if (x >= gX && x < gX + gWidth && y >= gY && y < gY + gHeight)
    gBuffer[(y - gY) * gWidth + x - gX] = color;
}

void rect(int x, int y, int width, int height, uint16_t color, int radius = 0) {
  const int left = std::max(x, gX), right = std::min(x + width, gX + gWidth);
  const int top = std::max(y, gY), bottom = std::min(y + height, gY + gHeight);
  for (int row = top; row < bottom; ++row) {
    for (int col = left; col < right; ++col) {
      if (radius) {
        const int dx = std::max(std::max(x + radius - col, col - (x + width - 1 - radius)), 0);
        const int dy = std::max(std::max(y + radius - row, row - (y + height - 1 - radius)), 0);
        if (dx * dx + dy * dy > radius * radius) continue;
      }
      pixel(col, row, color);
    }
  }
}

uint16_t blend(uint16_t foreground, uint16_t background, unsigned alpha) {
  const unsigned inverse = 15 - alpha;
  const unsigned r = (((foreground >> 11) * alpha + (background >> 11) * inverse + 7) / 15);
  const unsigned g = ((((foreground >> 5) & 63) * alpha + ((background >> 5) & 63) * inverse + 7) / 15);
  const unsigned b = (((foreground & 31) * alpha + (background & 31) * inverse + 7) / 15);
  return static_cast<uint16_t>((r << 11) | (g << 5) | b);
}

//  只解码本地固定文案；动态任务标题仍沿用主机单色位图 / Decode local fixed labels only; dynamic task titles remain host monochrome bitmaps
uint32_t codepoint(const char*& text) {
  const auto first = static_cast<uint8_t>(*text++);
  if (first < 128) return first;
  unsigned remaining = first >= 0xE0 ? 2 : 1;
  uint32_t value = first & (remaining == 2 ? 15 : 31);
  while (remaining--) {
    const auto next = static_cast<uint8_t>(*text);
    if ((next & 0xC0) != 0x80) return '?';
    value = (value << 6) | (next & 63);
    ++text;
  }
  return value;
}

const OmiPetUiFont::Glyph* glyph(uint32_t code, uint8_t size) {
  size_t left = 0, right = sizeof(OmiPetUiFont::kGlyphs) / sizeof(OmiPetUiFont::kGlyphs[0]);
  while (left < right) {
    const size_t middle = (left + right) / 2;
    const auto& candidate = OmiPetUiFont::kGlyphs[middle];
    if (candidate.size < size || (candidate.size == size && candidate.codepoint < code)) left = middle + 1;
    else right = middle;
  }
  if (left < sizeof(OmiPetUiFont::kGlyphs) / sizeof(OmiPetUiFont::kGlyphs[0])) {
    const auto& candidate = OmiPetUiFont::kGlyphs[left];
    if (candidate.size == size && candidate.codepoint == code) return &candidate;
  }
  return nullptr;
}

int textWidth(const char* text, uint8_t size) {
  int width = 0;
  while (*text) {
    const auto* item = glyph(codepoint(text), size);
    width += item ? item->advance : size;
  }
  return width;
}

void text(const char* value, int x, int baseline, uint8_t size = 14, uint16_t color = kText) {
  while (*value) {
    const auto* item = glyph(codepoint(value), size);
    if (!item) { x += size; continue; }
    const int left = x + item->left, top = baseline + item->top;
    for (int row = std::max(top, gY); row < std::min(top + item->height, gY + gHeight); ++row) {
      for (int col = std::max(left, gX); col < std::min(left + item->width, gX + gWidth); ++col) {
        const unsigned offset = (row - top) * item->width + col - left;
        const uint8_t packed = OmiPetUiFont::kPixels[item->offset + offset / 2];
        const unsigned alpha = offset % 2 ? packed & 15 : packed >> 4;
        if (alpha) {
          const uint16_t background = gBuffer[(row - gY) * gWidth + col - gX];
          pixel(col, row, blend(color, background, alpha));
        }
      }
    }
    x += item->advance;
  }
}

void centered(const char* value, int baseline, uint8_t size, uint16_t color = kText) {
  text(value, (kWidth - textWidth(value, size)) / 2, baseline, size, color);
}

void face(int x, int y, bool listening) {
  rect(x, y, 66, 56, kSurface, 18);
  rect(x + 15, y + 18, 8, listening ? 18 : 13, kAccent, 4);
  rect(x + 43, y + 18, 8, listening ? 18 : 13, kAccent, 4);
  rect(x + 29, y + 39, 2, 3, kAccent);
  rect(x + 31, y + 41, 6, 2, kAccent);
  rect(x + 37, y + 39, 2, 3, kAccent);
}

const char* voiceLabel() {
  if (std::strcmp(gState.voice, "LISTENING") == 0) return "正在聆听";
  if (std::strcmp(gState.voice, "PAIR UNREADY") == 0) return "配对未就绪";
  if (std::strcmp(gState.voice, "IDLE") == 0) return "语音就绪";
  return gState.voice;
}

void header(Page current) {
  rect(11, 10, 6, 6, kAccent, 3);
  text("Omi", 23, 18, 14);
  char label[48] = {};
  if (current == Page::Tasks) {
    std::snprintf(label, sizeof(label), "Codex  %u %s", gTasks.active, "活动");
  } else {
    std::snprintf(label, sizeof(label), "%s", current == Page::Pairing ? "设备配对" : current == Page::Listening ? "离线语音" : "桌面伙伴");
  }
  text(label, 57, 19, 14, kMuted);
  const char* network = gState.network ? "已连接" : gState.provisioning ? "配网中" : "离线";
  text(network, 294 - textWidth(network, 14), 19, 14, gState.network ? kAccent : kMuted);
  rect(299, 8, 1, 12, kLine);
  const char* voice = voiceLabel();
  if (textWidth(voice, 14) <= 70) text(voice, 305, 19, 14, kMuted);
  else text("VOICE", 305, 19, 14, kMuted);
  rect(380, 7, 24, 12, kLine, 3);
  rect(405, 11, 2, 4, kMuted);
  if (gState.batteryValid) {
    const auto color = gState.battery <= 20 ? kRed : gState.battery <= 40 ? kAmber : kAccent;
    rect(382, 9, (20 * gState.battery + 50) / 100, 8, color, 1);
  } else text("?", 389, 17, 11, kMuted);
  rect(12, 25, 404, 1, kLine);
}

void dashboard() {
  face(18, 56, false);
  text(gState.clock, 101, 88, 43);
  text(gState.date, 104, 111, 11, kMuted);
  rect(257, 43, 1, 85, kLine);
  text("温度", 274, 52, 14, kMuted);
  text(gState.temperature, 274, 78, 24);
  text("°C", 280 + textWidth(gState.temperature, 24), 77, 11, kMuted);
  text("湿度", 274, 99, 14, kMuted);
  text(gState.humidity, 274, 125, 24);
  text("%", 280 + textWidth(gState.humidity, 24), 124, 11, kMuted);
  if (!gState.timeValid) text("等待联网校时", 332, 137, 14, kMuted);
}

void monochrome(const uint8_t* pixels, int x, int y, int width, int height, uint16_t color) {
  for (int row = std::max(y, gY); row < std::min(y + height, gY + gHeight); ++row) {
    for (int col = std::max(x, gX); col < std::min(x + width, gX + gWidth); ++col) {
      const unsigned bit = (row - y) * width + col - x;
      if (pixels[bit / 8] & (0x80U >> (bit % 8))) pixel(col, row, color);
    }
  }
}

void tasks() {
  if (!gTasks.available) { centered("无任务", 83, 14, kAmber); return; }
  if (!gTasks.active) { centered("暂无活动任务", 83, 14, kMuted); return; }
  for (unsigned i = 0; i < 4; ++i) {
    const auto& card = gTasks.cards[i];
    if (!card.used) continue;
    const int x = 12 + (i % 2) * 208, y = 31 + (i / 2) * 49;
    const auto color = card.waiting ? kAmber : kRed;
    rect(x, y, 196, 45, kSurface, 7);
    rect(x, y + 9, 3, 29, color, 1);
    bool ink = false;
    for (uint8_t byte : card.pixels) ink = ink || byte != 0;
    if (ink) monochrome(card.pixels, x + 12, y + 4, 160, 16, kText);
    else text("标题不可用", x + 12, y + 18, 14, kMuted);
    if (gTasks.hasLabels) monochrome(gTasks.labels + (card.waiting ? 0 : 128), x + 12, y + 26, 64, 16, color);
    else text(card.waiting ? "等待操作" : "正在处理", x + 12, y + 39, 14, color);
    char number[3];
    std::snprintf(number, sizeof(number), "%02u", i + 1);
    text(number, x + 174, y + 38, 11, kMuted);
  }
  if (gTasks.active > 4) {
    char more[32];
    std::snprintf(more, sizeof(more), "+%u %s", gTasks.active - 4, "更多活动任务");
    text(more, 12, 139, 14, kAmber);
  }
}

void listening() {
  face(23, 52, true);
  text("我在听", 111, 69, 27);
  text("试试说「亮一点」", 111, 98, 14, kMuted);
  const int heights[] = {12, 24, 38, 28, 16};
  for (unsigned i = 0; i < 5; ++i) rect(332 + i * 11, 81 - heights[i] / 2, 5, heights[i], kAccent, 2);
  text("离线语音", 358, 120, 14, kMuted);
}

void pairing() {
  centered("在电脑端输入配对码", 48, 14, kMuted);
  char code[8];
  std::snprintf(code, sizeof(code), "%.3s %.3s", gState.pairingCode, gState.pairingCode + 3);
  centered(code, 91, 39);
  text(gState.pairingAddress, 19, 127, 11, kMuted);
  char remaining[32];
  std::snprintf(remaining, sizeof(remaining), "%02u:%02u %s", gState.pairingSeconds / 60, gState.pairingSeconds % 60, "后失效");
  text(remaining, 308, 125, 14, kAmber);
}

void drawPage() {
  const Page current = page();
  header(current);
  if (current == Page::Dashboard) dashboard();
  else if (current == Page::Tasks) tasks();
  else if (current == Page::Listening) listening();
  else pairing();
}

//  按缓冲容量分块合成，不先擦屏 / Composite regions within the buffer capacity without erase-first
void flush(int x, int y, int width, int height) {
  const int rows = static_cast<int>(sizeof(gBuffer) / sizeof(gBuffer[0])) / width;
  for (int top = y; top < y + height; top += rows) {
    gX = x; gY = top; gWidth = width; gHeight = std::min(rows, y + height - top);
    std::fill_n(gBuffer, gWidth * gHeight, kBackground);
    drawPage();
    OmiPetDisplay::lcd.drawBitmap(gX, gY, gWidth, gHeight, gBuffer);
  }
}

bool changed(const char* a, const char* b) { return std::strcmp(a, b) != 0; }

bool sameState() {
  if (changed(gState.temperature, gRendered.temperature) || changed(gState.humidity, gRendered.humidity) ||
      changed(gState.clock, gRendered.clock) || changed(gState.date, gRendered.date) ||
      changed(gState.voice, gRendered.voice) || changed(gState.pairingCode, gRendered.pairingCode) ||
      changed(gState.pairingAddress, gRendered.pairingAddress) || gState.timeValid != gRendered.timeValid ||
      gState.network != gRendered.network || gState.provisioning != gRendered.provisioning ||
      gState.batteryValid != gRendered.batteryValid || gState.battery != gRendered.battery ||
      gState.tasks != gRendered.tasks || gState.pairingSeconds != gRendered.pairingSeconds ||
      gTasks.available != gRenderedTasks.available || gTasks.active != gRenderedTasks.active ||
      gTasks.hasLabels != gRenderedTasks.hasLabels ||
      std::memcmp(gTasks.labels, gRenderedTasks.labels, sizeof(gTasks.labels)) != 0) return false;
  for (unsigned i = 0; i < 4; ++i)
    if (gTasks.cards[i].used != gRenderedTasks.cards[i].used || gTasks.cards[i].waiting != gRenderedTasks.cards[i].waiting ||
        std::memcmp(gTasks.cards[i].pixels, gRenderedTasks.cards[i].pixels, sizeof(gTasks.cards[i].pixels)) != 0) return false;
  return true;
}

void refresh() {
  if (!gStarted) return;
  const Page current = page();
  const bool full = !gRenderedValid || current != gRenderedPage ||
      (current == Page::Tasks && (gTasks.available != gRenderedTasks.available ||
                                 (gTasks.active == 0) != (gRenderedTasks.active == 0)));
  if (full || gFullRow >= 0) {
    if (gFullRow < 0 || current != gRenderedPage) {
      gFullRow = 0;
      gFullStale = false;
      gRendered = gState;
      gRenderedTasks = gTasks;
      gRenderedPage = current;
    }
    //  每轮只传一块，避免唤醒绘制拖长确认音；中途更新后补绘 / Transfer one chunk per loop to protect acknowledgement timing; repaint if data changes mid-transition
    gFullStale = gFullStale || !sameState();
    constexpr int kRows = sizeof(gBuffer) / sizeof(gBuffer[0]) / kWidth;
    const int height = std::min(kRows, kHeight - gFullRow);
    flush(0, gFullRow, kWidth, height);
    gFullRow += height;
    if (gFullRow == kHeight) {
      gFullRow = -1;
      gRenderedValid = !gFullStale;
    }
    return;
  }
  else {
    if (gState.network != gRendered.network || gState.provisioning != gRendered.provisioning)
      flush(250, 4, 45, 19);
    if (gState.battery != gRendered.battery || gState.batteryValid != gRendered.batteryValid)
      flush(378, 4, 32, 19);
    if (changed(gState.voice, gRendered.voice)) flush(305, 4, 70, 19);
    if (current == Page::Tasks && gTasks.active != gRenderedTasks.active) flush(55, 4, 190, 19);
    if (current == Page::Dashboard) {
      if (gState.timeValid != gRendered.timeValid) flush(96, 44, 158, 49);
      else if (changed(gState.clock, gRendered.clock)) {
        int x = 101;
        for (unsigned i = 0; i < 5; ++i) {
          const auto* item = glyph(gState.clock[i], 43);
          if (item && gState.clock[i] != gRendered.clock[i]) flush(x, 44, item->advance + 1, 49);
          if (item) x += item->advance;
        }
      }
      if (changed(gState.date, gRendered.date)) flush(96, 96, 158, 22);
      if (changed(gState.temperature, gRendered.temperature)) flush(267, 55, 149, 29);
      if (changed(gState.humidity, gRendered.humidity)) flush(267, 102, 149, 27);
      if (gState.timeValid != gRendered.timeValid) flush(330, 123, 98, 19);
    } else if (current == Page::Tasks) {
      if (gTasks.active != gRenderedTasks.active) flush(0, 125, kWidth, 17);
      for (unsigned i = 0; i < 4; ++i) {
        const auto& card = gTasks.cards[i];
        const auto& old = gRenderedTasks.cards[i];
        const int x = 12 + (i % 2) * 208, y = 31 + (i / 2) * 49;
        if (card.used != old.used) flush(x, y, 196, 45);
        else if (card.used) {
          if (std::memcmp(card.pixels, old.pixels, sizeof(card.pixels)) != 0) flush(x + 12, y + 4, 160, 16);
          if (card.waiting != old.waiting) flush(x, y + 9, 3, 29);
          if (card.waiting != old.waiting || gTasks.hasLabels != gRenderedTasks.hasLabels ||
              std::memcmp(gTasks.labels, gRenderedTasks.labels, sizeof(gTasks.labels)) != 0)
            flush(x + 9, y + 25, 92, 18);
        }
      }
    } else if (current == Page::Pairing) {
      if (changed(gState.pairingCode, gRendered.pairingCode)) flush(100, 53, 228, 44);
      if (changed(gState.pairingAddress, gRendered.pairingAddress)) flush(12, 110, 200, 23);
      if (gState.pairingSeconds != gRendered.pairingSeconds) flush(302, 111, 108, 18);
    }
  }
  gRendered = gState;
  gRenderedTasks = gTasks;
  gRenderedPage = current;
  gRenderedValid = true;
}
}  //  匿名命名空间 / Anonymous namespace

void begin() {
  gStarted = true;
  gFullRow = -1;
  flush(0, 0, kWidth, kHeight);
  gRendered = gState;
  gRenderedTasks = gTasks;
  gRenderedPage = page();
  gRenderedValid = true;
}

void setEnvironment(float temperatureC, float humidityPercent, bool valid) {
  if (valid && std::isfinite(temperatureC) && std::isfinite(humidityPercent)) {
    std::snprintf(gState.temperature, sizeof(gState.temperature), "%.1f", static_cast<double>(temperatureC));
    std::snprintf(gState.humidity, sizeof(gState.humidity), "%.0f", static_cast<double>(humidityPercent));
  } else {
    std::strcpy(gState.temperature, "--");
    std::strcpy(gState.humidity, "--");
  }
}

void setBatteryStatus(uint8_t percent, bool valid) {
  gState.battery = valid ? std::min<uint8_t>(percent, 100) : 0;
  gState.batteryValid = valid;
}

void setNetworkStatus(bool connected, bool provisioning, const char*) {
  gState.network = connected;
  gState.provisioning = provisioning;
}

void setDateTime(bool valid, int year, int month, int day, int hour, int minute) {
  valid = valid && year >= 1 && year <= 9999 && month >= 1 && month <= 12 &&
          day >= 1 && day <= 31 && hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59;
  gState.timeValid = valid;
  if (valid) {
    std::snprintf(gState.clock, sizeof(gState.clock), "%02d:%02d", hour, minute);
    std::snprintf(gState.date, sizeof(gState.date), "%04d/%02d/%02d", year, month, day);
  } else {
    std::strcpy(gState.clock, "--:--");
    std::strcpy(gState.date, "----/--/--");
  }
}

void setVoiceStatus(const char* statusText) {
  if (!statusText) return;
  std::snprintf(gState.voice, sizeof(gState.voice), "%s", statusText);
}

void setPairingCode(const char* sixDigits, uint16_t secondsRemaining, const char* address) {
  bool valid = sixDigits && secondsRemaining > 0 && secondsRemaining <= 300 && std::strlen(sixDigits) == 6;
  if (valid) for (unsigned i = 0; i < 6; ++i) valid = valid && sixDigits[i] >= '0' && sixDigits[i] <= '9';
  if (valid) {
    std::memcpy(gState.pairingCode, sixDigits, 7);
    std::snprintf(gState.pairingAddress, sizeof(gState.pairingAddress), "%s", address ? address : "");
    gState.pairingSeconds = secondsRemaining;
  } else {
    volatile char* code = gState.pairingCode;
    for (unsigned i = 0; i < sizeof(gState.pairingCode); ++i) code[i] = 0;
    gState.pairingSeconds = 0;
    gState.pairingAddress[0] = 0;
  }
}

void setTaskScreen(bool enabled, bool connected, const OmiPetProtocol::TaskScreen* screen) {
  gState.tasks = enabled && connected;
  gTasks = screen ? *screen : OmiPetProtocol::TaskScreen{};
}

void update() { refresh(); }
}  //  OmiPetUi 命名空间 / OmiPetUi namespace
