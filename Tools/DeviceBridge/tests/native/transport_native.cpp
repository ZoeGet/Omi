#include "device_protocol_transport.h"
#include "cJSON.h"
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void require(bool value, const char* reason) { if (!value) throw std::runtime_error(reason); }
unsigned wakes = 0, generation = 0;
void wake() { ++wakes; }
void token(char* value) { std::snprintf(value, 33, "%032x", ++generation); }
struct Port {
  bool cable = true, canSend = true, shortWrite = false;
  int space = 8192;
  std::size_t reads = 0;
  std::deque<uint8_t> input;
  std::vector<std::string> output;
  bool plugged() const { return cable; }
  bool ready() const { return canSend; }
  int available() const { return static_cast<int>(input.size()); }
  int availableForWrite() const { return space; }
  int read() { const int result = input.front(); input.pop_front(); ++reads; return result; }
  std::size_t write(const uint8_t* bytes, std::size_t size) {
    require(size <= static_cast<std::size_t>(space), "whole frame must fit");
    output.emplace_back(reinterpret_cast<const char*>(bytes), shortWrite ? size / 2 : size);
    return shortWrite ? size / 2 : size;
  }
  void add(const std::string& text) { for (uint8_t byte : text) input.push_back(byte); }
};
struct Fixture {
  OmiPetProtocol::ProtocolTransport<4096> transport{"11111111111111111111111111111111", 16, 8, 1000};
  Port port;
  std::string channel;
  void poll(uint64_t now) {
    const std::size_t before = port.reads;
    transport.poll(port, now, 64, token, wake);
    require(port.reads - before <= 64, "bounded RX");
  }
  void drain(uint64_t now) { while (port.available()) poll(now); }
  void open(uint64_t now = 0) {
    port.add("\n@OMI ?\n"); drain(now);
    require(!port.output.empty(), "welcome missing");
    cJSON* root = cJSON_Parse(port.output.back().c_str() + 6);
    require(root != nullptr, "welcome parse");
    channel = cJSON_GetObjectItemCaseSensitive(root, "channel")->valuestring;
    cJSON_Delete(root);
  }
  std::string request(unsigned seq, const char* type, const char* body) {
    return "\n@OMI {\"v\":1,\"boot\":\"11111111111111111111111111111111\",\"channel\":\"" + channel +
           "\",\"session\":\"33333333333333333333333333333333\",\"seq\":" + std::to_string(seq) +
           ",\"type\":\"" + type + "\",\"body\":" + body + "}\n";
  }
  void hello() { open(); port.add(request(1, "hello", "{\"protocol\":1}")); drain(1); }
};
const char* snapshot = "{\"revision\":1,\"validForMs\":10,\"sourceLiveness\":\"unverified\",\"overallStatus\":\"working\",\"sessions\":[{\"id\":\"s1\",\"observed\":\"working\",\"display\":\"working\",\"host\":\"running\"}]}";

