#include <Arduino.h>
#include <cstdlib>
#include <functional>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include "device_protocol_envelope.h"
#include "device_protocol_experiment.h"
#include "device_protocol_framer.h"

FakeSerial Serial;
using OmiPetProtocol::EnvelopeInfo;
using OmiPetProtocol::EnvelopeResult;
using OmiPetProtocol::FeedResult;
using OmiPetProtocol::SerialFramer;

#define REQUIRE(value) do { if (!(value)) throw std::runtime_error(#value); } while (false)

namespace {
std::size_t gDebugWakes = 0;
void wake() { ++gDebugWakes; }

std::string envelope(const std::string& body = "{}", const std::string& type = "snapshot") {
  const std::string id(32, 'a');
  return "{\"v\":1,\"boot\":\"" + id + "\",\"channel\":\"" + id + "\",\"session\":\"" + id +
         "\",\"seq\":1,\"type\":\"" + type + "\",\"body\":" + body + "}";
}

EnvelopeResult inspect(const std::string& text, std::size_t depth = 8) {
  EnvelopeInfo info;
  return OmiPetProtocol::inspectEnvelope(text.data(), text.size(), depth, info);
}

void drain() {
  while (Serial.available()) {
    const std::size_t before = Serial.reads;
    OmiPetProtocol::pollSerialExperiment(wake);
    REQUIRE(Serial.reads > before);
    REQUIRE(Serial.reads - before <= OMIPET_PROTOCOL_RX_BYTES_PER_LOOP);
  }
}

void completeFrame() {
  SerialFramer<64> framer;
  std::size_t ready = 0;
  for (unsigned char byte : std::string("@OMI {\"working\":true}\r\n")) {
    const FeedResult result = framer.feed(byte);
    REQUIRE(result != FeedResult::DebugWake);
    if (result == FeedResult::FrameReady) ++ready;
  }
  REQUIRE(ready == 1);
  REQUIRE(std::string(framer.frame(), framer.frameLength()) == "{\"working\":true}");
}

void partialFrame() {
  SerialFramer<64> framer;
  for (unsigned char byte : std::string("@OMI {\"w\":1}")) REQUIRE(framer.feed(byte) == FeedResult::None);
  REQUIRE(framer.feed('\n') == FeedResult::FrameReady);
}

void exactLimitAndCrlf() {
  SerialFramer<4> framer;
  for (unsigned char byte : std::string("@OMI abcd\r")) REQUIRE(framer.feed(byte) == FeedResult::None);
  REQUIRE(framer.feed('\n') == FeedResult::FrameReady);
  REQUIRE(framer.frameLength() == 4);
  REQUIRE(std::string(framer.frame()) == "abcd");
}

void overflowAndRecovery() {
  SerialFramer<4> framer;
  std::size_t rejected = 0;
  for (unsigned char byte : std::string("@OMI ") + std::string(10000, 'w') + "\n@OMI {}\n") {
    const FeedResult result = framer.feed(byte);
    REQUIRE(result != FeedResult::DebugWake);
    if (result == FeedResult::TooLong) ++rejected;
  }
  REQUIRE(rejected == 1);
  REQUIRE(std::string(framer.frame()) == "{}");
}

void badPrefixAndNulNeverReplayDebug() {
  SerialFramer<64> framer;
  const std::string stream = std::string("@w working\n@OMI {\"w\":") + std::string(1, '\0') + "working}\nw";
  std::size_t wakeCount = 0;
  for (unsigned char byte : stream) if (framer.feed(byte) == FeedResult::DebugWake) ++wakeCount;
  REQUIRE(wakeCount == 1);
}

void repeatedExternalDebug() {
  SerialFramer<64> framer;
  REQUIRE(framer.feed('w') == FeedResult::DebugWake);
  REQUIRE(framer.feed('w') == FeedResult::DebugWake);
}

void envelopeTypesAndUint32() {
  for (const std::string type : {"hello", "heartbeat", "snapshot", "release"}) {
    EnvelopeInfo info;
    const std::string text = envelope("{}", type);
    REQUIRE(OmiPetProtocol::inspectEnvelope(text.data(), text.size(), 8, info) == EnvelopeResult::Valid);
    REQUIRE(info.sequence == 1);
  }
  std::string maxSeq = envelope();
  maxSeq.replace(maxSeq.find("\"seq\":1"), 7, "\"seq\":4294967295");
  REQUIRE(inspect(maxSeq) == EnvelopeResult::Valid);
}

void booleanVersionsAndBadSequences() {
  for (const std::string number : {"true", "0", "-1", "1.0", "1e0", "1.5", "01", "1-2", "--1", "4294967296"}) {
    std::string text = envelope();
    text.replace(text.find("\"seq\":1"), 7, "\"seq\":" + number);
    REQUIRE(inspect(text) == EnvelopeResult::InvalidEnvelope);
  }
  std::string text = envelope();
  text.replace(text.find("\"v\":1"), 5, "\"v\":true");
  REQUIRE(inspect(text) == EnvelopeResult::InvalidEnvelope);
}

void strictShapeAndNoTrailingCommand() {
  REQUIRE(inspect(envelope() + "w") == EnvelopeResult::InvalidJson);
  REQUIRE(inspect(envelope() + " {}") == EnvelopeResult::InvalidJson);
  REQUIRE(inspect(envelope("[]")) == EnvelopeResult::InvalidEnvelope);
  REQUIRE(inspect(envelope("{}", "setLight")) == EnvelopeResult::InvalidEnvelope);
  REQUIRE(inspect("[]") == EnvelopeResult::InvalidEnvelope);
  REQUIRE(inspect("{") == EnvelopeResult::InvalidJson);
}

void duplicateKeysIncludingNestedObjects() {
  REQUIRE(inspect(envelope("{\"a\":1,\"a\":2}")) == EnvelopeResult::DuplicateKey);
  REQUIRE(inspect(envelope("{\"a\":[{\"x\":1,\"x\":2}]}")) == EnvelopeResult::DuplicateKey);
  std::string text = envelope();
  text.insert(1, "\"v\":1,");
  REQUIRE(inspect(text) == EnvelopeResult::DuplicateKey);
}

void utf8AndEmbeddedNul() {
  REQUIRE(inspect(envelope(u8"{\"text\":\"中文\"}")) == EnvelopeResult::Valid);
  for (const std::string& invalid : {std::string("\xFF"), std::string("\xC0\x80"),
                                   std::string("\xED\xA0\x80"), std::string("\xF4\x90\x80\x80")}) {
    REQUIRE(inspect(envelope("{\"text\":\"" + invalid + "\"}")) == EnvelopeResult::InvalidText);
  }
  REQUIRE(inspect(envelope("{\"text\":\"\\u0000\"}")) == EnvelopeResult::InvalidText);
  REQUIRE(inspect(envelope("{\"text\":\"\\\\u0000\"}")) == EnvelopeResult::Valid);
}

void depthBudgetAndQuotedBrackets() {
  REQUIRE(inspect(envelope("{\"nested\":[[[[[]]]]]}"), 3) == EnvelopeResult::DepthExceeded);
  REQUIRE(inspect(envelope("{\"text\":\"[[[[[\\\"}}\"}"), 2) == EnvelopeResult::Valid);
}

void adapterBudgetAndFrameIsolation() {
  const std::size_t before = gDebugWakes;
  const std::string json = envelope("{\"text\":\"working waitingApproval\"}");
  Serial.append("\nww\n@OMI " + json + "\n@OMI " + std::string(5000, 'w') + "\nw\n");
  drain();
  REQUIRE(gDebugWakes - before == 3);
  REQUIRE(Serial.output.find("envelope_valid") != std::string::npos);
  REQUIRE(Serial.output.find("frame_rejected") != std::string::npos);
  REQUIRE(Serial.output.find("execution=disabled") != std::string::npos);
  REQUIRE(Serial.output.find("waitingApproval") == std::string::npos);
}

void binaryFuzzFramesRemainIsolated() {
  for (unsigned value = 0; value < 256; ++value) {
    SerialFramer<8> framer;
    const std::string frame = "@OMI " + std::string(3, static_cast<char>(value));
    for (unsigned char byte : frame) REQUIRE(framer.feed(byte) != FeedResult::DebugWake);
  }
}
}  //  测试内部命名空间 / Internal test namespace

