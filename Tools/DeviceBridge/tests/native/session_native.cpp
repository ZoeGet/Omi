#include "device_protocol_session.h"
#include "cJSON.h"
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

using OmiPetProtocol::ProtocolSession;
using OmiPetProtocol::SessionLimits;
using OmiPetProtocol::SessionResult;

namespace {
const char* kBoot = "11111111111111111111111111111111";
const char* kChannel = "22222222222222222222222222222222";
const char* kHello = "{\"v\":1,\"boot\":\"11111111111111111111111111111111\",\"channel\":\"22222222222222222222222222222222\",\"session\":\"33333333333333333333333333333333\",\"seq\":1,\"type\":\"hello\",\"body\":{\"protocol\":1}}";
const SessionLimits kLimits = {4096, 16, 8, 1000};

void require(bool value, const char* reason) { if (!value) throw std::runtime_error(reason); }
const cJSON* field(const cJSON* node, const char* name) { return cJSON_GetObjectItemCaseSensitive(node, name); }
const char* text(const cJSON* node, const char* name) { return field(node, name)->valuestring; }

void outputAtomicity() {
  ProtocolSession session(kBoot, kLimits);
  char output[4097];
  require(session.open(kChannel, 0, output, 2) == SessionResult::OutputTooSmall, "small welcome");
  require(session.receive(kHello, std::strlen(kHello), 0, output, sizeof(output)) == SessionResult::NotOpen, "open must not commit");
  require(session.open(kChannel, 0, output, sizeof(output)) == SessionResult::Reply, "welcome retry");
  require(session.receive(kHello, std::strlen(kHello), 1, output, 2) == SessionResult::OutputTooSmall, "small ack");
  require(session.view().lastSequence == 0 && !session.view().leaseActive, "hello must not commit");
  require(session.receive(kHello, std::strlen(kHello), 1, output, sizeof(output)) == SessionResult::Reply, "hello retry");
  require(session.view().lastSequence == 1 && session.view().leaseActive, "hello commits");
  require(session.receive(kHello, std::strlen(kHello), 0, output, sizeof(output)) == SessionResult::InvalidClock, "backward clock");
  require(output[0] == 0 && session.view().lastSequence == 1, "clock failure atomic");
  session.disconnect();
  require(std::strcmp(session.view().mode, "local") == 0 && !session.view().leaseActive, "disconnect releases");
  require(session.open(kChannel, 2, output, sizeof(output)) == SessionResult::InvalidInput, "new channel required");
}

std::size_t gAllocation = 0;
std::size_t gFailureAt = 0;
void* failAllocation(std::size_t size) { return gAllocation++ == gFailureAt ? nullptr : std::malloc(size); }

void allocationFailures() {
  //  逐个注入分配失败，检查无部分握手且可用同序号恢复 / Inject each allocation failure and verify atomic handshake and same-sequence recovery
  bool finished = false;
  for (std::size_t at = 0; at < 512; ++at) {
    ProtocolSession session(kBoot, kLimits);
    char output[4097];
    require(session.open(kChannel, 0, output, sizeof(output)) == SessionResult::Reply, "allocation setup");
    gAllocation = 0;
    gFailureAt = at;
    cJSON_Hooks hooks = {failAllocation, std::free};
    cJSON_InitHooks(&hooks);
    const SessionResult result = session.receive(kHello, std::strlen(kHello), 1, output, sizeof(output));
    cJSON_InitHooks(nullptr);
    if (result == SessionResult::Reply) {
      require(session.view().lastSequence == 1, "success commits");
      if (gAllocation <= at) { finished = true; break; }
    } else {
      require(session.view().lastSequence == 0 && !session.view().leaseActive && output[0] == 0, "allocation failure commits nothing");
      require(session.receive(kHello, std::strlen(kHello), 1, output, sizeof(output)) == SessionResult::Reply, "allocation recovery");
    }
  }
  require(finished, "all allocation points checked");
}

void welcomeAndSnapshotAllocationFailures() {
  const std::string snap = std::string(kHello).substr(0, std::string(kHello).find("\"seq\"")) +
      "\"seq\":2,\"type\":\"snapshot\",\"body\":{\"revision\":1,\"validForMs\":100,\"sourceLiveness\":\"unverified\","
      "\"overallStatus\":\"working\",\"sessions\":[{\"id\":\"s1\",\"observed\":\"working\",\"display\":\"working\",\"host\":\"running\"}]}}";
  for (int phase = 0; phase < 2; ++phase) {
    bool finished = false;
    for (std::size_t at = 0; at < 512; ++at) {
      ProtocolSession session(kBoot, kLimits);
      char output[4097];
      if (phase) {
        require(session.open(kChannel, 0, output, sizeof(output)) == SessionResult::Reply, "snapshot allocation open");
        require(session.receive(kHello, std::strlen(kHello), 0, output, sizeof(output)) == SessionResult::Reply, "snapshot allocation hello");
      }
      gAllocation = 0;
      gFailureAt = at;
      cJSON_Hooks hooks = {failAllocation, std::free};
      cJSON_InitHooks(&hooks);
      const SessionResult result = phase ? session.receive(snap.data(), snap.size(), 1, output, sizeof(output)) :
                                           session.open(kChannel, 0, output, sizeof(output));
      cJSON_InitHooks(nullptr);
      if (result == SessionResult::Reply) {
        if (gAllocation <= at) { finished = true; break; }
      } else {
        require(output[0] == 0 && session.view().lastSequence == static_cast<uint32_t>(phase), "allocation sequence unchanged");
        require(session.view().lastRevision == 0 && std::strcmp(session.view().mode, "local") == 0, "allocation snapshot unchanged");
        const SessionResult retry = phase ? session.receive(snap.data(), snap.size(), 1, output, sizeof(output)) :
                                           session.open(kChannel, 0, output, sizeof(output));
        require(retry == SessionResult::Reply, "welcome or snapshot allocation recovery");
      }
    }
    require(finished, "welcome or snapshot allocations exhausted");
  }
}

void clockAndInputBoundaries() {
  ProtocolSession session(kBoot, kLimits);
  char output[4097];
  const uint64_t start = UINT64_MAX - 1000;
  require(session.open(kChannel, start, output, sizeof(output)) == SessionResult::Reply, "large clock open");
  require(session.receive(kHello, std::strlen(kHello), start, output, sizeof(output)) == SessionResult::Reply, "large clock hello");
  require(session.advance(UINT64_MAX - 1) && session.view().leaseActive, "lease just before boundary");
  require(session.advance(UINT64_MAX) && !session.view().leaseActive, "lease expires without addition overflow");
  require(!session.advance(0), "clock wrap requires adapter extension");
  ProtocolSession invalid(kBoot, {4096, 16, 8, 0});
  require(invalid.open(kChannel, 0, output, sizeof(output)) == SessionResult::InvalidInput, "explicit positive lease");
  ProtocolSession input(kBoot, kLimits);
  require(input.open(kChannel, 0, output, sizeof(output)) == SessionResult::Reply, "input setup");
  for (const std::string& data : {std::string("{}"), std::string(4097, 'w'), std::string(kHello) + "w"}) {
    require(input.receive(data.data(), data.size(), 0, output, sizeof(output)) == SessionResult::InvalidInput, "invalid input rejected");
    require(input.view().lastSequence == 0 && output[0] == 0, "invalid input atomic");
  }
  require(input.receive(kHello, std::strlen(kHello), 0, output, sizeof(output)) == SessionResult::Reply, "expiry input setup");
  require(input.receive(nullptr, 0, 1000, output, sizeof(output)) == SessionResult::InvalidInput, "invalid input at expiry");
  require(!input.view().leaseActive, "invalid input cannot prevent expiry");
}

void vectors(const char* path) {
  std::ifstream source(path);
  require(source.good(), "fixture open");
  std::string line;
  std::size_t count = 0;
  while (std::getline(source, line)) {
    cJSON* fixture = cJSON_Parse(line.c_str());
    require(fixture != nullptr, "fixture parse");
    ProtocolSession session(kBoot, kLimits);
    const cJSON* steps = field(fixture, "steps");
    std::size_t stepIndex = 0;
    for (const cJSON* step = steps->child; step; step = step->next, ++stepIndex) {
      const uint64_t now = static_cast<uint64_t>(field(step, "now")->valuedouble);
      const char* op = text(step, "op");
      char output[4097];
      SessionResult result = SessionResult::Reply;
      if (std::strcmp(op, "open") == 0) result = session.open(text(step, "channel"), now, output, sizeof(output));
      else if (std::strcmp(op, "receive") == 0) {
        const char* raw = text(step, "raw");
        result = session.receive(raw, std::strlen(raw), now, output, sizeof(output));
      } else if (std::strcmp(op, "advance") == 0) require(session.advance(now), "advance fixture");
      else if (std::strcmp(op, "disconnect") == 0) session.disconnect();
      else require(false, "unknown fixture operation");
      const cJSON* expected = field(step, "reply");
      if (expected) {
        cJSON* actual = result == SessionResult::Reply ? cJSON_Parse(output) : nullptr;
        const bool same = actual && cJSON_Compare(actual, expected, true);
        if (!same) std::cerr << "Vector " << text(fixture, "name") << " step " << stepIndex << " actual=" << output << '\n';
        cJSON_Delete(actual);
        require(same, "Python/C++ reply mismatch");
      }
      const auto view = session.view();
      const cJSON* state = field(step, "state");
      require(std::strcmp(view.mode, text(state, "mode")) == 0, "mode mismatch");
      require(std::strcmp(view.displayStatus, text(state, "displayStatus")) == 0, "display mismatch");
      require(view.leaseActive == static_cast<bool>(cJSON_IsTrue(field(state, "leaseActive"))), "lease mismatch");
    }
    std::cout << "PASS session_vector_" << text(fixture, "name") << '\n';
    cJSON_Delete(fixture);
    ++count;
  }
  require(count > 0, "nonempty vectors");
}
}  //  测试内部命名空间 / Internal test namespace

int main(int argc, char** argv) {
  try {
    outputAtomicity(); std::cout << "PASS session_output_atomicity\n";
    allocationFailures(); std::cout << "PASS session_allocation_failures\n";
    welcomeAndSnapshotAllocationFailures(); std::cout << "PASS session_welcome_snapshot_allocation_failures\n";
    clockAndInputBoundaries(); std::cout << "PASS session_clock_input_boundaries\n";
    require(argc == 2, "fixture required");
    vectors(argv[1]);
  } catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; return EXIT_FAILURE; }
}
