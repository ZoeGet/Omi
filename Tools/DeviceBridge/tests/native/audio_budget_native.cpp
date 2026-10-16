#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <deque>

namespace OmiPetAudio { constexpr size_t kPcmAudioFrameSamples = 160; }
constexpr size_t kMaxCommandFramesPerLoop = 4;
int16_t gCommandPcmFrame[OmiPetAudio::kPcmAudioFrameSamples];
struct AudioQueue {
  std::deque<int16_t> frames;
  bool popFrame(int16_t* frame, size_t) {
    if (frames.empty()) return false;
    *frame = frames.front();
    frames.pop_front();
    return true;
  }
} gCommandAudioBuffer;

size_t drain() {
  size_t processedFrameCount = 0;
  //  直接编译主循环条件，避免测试另写一份正确实现 / Compile the main-loop condition itself instead of testing a separate correct copy
#include "audio_budget_loop.h"
  { ++processedFrameCount; }
  return processedFrameCount;
}

int main() {
  gCommandAudioBuffer.frames = {1, 2, 3, 4, 5};
  assert(drain() == 4);
  assert(gCommandAudioBuffer.frames.size() == 1);
  assert(gCommandAudioBuffer.frames.front() == 5);
  assert(drain() == 1 && gCommandPcmFrame[0] == 5);
  assert(drain() == 0);
  std::puts("PASS audio_budget_preserves_next_frame_for_next_loop");
}
