#pragma once

#include <cstdint>
#include <vector>

constexpr int NEO_GRB = 1;
constexpr int NEO_KHZ800 = 2;

//  原生测试仅记录灯珠缓存和发送次数，不连接 GPIO / Native tests record pixel buffers and frame sends without GPIO
class Adafruit_NeoPixel {
 public:
  Adafruit_NeoPixel(uint16_t count, uint8_t, int) : pixels_(count, 0) {}
  void begin() {}
  void setBrightness(uint8_t) {}
  void clear() { for (auto& pixel : pixels_) pixel = 0; }
  void show() { ++showCount_; }
  void setPixelColor(uint16_t index, uint32_t color) { pixels_.at(index) = color; }
  uint32_t getPixelColor(uint16_t index) const { return pixels_.at(index); }
  uint32_t Color(uint8_t red, uint8_t green, uint8_t blue) const {
    return (static_cast<uint32_t>(red) << 16) |
           (static_cast<uint32_t>(green) << 8) | blue;
  }
  uint32_t ColorHSV(uint16_t, uint8_t, uint8_t) const { return 0; }
  uint32_t showCount() const { return showCount_; }

 private:
  std::vector<uint32_t> pixels_;
  uint32_t showCount_ = 0;
};
