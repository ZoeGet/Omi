#pragma once

#include <cstddef>
#include <cstdint>

namespace OmiPetProtocol {

//  字节分帧结果，协议内容永远不作为调试字符重放 / Byte-framing outcomes; protocol content is never replayed as debug characters
enum class FeedResult { None, DebugWake, FrameReady, PrefixMismatch, TooLong, InvalidByte };

//  固定容量分帧器，无堆分配且每个字节只执行有限步骤 / Fixed-capacity framer without heap allocation and with bounded work per byte
template <std::size_t MaxJsonBytes>
class SerialFramer {
  static_assert(MaxJsonBytes > 0, "JSON capacity must be positive");

 public:
  FeedResult feed(uint8_t byte) {
    if (mode_ == Mode::Discard) {
      if (byte == '\n') resetLine();
      return FeedResult::None;
    }
    if (mode_ == Mode::Prefix) {
      if (byte != static_cast<uint8_t>("@OMI "[prefixPosition_])) {
        if (byte == '\n') resetLine();
        else mode_ = Mode::Discard;
        return FeedResult::PrefixMismatch;
      }
      if (++prefixPosition_ == 5) {
        mode_ = Mode::Body;
        cursor_ = 0;
      }
      return FeedResult::None;
    }
    if (mode_ == Mode::Body) {
      if (byte == '\n') {
        frameLength_ = cursor_;
        if (frameLength_ && buffer_[frameLength_ - 1] == '\r') --frameLength_;
        buffer_[frameLength_] = '\0';
        resetLine();
        return FeedResult::FrameReady;
      }
      if (byte == 0) {
        mode_ = Mode::Discard;
        return FeedResult::InvalidByte;
      }
      if (cursor_ >= MaxJsonBytes && !(cursor_ == MaxJsonBytes && byte == '\r')) {
        mode_ = Mode::Discard;
        return FeedResult::TooLong;
      }
      buffer_[cursor_++] = static_cast<char>(byte);
      return FeedResult::None;
    }
    if (byte == '\n' || byte == '\r') {
      atLineStart_ = true;
      return FeedResult::None;
    }
    if (atLineStart_ && byte == '@') {
      mode_ = Mode::Prefix;
      prefixPosition_ = 1;
      return FeedResult::None;
    }
    atLineStart_ = false;
    return byte == 'w' ? FeedResult::DebugWake : FeedResult::None;
  }

  const char* frame() const { return buffer_; }
  std::size_t frameLength() const { return frameLength_; }
  //  断连后丢弃残留半帧，下一换行恢复，避免旧正文变成调试输入 / Drop residual partial frames after disconnect until newline, preventing stale debug input
  void discardUntilNewline() { resetLine(); mode_ = Mode::Discard; }

 private:
  enum class Mode { Text, Prefix, Body, Discard };
  void resetLine() {
    mode_ = Mode::Text;
    atLineStart_ = true;
    prefixPosition_ = 0;
    cursor_ = 0;
  }

  char buffer_[MaxJsonBytes + 2] = {};
  std::size_t cursor_ = 0;
  std::size_t frameLength_ = 0;
  std::size_t prefixPosition_ = 0;
  Mode mode_ = Mode::Text;
  bool atLineStart_ = true;
};

}  //  协议命名空间 / Protocol namespace
