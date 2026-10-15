#pragma once

#include <Arduino.h>
#include <Adafruit_NeoPixel.h>

namespace OmiPetLed {

//  WS2812B 硬件映射常量 / WS2812B hardware mapping constants
constexpr uint8_t kDataPin = 47;  //  WS2812B 数据引脚 / WS2812B data pin
constexpr uint16_t kLedCount = 13;  //  原理图中的 LED2 至 LED14 / LED2 through LED14 in the schematic

//  只负责 NeoPixel 缓存、亮度和总线发送 / Own only the NeoPixel buffer, brightness, and bus output
class Strip {
 public:
  //  创建 WS2812B 灯带对象 / Create the WS2812B strip object
  Strip();
  //  初始化硬件并保存应用层亮度 / Initialize hardware and store application-level brightness
  void begin(uint8_t brightness = 64);
  //  清空缓存并按需立即发送 / Clear the buffer and optionally transmit immediately
  void clear(bool update = true);
  //  将缓存发送到 WS2812B / Transmit the buffer to WS2812B
  void show();
  //  设置应用层全局亮度，范围为 0–255 / Set application-level global brightness from 0 to 255
  void setBrightness(uint8_t brightness);
  //  获取当前应用层全局亮度 / Get the current application-level global brightness
  uint8_t brightness() const;
  //  按 RGB 设置单颗灯珠缓存 / Set one pixel in the buffer by RGB
  void setPixel(uint16_t index, uint8_t red, uint8_t green, uint8_t blue);
  //  设置单颗灯珠的打包颜色缓存 / Set one pixel in the buffer by packed color
  void setPixel(uint16_t index, uint32_t color);
  //  用 RGB 填充缓存 / Fill the buffer with RGB
  void fill(uint8_t red, uint8_t green, uint8_t blue, bool update = true);
  //  用打包颜色填充缓存 / Fill the buffer with packed color
  void fill(uint32_t color, bool update = true);
  //  按 HSV 设置单颗灯珠缓存 / Set one pixel in the buffer by HSV
  void setPixelHSV(uint16_t index, uint8_t hue, uint8_t saturation,
                   uint8_t value);
  //  将 RGB 转换为 NeoPixel 打包颜色 / Convert RGB to a NeoPixel packed color
  uint32_t color(uint8_t red, uint8_t green, uint8_t blue) const;
  //  根据色轮位置生成颜色 / Generate a color from a color-wheel position
  uint32_t colorWheel(uint8_t position) const;
  //  获取底层 NeoPixel 对象 / Get the underlying NeoPixel object
  Adafruit_NeoPixel& pixels();
  //  获取只读底层 NeoPixel 对象 / Get the read-only underlying NeoPixel object
  const Adafruit_NeoPixel& pixels() const;

 private:
  Adafruit_NeoPixel pixels_;
  uint8_t brightness_ = 64;  //  当前全局亮度 / Current global brightness
};

extern Strip strip;

//  动效模式枚举 / LED effect mode enumeration
enum class EffectMode : uint8_t {
  Solid,
  Rainbow,
  Breathe,
  Sweep,
  CenterExpand,
  Off,
};

//  只负责颜色状态、时间轴和动画渲染 / Own only color state, timelines, and animation rendering
class EffectController {
 public:
  //  将动画控制器绑定到硬件缓存 / Bind the effect controller to hardware buffering
  explicit EffectController(Strip& strip);
  //  初始化动画时间轴 / Initialize animation timelines
  void begin();
  //  在主循环中推进动画 / Advance animation from the main loop
  void update();
  //  立即按当前模式完整重绘一帧 / Immediately redraw one complete frame for the current mode
  void refresh();
  //  一次更新颜色和模式后只绘制一帧，避免上位机命令产生中间颜色 / Update color and mode together and draw once to avoid intermediate desktop-command colors
  void setConfiguration(EffectMode mode, uint8_t red, uint8_t green, uint8_t blue);
  //  设置颜色并切换到常亮 / Set color and switch to solid mode
  void setSolid(uint8_t red, uint8_t green, uint8_t blue);
  //  用当前颜色切换到常亮 / Switch to solid mode using current color
  void setSolid();
  //  修改当前颜色但保留正在运行的动效；彩虹和关灯模式不立即改变画面 / Change the current color without leaving the active effect; rainbow and off keep their frame
  void setColor(uint8_t red, uint8_t green, uint8_t blue);
  //  设置彩虹动效 / Set rainbow effect
  void setRainbow();
  //  设置全灯带呼吸动效 / Set whole-strip breathing effect
  void setBreathe();
  //  设置左右往返渐变扫描 / Set left-to-right ping-pong sweep
  void setSweep();
  //  以指定颜色开始跑马灯，避免先显示默认绿色帧 / Start the sweep in the requested color without a transient default-green frame
  void setSweep(uint8_t red, uint8_t green, uint8_t blue);
  //  设置中心向外扩散再收回 / Set center-outward expansion and return
  void setCenterExpand();
  //  以指定颜色开始中心扩散，避免先显示默认红色帧 / Start center expansion in the requested color without a transient default-red frame
  void setCenterExpand(uint8_t red, uint8_t green, uint8_t blue);
  //  关闭灯带输出 / Turn off strip output
  void setOff();
  //  获取当前动画模式 / Get current animation mode
  EffectMode mode() const;

 private:
  //  根据模式选择对应的渲染函数 / Select the renderer for the current mode
  void selectMode(EffectMode mode);
  //  判断是否需要刷新，并按模式绘制当前时间点的画面 / Decide whether to refresh and render the current time point
  void render(uint32_t nowMs, bool force);
  //  绘制常亮颜色 / Render the solid color frame
  void renderSolid();
  //  绘制彩虹循环帧 / Render one rainbow frame
  void renderRainbow(uint32_t elapsedMs);
  //  绘制呼吸亮度帧 / Render one breathing-brightness frame
  void renderBreathe(uint32_t elapsedMs);
  //  绘制左右往返追逐帧 / Render one left-right sweep frame
  void renderSweep(uint32_t elapsedMs);
  //  绘制中心向外扩散帧 / Render one center-expansion frame
  void renderCenterExpand(uint32_t elapsedMs);
  //  绘制全黑帧 / Render one fully-off frame
  void renderOff();

  Strip& strip_;  //  动画写入的硬件缓存 / Hardware buffer written by animation
  EffectMode mode_ = EffectMode::Solid;
  uint8_t red_ = 255;  //  当前颜色红色分量 / Current red component
  uint8_t green_ = 255;  //  当前颜色绿色分量 / Current green component
  uint8_t blue_ = 255;  //  当前颜色蓝色分量 / Current blue component
  uint32_t modeStartedAtMs_ = 0;
  uint32_t lastFrameAtMs_ = 0;
  bool initialized_ = false;
};

extern EffectController effects;

}  //  OmiPetLed 命名空间 / OmiPetLed namespace
