#include <cassert>
#include <cstdio>
#include "led_controller.h"

uint32_t gNowMs = 100;
uint32_t millis() { return gNowMs; }

int main() {
  OmiPetLed::Strip strip;
  OmiPetLed::EffectController local(strip);
  OmiPetLed::EffectController monitor(strip);
  strip.begin(16);
  local.begin();
  local.setSweep();
  local.setColor(0, 0, 255);
  assert(local.mode() == OmiPetLed::EffectMode::Sweep);

  monitor.begin();
  monitor.setCenterExpand(255, 255, 0);
  assert(monitor.mode() == OmiPetLed::EffectMode::CenterExpand);
  assert(local.mode() == OmiPetLed::EffectMode::Sweep);
  uint32_t center = strip.pixels().getPixelColor(6);
  assert(((center >> 16) & 0xff) == ((center >> 8) & 0xff) &&
         (center & 0x00ff0000) != 0 && (center & 0xff) == 0);
  gNowMs += 1000;
  const uint32_t before = strip.pixels().showCount();
  monitor.update();
  assert(strip.pixels().showCount() > before);
  assert(strip.pixels().getPixelColor(6) != center);
  std::puts("PASS monitor_center_expansion_animates");

  monitor.setColor(0, 255, 0);
  center = strip.pixels().getPixelColor(6);
  assert((center & 0x00ff0000) == 0 && (center & 0x0000ff00) != 0 && (center & 0xff) == 0);
  assert(monitor.mode() == OmiPetLed::EffectMode::CenterExpand);
  std::puts("PASS status_color_changes_keep_expansion");

  local.refresh();
  center = strip.pixels().getPixelColor(6);
  assert((center & 0x00ffff00) == 0 && (center & 0xff) != 0);
  assert(local.mode() == OmiPetLed::EffectMode::Sweep);
  assert(strip.brightness() == 16);
  std::puts("PASS local_effect_restored_without_mutation");

  local.setSolid(0, 0, 255);
  OmiPetLed::EffectController wake(strip);
  wake.begin();
  wake.setSweep(255, 255, 255);
  assert(wake.mode() == OmiPetLed::EffectMode::Sweep);
  assert(local.mode() == OmiPetLed::EffectMode::Solid);
  center = strip.pixels().getPixelColor(6);
  assert(center != 0 && ((center >> 16) & 0xff) == ((center >> 8) & 0xff) &&
         ((center >> 8) & 0xff) == (center & 0xff));
  const uint32_t wakeShows = strip.pixels().showCount();
  gNowMs += 100;
  wake.update();
  assert(strip.pixels().showCount() > wakeShows);
  local.refresh();
  assert(strip.pixels().getPixelColor(6) == strip.pixels().getPixelColor(0));
  assert((strip.pixels().getPixelColor(6) & 0x00ffff00) == 0);
  assert((strip.pixels().getPixelColor(6) & 0xff) != 0);
  std::puts("PASS white_wake_sweep_preserves_blue_solid");

  local.setOff();
  wake.setSweep(255, 255, 255);
  local.refresh();
  for (uint16_t index = 0; index < OmiPetLed::kLedCount; ++index) {
    assert(strip.pixels().getPixelColor(index) == 0);
  }
  std::puts("PASS local_off_restored");

  const uint32_t configurationShows = strip.pixels().showCount();
  local.setConfiguration(OmiPetLed::EffectMode::Sweep, 255, 0, 0);
  assert(strip.pixels().showCount() == configurationShows + 1);
  for (uint16_t index = 0; index < OmiPetLed::kLedCount; ++index) {
    assert((strip.pixels().getPixelColor(index) & 0x0000ffff) == 0);
  }
  std::puts("PASS desktop_configuration_has_no_intermediate_color_frame");
}
