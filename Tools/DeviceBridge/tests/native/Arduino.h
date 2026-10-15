#pragma once

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <string>

//  主机测试替身，不用于固件构建 / Host test double, excluded from firmware builds
class FakeSerial {
 public:
  std::deque<unsigned char> input;
  std::string output;
  std::size_t reads = 0;
  int available() const { return static_cast<int>(input.size()); }
  int read() {
    if (input.empty()) return -1;
    const int result = input.front();
    input.pop_front();
    ++reads;
    return result;
  }
  void append(const std::string& data) {
    for (unsigned char byte : data) input.push_back(byte);
  }
  int printf(const char* format, ...) {
    char buffer[512];
    va_list arguments;
    va_start(arguments, format);
    const int length = std::vsnprintf(buffer, sizeof(buffer), format, arguments);
    va_end(arguments);
    if (length > 0 && static_cast<std::size_t>(length) < sizeof(buffer)) output.append(buffer, length);
    return length;
  }
};

extern FakeSerial Serial;
uint32_t millis();
