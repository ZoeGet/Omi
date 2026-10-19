#pragma once

#include <cstdint>

namespace OmiPetProtocol {
//  最多四个固定槽位，标题为上位机生成的160×16单色位图 / Up to four fixed slots with host-rendered 160x16 monochrome titles
struct TaskCard {
  bool used = false;
  bool waiting = false;
  uint8_t pixels[320] = {};
};
struct TaskScreen {
  bool available = false;
  uint8_t active = 0;
  bool hasLabels = false;
  uint8_t labels[256] = {};
  TaskCard cards[4];
};
}  //  协议命名空间 / Protocol namespace