void handshakeAndIsolation() {
  Fixture f; f.hello();
  require(f.transport.view().lastSequence == 1, "hello committed");
  const unsigned before = wakes;
  f.port.add(f.request(2, "snapshot", snapshot)); f.drain(2);
  require(wakes == before, "frame w isolated");
  require(std::string(f.transport.view().displayStatus) == "working", "snapshot applied");
  f.port.add("w"); f.drain(3);
  require(wakes == before + 1, "external debug preserved");
  for (const auto& frame : f.port.output) require(frame.substr(0, 6) == "\n@OMI " && frame.back() == '\n', "atomic framed output");
  f.port.add("\n@OMI {}\n"); f.drain(4);
  require(f.transport.stats().lastSessionFailure == static_cast<uint32_t>(OmiPetProtocol::SessionResult::InvalidInput), "session rejection diagnostics");
  f.port.add("\n@OMX bad\n"); f.drain(5);
  require(f.transport.stats().lastFrameFailure == static_cast<uint32_t>(OmiPetProtocol::FeedResult::PrefixMismatch), "frame rejection diagnostics");
}
void backpressureAndNoQueue() {
  Fixture f; f.hello();
  const auto before = f.port.output.size(); f.port.space = 0;
  f.port.add(f.request(2, "heartbeat", "{}")); f.drain(2);
  f.port.add(f.request(3, "snapshot", snapshot)); f.drain(3);
  require(f.transport.view().lastSequence == 2 && f.port.output.size() == before, "no hidden command queue");
  f.port.space = 8192; f.poll(4);
  require(f.port.output.size() == before + 1 && f.transport.stats().stalled > 0, "resume one complete reply");
}
void staleReplyDropped() {
  Fixture f; f.hello(); f.port.space = 0;
  const auto before = f.port.output.size();
  f.port.add(f.request(2, "snapshot", snapshot)); f.drain(10);
  f.port.space = 8192; f.poll(20);
  require(f.port.output.size() == before && f.transport.stats().staleReplies == 1, "expired queued display discarded");
  f.port.add(f.request(2, "snapshot", snapshot)); f.drain(21);
  require(f.port.output.back().find("\"duplicate\":true") != std::string::npos, "retry deduplicates");
  require(f.port.output.back().find("\"displayStatus\":\"unknown\"") != std::string::npos, "retry reflects expiry");
}
void disconnectAndPartialFrame() {
  Fixture f; f.hello(); f.port.add("@OMI {\"unfinished\":"); f.drain(2);
  const unsigned before = wakes;
  f.port.cable = false; f.poll(3); f.port.cable = true;
  f.port.add("working}\n"); f.drain(4);
  require(wakes == before && !f.transport.view().leaseActive, "disconnect drops residual frame");
  const std::string old = f.channel; f.open(5);
  require(old != f.channel, "reconnect rotates channel");
}
void failedWriteAndRecovery() {
  Fixture f; f.hello(); f.port.shortWrite = true;
  f.port.add(f.request(2, "heartbeat", "{}")); f.drain(2);
  require(!f.transport.view().leaseActive && f.transport.stats().writeFailures == 1, "short write fails closed");
  f.port.shortWrite = false; f.open(3);
  f.port.add(f.request(1, "hello", "{\"protocol\":1}")); f.drain(4);
  require(f.transport.view().leaseActive, "new probe recovers");
}
void expiredConnectionAndProbe() {
  Fixture f; f.hello(); f.poll(1001);
  require(!f.transport.view().leaseActive, "lease advances without traffic");
  f.port.add(f.request(2, "heartbeat", "{}")); f.drain(1002);
  require(f.port.output.back().find("connection-expired") != std::string::npos, "late traffic cannot resurrect");
  f.open(1003);
  f.port.add(f.request(1, "hello", "{\"protocol\":1}")); f.drain(1004);
  require(f.transport.view().leaseActive, "new channel after expiry");
}
void closedConnectionOffersHandshake() {
  Fixture f; f.hello();
  const std::string old = f.channel;
  const std::string stale = f.request(2, "snapshot", snapshot);
  f.port.cable = false; f.poll(2); f.poll(3); f.port.cable = true;
  f.port.add(stale); f.drain(4);
  require(f.transport.stats().linkLosses == 1 && f.transport.stats().reopens == 1, "one link loss and handshake recovery");
  require(f.transport.stats().linkDownPolls == 2 && f.transport.stats().lastLinkDownMs == 2 &&
          f.transport.stats().maxLinkDownMs == 2, "link signal duration measured without changing recovery");
  require(f.port.output.back().find("\"type\":\"welcome\"") != std::string::npos, "closed connection offers welcome");
  require(!f.transport.view().leaseActive && f.transport.view().lastRevision == 0, "old snapshot must not execute");
  cJSON* root = cJSON_Parse(f.port.output.back().c_str() + 6);
  require(root != nullptr, "reopened welcome parse");
  f.channel = cJSON_GetObjectItemCaseSensitive(root, "channel")->valuestring;
  cJSON_Delete(root);
  require(old != f.channel, "reopened channel must change");
  f.port.add(f.request(1, "hello", "{\"protocol\":1}")); f.drain(5);
  require(f.transport.view().leaseActive && f.transport.view().lastSequence == 1, "fresh handshake required");
}
}  //  测试内部命名空间 / Internal test namespace

int main() {
  try {
    handshakeAndIsolation(); std::cout << "PASS transport_handshake_isolation\n";
    backpressureAndNoQueue(); std::cout << "PASS transport_backpressure\n";
    staleReplyDropped(); std::cout << "PASS transport_stale_reply\n";
    disconnectAndPartialFrame(); std::cout << "PASS transport_disconnect_partial_frame\n";
    failedWriteAndRecovery(); std::cout << "PASS transport_short_write_recovery\n";
    expiredConnectionAndProbe(); std::cout << "PASS transport_expiry_reconnect\n";
    closedConnectionOffersHandshake(); std::cout << "PASS transport_closed_connection_handshake\n";
  } catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; return EXIT_FAILURE; }
}
