#include "omi_pet_ui.h"
#include "NV3007_Display.h"
#include "omi_ui_font.h"
#include <array>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
namespace OmiPetDisplay { Display lcd; }
using Frame = std::array<uint16_t, 428 * 142>;
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
void tick() { for (unsigned i = 0; i < 24; ++i) OmiPetUi::update(); }
Frame snapshot() { Frame result; std::copy_n(OmiPetDisplay::lcd.pixels, result.size(), result.begin()); return result; }
void unchangedOutside(const Frame& before, int x, int y, int w, int h) {
  const auto after = snapshot();
  for (int row = 0; row < 142; ++row) for (int col = 0; col < 428; ++col)
    if (col < x || col >= x + w || row < y || row >= y + h)
      require(before[row * 428 + col] == after[row * 428 + col], "unrelated pixels changed");
}
void dump(const char* path) {
  std::ofstream out(path, std::ios::binary);
  out.write(reinterpret_cast<const char*>(OmiPetDisplay::lcd.pixels), sizeof(OmiPetDisplay::lcd.pixels));
}
void matchesFullDraw() {
  const Frame partial = snapshot();
  OmiPetUi::begin();
  const auto full = snapshot();
  for (unsigned i = 0; i < full.size(); ++i) if (full[i] != partial[i]) {
    throw std::runtime_error("regional refresh differs at " + std::to_string(i % 428) + "," + std::to_string(i / 428));
  }
}
int main(int argc, char** argv) {
  try {
    auto& lcd = OmiPetDisplay::lcd;
    OmiPetUi::setEnvironment(24.6F, 56, true); tick();
    OmiPetUi::setDateTime(true, 2026, 10, 22, 14, 28); tick();
    OmiPetUi::setNetworkStatus(true, false, "synthetic"); tick();
    OmiPetUi::setBatteryStatus(76, true); tick();
    require(lcd.writes == 0, "setters before begin must not draw");
    OmiPetUi::begin();
    const Frame home = snapshot();
    if (argc > 2) dump((std::string(argv[2]) + ".home").c_str());
    const uint16_t background = OmiPetDisplay::Display::color565(8, 12, 17);
    for (int y = 113; y < 133; ++y) for (int x = 12; x < 90; ++x)
      require(lcd.pixels[y * 428 + x] == background, "no caption below face");
    auto before = snapshot();
    OmiPetUi::setDateTime(true, 2026, 10, 22, 14, 29); tick();
    require(snapshot() != before, "minute changes visible");
    unchangedOutside(before, 96, 44, 158, 49);
    OmiPetUi::setDateTime(true, 2026, 10, 22, 14, 28); tick();
    require(snapshot() == home, "minute restoration leaves no trails");
    before = snapshot();
    OmiPetUi::setEnvironment(-44, 100, true); tick();
    unchangedOutside(before, 267, 55, 149, 74);
    OmiPetUi::setEnvironment(24.6F, 56, true); tick();
    require(snapshot() == home, "shorter environment numbers erase old digits");
    OmiPetUi::setEnvironment(116, 100, true); tick();
    if (argc > 2) dump((std::string(argv[2]) + ".limits").c_str());
    OmiPetUi::setEnvironment(NAN, 56, true); tick();
    const Frame invalidEnvironment = snapshot();
    OmiPetUi::setEnvironment(20, 56, false); tick();
    require(snapshot() == invalidEnvironment, "invalid values share placeholders");
    OmiPetUi::setEnvironment(24.6F, 56, true); tick();
    OmiPetUi::setNetworkStatus(false, false, nullptr); tick();
    OmiPetUi::setDateTime(false, 0, 0, 0, 0, 0); tick();
    const Frame offline = snapshot();
    if (argc > 2) dump((std::string(argv[2]) + ".offline").c_str());
    OmiPetUi::setDateTime(false, 2026, 10, 22, 14, 28); tick();
    require(snapshot() == offline, "invalid time cannot display supplied date");
    OmiPetUi::setDateTime(true, 2026, 10, 22, 14, 28); tick();
    OmiPetUi::setNetworkStatus(true, false, "synthetic"); tick();
    require(snapshot() == home, "offline hint fully erased on recovery");
    OmiPetUi::setVoiceStatus("LISTENING"); tick();
    require(snapshot() != home, "listening page visible");
    if (argc > 2) dump((std::string(argv[2]) + ".listening").c_str());
    OmiPetUi::setVoiceStatus("IDLE"); tick();
    require(snapshot() == home, "voice restores dashboard");
    unsigned writes = lcd.writes;
    OmiPetUi::setVoiceStatus(nullptr); tick(); tick();
    require(lcd.writes == writes, "null or unchanged inputs do not draw");
    OmiPetProtocol::TaskScreen screen;
    screen.available = true; screen.active = 6;
    std::ifstream titles(argc > 1 ? argv[1] : "", std::ios::binary);
    for (unsigned i = 0; i < 4; ++i) {
      screen.cards[i].used = true; screen.cards[i].waiting = i == 1;
      titles.read(reinterpret_cast<char*>(screen.cards[i].pixels), 320);
    }
    if (titles.read(reinterpret_cast<char*>(screen.labels), 256)) screen.hasLabels = true;
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    if (argc > 2) dump(argv[2]);
    const Frame initialTasks = snapshot();
    before = snapshot(); unsigned transfers = lcd.bitmaps;
    screen.cards[0].waiting = !screen.cards[0].waiting;
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    require(lcd.bitmaps == transfers + 2, "only status text and accent strip transferred");
    require(snapshot() != before, "status changes pixels");
    unchangedOutside(before, 12, 31, 196, 47);
    screen.cards[0].waiting = !screen.cards[0].waiting;
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    require(snapshot() == initialTasks, "status restoration exact");
    before = snapshot(); transfers = lcd.bitmaps;
    screen.cards[1].pixels[0] ^= 128;
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    require(lcd.bitmaps == transfers + 1, "one title transfer");
    unchangedOutside(before, 232, 35, 160, 16);
    before = snapshot(); transfers = lcd.bitmaps;
    screen.cards[2].used = false;
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    require(lcd.bitmaps == transfers + 1, "remove only one card");
    unchangedOutside(before, 12, 80, 196, 45);
    require(lcd.pixels[100 * 428 + 30] == background, "removed card erased");
    screen.cards[2].used = true;
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    transfers = lcd.bitmaps;
    screen.cards[3].waiting = true;
    OmiPetUi::setTaskScreen(true, true, &screen);
    screen.cards[3].waiting = false;
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    require(lcd.bitmaps == transfers, "coalesced task changes do not redraw");
    writes = lcd.writes;
    OmiPetUi::setEnvironment(23, 60, true); tick();
    OmiPetUi::setDateTime(true, 2026, 10, 22, 16, 30); tick();
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    require(lcd.writes == writes, "hidden dashboard values never leak into cards");
    before = snapshot();
    OmiPetUi::setBatteryStatus(10, true); tick();
    unchangedOutside(before, 0, 0, 428, 26);
    OmiPetUi::setTaskScreen(true, false, nullptr); tick();
    const Frame local = snapshot(); writes = lcd.writes;
    OmiPetUi::setTaskScreen(false, false, nullptr); tick();
    require(lcd.writes == writes, "disconnect already restored dashboard");
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    OmiPetUi::setTaskScreen(true, false, nullptr); tick();
    require(snapshot() == local, "disconnect restores current values");
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    OmiPetUi::setPairingCode("583204", 158, "192.0.2.1"); tick();
    if (argc > 2) dump((std::string(argv[2]) + ".pairing").c_str());
    before = snapshot(); writes = lcd.writes;
    OmiPetUi::setTaskScreen(true, false, nullptr); tick();
    require(lcd.writes == writes, "pairing dominates task disconnect");
    OmiPetUi::setPairingCode("583204", 157, "192.0.2.1"); tick();
    unchangedOutside(before, 302, 111, 108, 18);
    OmiPetUi::setPairingCode("111111", 120, "192.0.2.9"); tick();
    const Frame replacement = snapshot();
    OmiPetUi::setPairingCode("12x456", 120, "192.0.2.1"); tick();
    require(snapshot() == local, "invalid pairing code clears overlay");
    OmiPetUi::setPairingCode("111111", 120, "192.0.2.9"); tick();
    require(snapshot() == replacement, "pairing update matches fresh full draw");
    OmiPetUi::setPairingCode("111111", 301, nullptr); tick();
    require(snapshot() == local, "oversized pairing window clears code");
    OmiPetUi::setPairingCode("111111", 120, "192.0.2.9"); tick();
    OmiPetUi::setVoiceStatus("LISTENING"); tick(); before = snapshot();
    OmiPetUi::setPairingCode(nullptr, 0); tick();
    require(snapshot() != before, "pairing exit restores listening");
    OmiPetUi::setVoiceStatus("IDLE"); tick();
    require(snapshot() == local, "pairing and voice restore dashboard");
    screen.available = false;
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    const Frame unavailable = snapshot();
    screen.available = true; screen.active = 0;
    for (auto& card : screen.cards) card.used = false;
    OmiPetUi::setTaskScreen(true, true, &screen); tick();
    require(snapshot() != unavailable, "unavailable and no active tasks differ");
    if (argc > 2) dump((std::string(argv[2]) + ".empty").c_str());
    writes = lcd.writes; tick();
    require(lcd.writes == writes, "idle refresh does not transfer");
    for (unsigned i = 0; i < 24; ++i) {
      OmiPetUi::setTaskScreen(false, false, nullptr); tick();
      OmiPetUi::setEnvironment(i % 2 ? -44.0F : 116.0F, i % 3 ? 100 : 0, i % 5 != 0); tick();
      OmiPetUi::setDateTime(i % 4 != 0, 2026, 10, 22, i, (i * 17) % 60); tick();
      OmiPetUi::setBatteryStatus((i * 7) % 101, i % 3 != 0); tick();
      OmiPetUi::setNetworkStatus(i % 3 == 0, i % 3 == 1, "synthetic"); tick();
      OmiPetUi::setVoiceStatus(i % 2 ? "PAIR UNREADY" : "IDLE"); tick();
      matchesFullDraw();
      screen.available = i % 4 != 0; screen.active = i % 7;
      screen.hasLabels = i % 2 != 0;
      for (unsigned slot = 0; slot < 4; ++slot) {
        screen.cards[slot].used = slot < screen.active;
        screen.cards[slot].waiting = (slot + i) % 2 != 0;
        screen.cards[slot].pixels[i] ^= 128;
      }
      OmiPetUi::setTaskScreen(true, true, &screen); tick();
      matchesFullDraw();
      OmiPetUi::setPairingCode(i % 2 ? "111111" : "888888", 300 - i, i % 2 ? "1.1.1.1" : "192.168.100.100"); tick();
      matchesFullDraw();
      OmiPetUi::setPairingCode("123456", 10, "192.0.2.1"); tick();
      matchesFullDraw();
      OmiPetUi::setPairingCode(nullptr, 0); tick(); tick();
      matchesFullDraw();
    }
    OmiPetUi::setTaskScreen(false, false, nullptr); tick();
    writes = lcd.writes;
    OmiPetUi::setVoiceStatus("LISTENING");
    require(lcd.writes == writes, "voice setter never blocks on screen transfer");
    transfers = lcd.bitmaps;
    OmiPetUi::update();
    require(lcd.bitmaps == transfers + 1, "page transition transfers one bounded chunk per loop");
    OmiPetUi::setBatteryStatus(85, true);
    OmiPetUi::update();
    OmiPetUi::setPairingCode("123456", 120, "192.0.2.1");
    OmiPetUi::update();
    OmiPetUi::setNetworkStatus(true, false, "synthetic");
    tick(); matchesFullDraw();
    OmiPetUi::setPairingCode(nullptr, 0);
    OmiPetUi::update();
    OmiPetUi::setVoiceStatus("IDLE");
    tick(); matchesFullDraw();
    require(lcd.maxFill == 1, "no clear-before-draw anywhere");
    require(lcd.maxBitmap <= 206 * 50, "original buffer budget preserved");
    for (const auto& item : OmiPetUiFont::kGlyphs)
      require(item.offset + (item.width * item.height + 1) / 2 <= sizeof(OmiPetUiFont::kPixels), "font bounds");
    std::cout << "PASS companion_ui_regions_fonts_states_pairing_disconnect_no_caption\n";
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
