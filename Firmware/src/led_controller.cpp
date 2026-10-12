#include "led_controller.h"

#include <algorithm>
#include <cmath>

namespace OmiPetLed {
namespace {

//  所有动画参数集中放在这里，便于调节速度、柔和度和最低亮度 / Keep animation tuning parameters together for speed, softness, and minimum brightness
//  每 12 ms 最多发送一帧，约等于 83 FPS；动画不依赖 loop() 执行次数 / Send at most one frame every 12 ms, about 83 FPS; animation does not depend on loop count
constexpr uint32_t kFrameIntervalMs = 12;
//  彩虹颜色完成一整圈所需的时间 / Time required for the rainbow hue to complete one full cycle
constexpr uint32_t kRainbowCycleMs = 7200;
//  呼吸灯从暗到亮再回到暗的完整周期 / Full breathing cycle from dim to bright and back to dim
constexpr uint32_t kBreatheCycleMs = 3000;
//  光点从最左移动到最右再返回最左的完整周期 / Full sweep cycle from the left end to the right and back
constexpr uint32_t kSweepCycleMs = 3600;
//  光环从中心扩散到两侧再收回中心的完整周期 / Full cycle for the ring to expand from center and return
constexpr uint32_t kCenterExpandCycleMs = 4200;
//  余弦函数的数学常量 / Mathematical constants used by cosine easing
constexpr float kPi = 3.14159265358979323846F;
constexpr float kTwoPi = 2.0F * kPi;
//  中心扩散灯环保留约 22% 的基础亮度，移动高光只在此基础上叠加 / Keep about 22% base brightness for the center ring and add the moving highlight on top
constexpr float kAnimatedBaseGlow = 0.22F;
//  跑马灯远离高光时仍保留约 10% 亮度，但整条灯带会形成连续渐变 / Keep about 10% brightness away from the sweep highlight for a continuous gradient
constexpr float kSweepMinimumGlow = 0.10F;
//  跑马灯渐变覆盖范围，范围越大，亮暗过渡越宽 / Sweep gradient radius; a larger radius makes the bright-to-dim transition wider
constexpr float kSweepGradientRadius = 7.2F;
//  亮度计算的最低保底值，避免数值取整后完全熄灭 / Minimum level used to prevent rounding from turning a pixel completely off
constexpr uint8_t kAmbientLevel = 7;

//  呼吸灯默认使用纯蓝色；动画只改变亮度，不混入其他颜色 / Use pure blue for breathing by default; animation changes brightness only
constexpr uint8_t kBreatheRed = 0;
constexpr uint8_t kBreatheGreen = 0;
constexpr uint8_t kBreatheBlue = 255;
//  跑马灯默认使用纯绿色；动画只改变亮度，不混入其他颜色 / Use pure green for sweep by default; animation changes brightness only
constexpr uint8_t kSweepRed = 0;
constexpr uint8_t kSweepGreen = 255;
constexpr uint8_t kSweepBlue = 0;
//  扩散灯默认使用纯红色；动画只改变亮度，不混入其他颜色 / Use pure red for center expansion by default; animation changes brightness only
constexpr uint8_t kCenterExpandRed = 255;
constexpr uint8_t kCenterExpandGreen = 0;
constexpr uint8_t kCenterExpandBlue = 0;

//  将数值限制到 0.0 到 1.0，避免浮点误差导致亮度越界 / Clamp a value to 0.0 through 1.0 to prevent brightness overflow
float clampUnit(float value) {
  return std::max(0.0F, std::min(value, 1.0F));
}

//  根据距离计算柔和光晕：中心距离为 0 时最亮，超过半径时为 0 / Calculate a soft glow: brightest at distance 0 and zero beyond the radius
//  余弦曲线在边缘平滑收敛，比线性截断更适合连续灯效 / Cosine easing converges smoothly at the edge and avoids harsh linear cutoffs
float cosineFalloff(float distance, float radius) {
  if (radius <= 0.0F) {
    return 0.0F;
  }
  const float normalizedDistance = clampUnit(distance / radius);
  return 0.5F * (1.0F + std::cos(kPi * normalizedDistance));
}

//  把 0.0 到 1.0 的光晕强度映射到 LED 的 0 到 255 亮度 / Map glow intensity from 0.0 through 1.0 to LED level 0 through 255
//  先加入基础亮度，再四舍五入为整数，减少闪烁和截断误差 / Add ambient brightness first, then round to reduce flicker and truncation error
uint8_t levelFromGlow(float glow) {
  const float level = static_cast<float>(kAmbientLevel) +
                      clampUnit(glow) * (255.0F - kAmbientLevel);
  return static_cast<uint8_t>(std::lround(level));
}

//  在固定底光上叠加高光；高光消失时仍返回基础亮度 / Add a highlight over fixed base light; return the base level even when the highlight fades
uint8_t levelFromHighlight(float highlight) {
  const float base = clampUnit(kAnimatedBaseGlow);
  const float combinedGlow = base + (1.0F - base) * clampUnit(highlight);
  return levelFromGlow(combinedGlow);
}

//  按亮度比例缩放一个 RGB 分量，并保留非零颜色分量避免暗部偏色 / Scale one RGB component while preserving nonzero channels to reduce dark-color shifts
uint8_t scaleComponent(uint8_t component, uint8_t level) {
  if (component == 0U || level == 0U) {
    return 0;
  }
  const uint16_t scaled =
      (static_cast<uint16_t>(component) * level + 127U) / 255U;
  return static_cast<uint8_t>(std::max<uint16_t>(1U, scaled));
}

//  把移动高光转换为跑马灯的连续渐亮渐暗亮度 / Convert the moving highlight into a continuous sweep brightness
uint8_t levelFromSweepGradient(float gradient) {
  const float glow = kSweepMinimumGlow +
                     (1.0F - kSweepMinimumGlow) * clampUnit(gradient);
  return levelFromGlow(glow);
}

}  //  匿名命名空间 / Anonymous namespace

//  按应用层亮度缩放颜色，避免调用 NeoPixel 的有损 setBrightness() / Scale colors at the application layer to avoid NeoPixel's lossy setBrightness()
static uint8_t applyBrightness(uint8_t component, uint8_t brightness) {
  return static_cast<uint8_t>(
      (static_cast<uint16_t>(component) * brightness + 127U) / 255U);
}

//  创建底层 NeoPixel 对象：13 颗灯、GPIO47、GRB 顺序、800 kHz 协议 / Create the NeoPixel object: 13 LEDs, GPIO47, GRB order, and 800 kHz protocol
Strip::Strip() : pixels_(kLedCount, kDataPin, NEO_GRB + NEO_KHZ800) {}

//  初始化 WS2812B 外设并保存应用层亮度 / Initialize the WS2812B peripheral and store application-level brightness
void Strip::begin(uint8_t brightness) {
  //  禁用 NeoPixel 内部缩放，所有颜色都由本类完整写入后再发送 / Disable NeoPixel's internal scaling; this class writes every complete frame before transmission
  pixels_.begin();
  brightness_ = brightness;
  pixels_.setBrightness(255);
  //  上电先清空缓存并发送黑帧，避免灯带保留上一次的随机状态 / Clear and transmit a black frame at boot to avoid stale or random LED state
  clear(false);
  show();
}

//  清空灯珠缓存，并按参数决定是否立即发送 / Clear the pixel buffer and optionally transmit immediately
void Strip::clear(bool update) {
  //  clear() 只修改 RAM 缓存；update=true 时才立即把黑帧发送到灯带 / clear() changes only the RAM buffer; update=true also immediately sends the black frame
  pixels_.clear();
  if (update) {
    show();
  }
}

//  把当前缓存发送到灯带硬件 / Transmit the current buffer to the strip hardware
void Strip::show() {
  //  将当前缓存一次性发送给 WS2812B；动画每帧只在这里真正更新硬件 / Transmit the complete buffer to WS2812B; this is the only hardware update per animation frame
  pixels_.show();
}

//  更新应用层保存的全局亮度 / Update the application-level global brightness
void Strip::setBrightness(uint8_t brightness) {
  //  只保存亮度，不改写 NeoPixel 内部缓存，避免反复缩放造成颜色失真 / Store brightness without rewriting NeoPixel RAM, preventing repeated scaling from distorting colors
  brightness_ = brightness;
}

//  返回当前全局亮度值 / Return the current global brightness value
uint8_t Strip::brightness() const { return brightness_; }

//  按 RGB 分量写入一个灯珠缓存 / Write one pixel's RGB components to the buffer
void Strip::setPixel(uint16_t index, uint8_t red, uint8_t green,
                     uint8_t blue) {
  //  先写入缓存，不在单颗灯珠更新时发送；调用方完成整帧后再 show() / Write the buffer without transmitting; the caller calls show() after building the whole frame
  if (index < kLedCount) {
    pixels_.setPixelColor(index, pixels_.Color(
        applyBrightness(red, brightness_), applyBrightness(green, brightness_),
        applyBrightness(blue, brightness_)));
  }
}

//  按打包颜色值写入一个灯珠 / Write one pixel using a packed color value
void Strip::setPixel(uint16_t index, uint32_t colorValue) {
  //  允许动画直接写入 NeoPixel 打包颜色 / Allow effects to write a packed NeoPixel color directly
  if (index < kLedCount) {
    setPixel(index, static_cast<uint8_t>(colorValue >> 16),
             static_cast<uint8_t>(colorValue >> 8),
             static_cast<uint8_t>(colorValue));
  }
}

//  用 RGB 分量填充整条灯带 / Fill the entire strip with RGB components
void Strip::fill(uint8_t red, uint8_t green, uint8_t blue, bool update) {
  //  RGB 版本先转换为库使用的打包颜色，再复用统一的填充实现 / Convert RGB to the library's packed color and reuse the common fill implementation
  fill(color(red, green, blue), update);
}

//  用打包颜色值填充整条灯带 / Fill the entire strip with a packed color
void Strip::fill(uint32_t colorValue, bool update) {
  //  逐颗写入经过亮度缩放的颜色，确保每次都是从完整 RGB 状态重新渲染 / Write scaled colors pixel by pixel so every frame starts from complete RGB state
  for (uint16_t index = 0; index < kLedCount; ++index) {
    setPixel(index, colorValue);
  }
  if (update) {
    show();
  }
}

//  使用 HSV 参数设置一个灯珠，便于按色相生成动画 / Set one pixel from HSV values for hue-based effects
void Strip::setPixelHSV(uint16_t index, uint8_t hue, uint8_t saturation,
                        uint8_t value) {
  //  HSV 更适合彩虹动画：只改变 hue 就能连续移动色相 / HSV suits rainbow animation because changing hue alone moves the color continuously
  if (index < kLedCount) {
    setPixel(index, pixels_.ColorHSV(static_cast<uint16_t>(hue) * 256U,
                                     saturation, value));
  }
}

//  把 RGB 分量转换成 NeoPixel 使用的打包颜色值 / Pack RGB components into a NeoPixel color value
uint32_t Strip::color(uint8_t red, uint8_t green, uint8_t blue) const {
  //  使用 Adafruit_NeoPixel 的颜色打包方式，避免手动处理 GRB 顺序 / Use Adafruit_NeoPixel packing to avoid manually handling GRB byte order
  return pixels_.Color(red, green, blue);
}

//  根据 0 到 255 的位置生成一圈彩虹色 / Generate a rainbow color from a 0-to-255 wheel position
uint32_t Strip::colorWheel(uint8_t position) const {
  //  把 0 到 255 的位置映射为红、绿、蓝连续过渡的颜色 / Map position 0 through 255 to a continuous red-green-blue color transition
  position = 255 - position;
  if (position < 85) {
    return color(255 - position * 3, 0, position * 3);
  }
  if (position < 170) {
    position -= 85;
    return color(0, position * 3, 255 - position * 3);
  }
  position -= 170;
  return color(position * 3, 255 - position * 3, 0);
}

//  动画控制器只保存状态，并通过引用操作 Strip，不直接拥有硬件对象 / The effect controller stores state and operates on Strip by reference without owning hardware
EffectController::EffectController(Strip& strip) : strip_(strip) {}

//  初始化动效控制器并立即显示当前模式 / Initialize the effect controller and render the current mode
void EffectController::begin() {
  //  记录初始化时间；之后每个模式都用相对时间计算位置和亮度 / Record initialization time; each mode uses relative time for position and brightness
  initialized_ = true;
  modeStartedAtMs_ = millis();
  lastFrameAtMs_ = 0;
}

//  根据时间推进动画，并限制灯带刷新帧率 / Advance the animation by time and limit strip refresh rate
void EffectController::update() {
  //  常亮和关闭没有时间变化，不需要每次 loop() 重复发送 / Solid and off modes do not change over time and need no repeated loop transmission
  if (!initialized_ || mode_ == EffectMode::Solid || mode_ == EffectMode::Off) {
    return;
  }
  //  主循环只负责调用 update()；具体帧率和渲染由 render() 控制 / The main loop only calls update(); render() controls frame timing and drawing
  render(millis(), false);
}

//  立即重绘当前模式，用于亮度变化后从未缩放的颜色状态重新输出 / Immediately redraw the current mode after brightness changes from the complete color state
void EffectController::refresh() {
  if (!initialized_) {
    return;
  }
  render(millis(), true);
}

//  切换到指定 RGB 颜色的常亮模式 / Switch to solid mode with the requested RGB color
void EffectController::setSolid(uint8_t red, uint8_t green, uint8_t blue) {
  //  保存基础颜色；呼吸、扫描和扩散都以这组 RGB 为颜色来源 / Store the base color used by breathing, sweep, and expansion effects
  red_ = red;
  green_ = green;
  blue_ = blue;
  setSolid();
}

//  使用最近一次保存的常亮颜色 / Use the most recently saved solid color
void EffectController::setSolid() {
  //  切换模式后立即绘制一帧，让语音命令无需等待下一次 loop() / Render immediately after switching so a voice command does not wait for the next loop
  selectMode(EffectMode::Solid);
  render(millis(), true);
}

//  修改当前颜色但不改变正在运行的动效；彩虹和关灯状态保持原样 / Change the current color without changing the active effect; rainbow and off stay unchanged
void EffectController::setColor(uint8_t red, uint8_t green, uint8_t blue) {
  red_ = red;
  green_ = green;
  blue_ = blue;
  if (mode_ == EffectMode::Rainbow || mode_ == EffectMode::Off) {
    return;
  }
  render(millis(), true);
}

//  切换到连续循环的彩虹动效 / Switch to the continuously cycling rainbow effect
void EffectController::setRainbow() {
  //  彩虹模式沿用当前亮度，但每颗灯使用不同的色相偏移 / Rainbow mode uses current brightness with a hue offset for each LED
  selectMode(EffectMode::Rainbow);
  render(millis(), true);
}

//  切换到纯蓝色呼吸动效 / Switch to the pure-blue breathing effect
void EffectController::setBreathe() {
  //  进入呼吸灯时使用纯蓝色；之后的颜色命令仍可保留呼吸动效并切换颜色 / Start breathing in pure blue; later color commands keep the effect and change its color
  red_ = kBreatheRed;
  green_ = kBreatheGreen;
  blue_ = kBreatheBlue;
  selectMode(EffectMode::Breathe);
  render(millis(), true);
}

//  切换到带固定底光的纯绿色左右追逐动效 / Switch to the pure-green left-right sweep with fixed base light
void EffectController::setSweep() {
  //  进入跑马灯时使用纯绿色；之后的颜色命令仍可保留跑马灯并切换颜色 / Start sweep in pure green; later color commands keep the effect and change its color
  red_ = kSweepRed;
  green_ = kSweepGreen;
  blue_ = kSweepBlue;
  selectMode(EffectMode::Sweep);
  render(millis(), true);
}

//  切换到带固定底光的纯红色中心向外扩散动效 / Switch to the pure-red center-out expansion with fixed base light
void EffectController::setCenterExpand() {
  //  进入扩散灯时使用纯红色；之后的颜色命令仍可保留扩散动效并切换颜色 / Start expansion in pure red; later color commands keep the effect and change its color
  red_ = kCenterExpandRed;
  green_ = kCenterExpandGreen;
  blue_ = kCenterExpandBlue;
  selectMode(EffectMode::CenterExpand);
  render(millis(), true);
}

//  切换到关灯模式并立即发送黑帧 / Switch to off mode and send a black frame immediately
void EffectController::setOff() {
  //  关闭模式会清空缓存并发送黑帧 / Off mode clears the buffer and sends a black frame
  selectMode(EffectMode::Off);
  render(millis(), true);
}

//  返回当前动效模式 / Return the current effect mode
EffectMode EffectController::mode() const { return mode_; }

//  保存新模式并重置动画起始时间 / Store the new mode and reset its animation start time
void EffectController::selectMode(EffectMode mode) {
  //  每次切换模式都从 0 ms 重新开始，避免新动画接着旧动画的半途位置运行 / Restart each timeline at 0 ms so a new effect does not inherit the old effect's midpoint
  mode_ = mode;
  modeStartedAtMs_ = millis();
  lastFrameAtMs_ = 0;
}

//  根据当前模式选择具体渲染函数 / Dispatch rendering to the function for the current mode
void EffectController::render(uint32_t nowMs, bool force) {
  //  非强制渲染遵守 16 ms 帧间隔；无论 loop() 多快，都不会过度发送数据 / Non-forced rendering obeys the 16 ms interval and avoids excessive bus traffic regardless of loop speed
  if (!force && nowMs - lastFrameAtMs_ < kFrameIntervalMs) {
    return;
  }
  lastFrameAtMs_ = nowMs;
  //  使用无符号时间差，millis() 溢出时仍能正确工作 / Use unsigned elapsed time so the logic remains valid across millis() rollover
  const uint32_t elapsedMs = nowMs - modeStartedAtMs_;

  //  统一分派到当前模式的渲染函数，保持硬件层和动画层分离 / Dispatch to the active renderer while keeping hardware and animation layers separate
  switch (mode_) {
    case EffectMode::Solid:
      renderSolid();
      break;
    case EffectMode::Rainbow:
      renderRainbow(elapsedMs);
      break;
    case EffectMode::Breathe:
      renderBreathe(elapsedMs);
      break;
    case EffectMode::Sweep:
      renderSweep(elapsedMs);
      break;
    case EffectMode::CenterExpand:
      renderCenterExpand(elapsedMs);
      break;
    case EffectMode::Off:
      renderOff();
      break;
  }
}

//  渲染所有灯珠保持同一颜色的常亮画面 / Render a frame with one solid color on every pixel
void EffectController::renderSolid() {
  //  常亮模式把当前 RGB 写入整条缓存并发送 / Fill the complete buffer with the current RGB and transmit it
  strip_.fill(red_, green_, blue_);
}

//  根据经过时间计算每颗灯珠的彩虹色并发送 / Compute time-based rainbow colors for all pixels and send the frame
void EffectController::renderRainbow(uint32_t elapsedMs) {
  //  将经过时间折算为 0.0 到 1.0 的循环相位 / Convert elapsed time into a looping phase from 0.0 through 1.0
  const float phase = static_cast<float>(elapsedMs % kRainbowCycleMs) /
                      static_cast<float>(kRainbowCycleMs);
  //  基础色相随时间移动；每颗灯再叠加空间偏移，形成流动彩虹 / Move the base hue over time and add a spatial offset to create a flowing rainbow
  const uint8_t baseHue = static_cast<uint8_t>(phase * 256.0F);
  for (uint16_t index = 0; index < kLedCount; ++index) {
    //  按灯珠位置均匀分布色相，避免 13 颗灯显示成同一种颜色 / Distribute hue evenly across the 13 LEDs instead of showing one color everywhere
    const uint8_t offset = static_cast<uint8_t>(
        (static_cast<uint16_t>(index) * 256U) / kLedCount);
    strip_.setPixelHSV(index, static_cast<uint8_t>(baseHue + offset), 255, 255);
  }
  strip_.show();
}

//  用平滑曲线改变蓝紫色亮度，形成完整呼吸周期 / Modulate blue-purple brightness with a smooth full breathing cycle
void EffectController::renderBreathe(uint32_t elapsedMs) {
  //  相位从 0 到 1 循环；余弦波让亮度在最高点和最低点都平滑停留 / Loop phase from 0 to 1; cosine keeps brightness smooth at both extremes
  const float phase = static_cast<float>(elapsedMs % kBreatheCycleMs) /
                      static_cast<float>(kBreatheCycleMs);
  //  计算整体亮度波形，并保留少量基础亮度 / Calculate overall brightness and retain a small ambient level
  const float wave = 0.5F - 0.5F * std::cos(kTwoPi * phase);
  const uint8_t level = levelFromGlow(0.04F + wave * 0.96F);
  //  呼吸动效使用当前颜色，三个分量同步缩放以保持色相 / Breathing uses the current color and scales all components together to preserve hue
  strip_.fill(scaleComponent(red_, level), scaleComponent(green_, level),
              scaleComponent(blue_, level));
}

//  让柔和高光从左向右再返回，同时保留整条底光 / Move a soft highlight left and right while keeping the strip base-lit
void EffectController::renderSweep(uint32_t elapsedMs) {
  //  把时间转换为线性往返相位，端点立即反向，避免到边缘停顿 / Convert time to a linear ping-pong phase so endpoints reverse without pausing
  const float phase = static_cast<float>(elapsedMs % kSweepCycleMs) /
                      static_cast<float>(kSweepCycleMs);
  const float pingPong = phase < 0.5F ? phase * 2.0F : (1.0F - phase) * 2.0F;
  const float position = static_cast<float>(kLedCount - 1U) * pingPong;
  for (uint16_t index = 0; index < kLedCount; ++index) {
    //  距离越近越亮，距离越远越暗，但整条灯带保留连续的最低亮度 / LEDs get brighter near the point and dimmer farther away while keeping a continuous minimum
    const float distance = std::fabs(static_cast<float>(index) - position);
    const uint8_t level = levelFromSweepGradient(
        cosineFalloff(distance, kSweepGradientRadius));
    //  跑马灯使用当前颜色，颜色命令不会把动效改成常亮 / Sweep uses the current color; color commands do not switch it to solid mode
    strip_.setPixel(index, scaleComponent(red_, level),
                    scaleComponent(green_, level), scaleComponent(blue_, level));
  }
  strip_.show();
}

//  让纯红色光环从中心扩散到边缘再返回，并保留固定底光 / Expand a pure-red ring from center to edge and back with base light
void EffectController::renderCenterExpand(uint32_t elapsedMs) {
  //  计算中心对称的动画相位，中心和最外侧分别对应半径 0 和最大半径 / Calculate a center-symmetric phase where radius 0 is center and maximum radius is the edge
  const float phase = static_cast<float>(elapsedMs % kCenterExpandCycleMs) /
                      static_cast<float>(kCenterExpandCycleMs);
  //  13 颗灯的几何中心位于索引 6；最大半径约为 6 个灯珠间距 / The geometric center of 13 LEDs is index 6; maximum radius is about six LED spacings
  const float maximumRadius = static_cast<float>(kLedCount - 1U) * 0.5F;
  //  线性半径从中心走到边缘再立即反向，避免中心和边缘停顿 / Linear radius travels center-to-edge and reverses immediately to avoid pauses
  const float pingPong = phase < 0.5F ? phase * 2.0F : (1.0F - phase) * 2.0F;
  const float radius = maximumRadius * pingPong;
  const float center = maximumRadius;
  for (uint16_t index = 0; index < kLedCount; ++index) {
    //  用灯珠距中心的距离与当前光环半径比较，得到光环厚度方向的距离 / Compare each LED's center distance with the ring radius to get distance from the ring
    const float distanceFromCenter =
        std::fabs(static_cast<float>(index) - center);
    const float ringDistance = std::fabs(distanceFromCenter - radius);
    //  同时叠加核心光环和外围光晕，且始终保留固定底光 / Combine a bright ring with a wider halo while always retaining fixed base light
    const float core = cosineFalloff(ringDistance, 1.25F);
    const float halo = cosineFalloff(ringDistance, 3.8F) * 0.34F;
    const uint8_t level = levelFromHighlight(std::max(core, halo));
    //  中心扩散使用当前颜色，中心和边缘都不会因动画位置变化而熄灭 / Center expansion uses the current color; center and edge never turn off as the ring moves
    strip_.setPixel(index, scaleComponent(red_, level),
                    scaleComponent(green_, level), scaleComponent(blue_, level));
  }
  strip_.show();
}

//  清空缓存并发送黑帧，确保灯带真正熄灭 / Clear the buffer and transmit black so the strip is actually off
void EffectController::renderOff() {
  //  先清理缓存，再发送黑帧，确保灯珠实际熄灭 / Clear the buffer first, then transmit a black frame so the LEDs actually turn off
  strip_.clear(false);
  strip_.show();
}

//  全局硬件对象和动画控制器；控制器引用 strip，不复制或重新拥有硬件缓存 / Global hardware object and effect controller; the controller references strip without copying or owning its buffer
Strip strip;
EffectController effects(strip);

//  暴露底层对象给需要读取 NeoPixel 状态的调试代码 / Expose the underlying object to diagnostic code that needs NeoPixel state
//  返回可修改的底层 NeoPixel 对象 / Return the mutable underlying NeoPixel object
Adafruit_NeoPixel& Strip::pixels() { return pixels_; }
//  返回只读的底层 NeoPixel 对象 / Return the read-only underlying NeoPixel object
const Adafruit_NeoPixel& Strip::pixels() const { return pixels_; }

}  //  OmiPetLed 命名空间 / OmiPetLed namespace