int main(int argc, char** argv) {
  const std::vector<std::pair<const char*, std::function<void()>>> tests = {
      {"complete_frame", completeFrame}, {"partial_frame", partialFrame},
      {"exact_limit_crlf", exactLimitAndCrlf}, {"overflow_recovery", overflowAndRecovery},
      {"prefix_nul_isolation", badPrefixAndNulNeverReplayDebug}, {"external_debug", repeatedExternalDebug},
      {"envelope_types_uint32", envelopeTypesAndUint32}, {"invalid_numbers", booleanVersionsAndBadSequences},
      {"strict_shape_trailing", strictShapeAndNoTrailingCommand}, {"duplicate_keys", duplicateKeysIncludingNestedObjects},
      {"utf8_nul", utf8AndEmbeddedNul}, {"depth_quoted_brackets", depthBudgetAndQuotedBrackets},
      {"adapter_budget_isolation", adapterBudgetAndFrameIsolation}, {"binary_fuzz", binaryFuzzFramesRemainIsolated}};
  for (const auto& test : tests) {
    try { test.second(); }
    catch (const std::exception& error) {
      std::cerr << "FAIL " << test.first << ": " << error.what() << '\n';
      return EXIT_FAILURE;
    }
    std::cout << "PASS " << test.first << '\n';
  }
  std::size_t count = tests.size();
  if (argc == 2) {
    std::ifstream fixture(argv[1], std::ios::binary);
    REQUIRE(fixture.good());
    std::string line;
    std::size_t frames = 0;
    while (std::getline(fixture, line)) {
      SerialFramer<4096> framer;
      for (unsigned char byte : line) REQUIRE(framer.feed(byte) == FeedResult::None);
      REQUIRE(framer.feed('\n') == FeedResult::FrameReady);
      EnvelopeInfo info;
      REQUIRE(OmiPetProtocol::inspectEnvelope(framer.frame(), framer.frameLength(), 8, info) == EnvelopeResult::Valid);
      ++frames;
    }
    REQUIRE(frames == 4);
    std::cout << "PASS python_wire_fixtures\n";
    ++count;
  }
  std::cout << "native_tests=" << count << '\n';
}
