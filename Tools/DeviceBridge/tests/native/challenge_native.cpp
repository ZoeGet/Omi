#include "device_protocol_session.h"
#include "cJSON.h"
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

using OmiPetProtocol::ProtocolSession;
using OmiPetProtocol::SessionResult;

namespace {
const char* kBoot = "11111111111111111111111111111111";
const char* kChannel = "22222222222222222222222222222222";
const char* kSession = "33333333333333333333333333333333";

void require(bool value, const char* reason) { if (!value) throw std::runtime_error(reason); }
std::string request(unsigned sequence, const char* kind, const std::string& body) {
  return std::string("{\"v\":1,\"boot\":\"") + kBoot + "\",\"channel\":\"" + kChannel +
         "\",\"session\":\"" + kSession + "\",\"seq\":" + std::to_string(sequence) +
         ",\"type\":\"" + kind + "\",\"body\":" + body + "}";
}
std::string snapshot(unsigned revision, int challenge, unsigned validity) {
  return std::string("{\"revision\":") + std::to_string(revision) +
         ",\"validForMs\":" + std::to_string(validity) +
         ",\"sourceLiveness\":\"unverified\",\"overallStatus\":\"working\",\"sessions\":[{"
         "\"id\":\"s1\",\"observed\":\"working\",\"display\":\"working\",\"host\":\"running\"}]" +
         (challenge > 0 ? ",\"challengeSeq\":" + std::to_string(challenge) : "") + "}";
}
std::string send(ProtocolSession& session, const std::string& raw, uint64_t now) {
  char output[4097];
  require(session.receive(raw.data(), raw.size(), now, output, sizeof(output)) == SessionResult::Reply, "reply");
  return output;
}
bool ok(const std::string& raw) {
  cJSON* root = cJSON_Parse(raw.c_str());
  require(root != nullptr, "parse reply");
  const cJSON* body = cJSON_GetObjectItemCaseSensitive(root, "body");
  const bool accepted = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(body, "ok"));
  cJSON_Delete(root);
  return accepted;
}
}

int main() {
  try {
    ProtocolSession session(kBoot, {4096, 16, 8, 5000});
    char welcome[4097];
    require(session.open(kChannel, 0, welcome, sizeof(welcome)) == SessionResult::Reply, "welcome");
    require(std::strstr(welcome, "\"freshnessChallenge\":true") != nullptr, "capability");
    require(ok(send(session, request(1, "hello", "{\"protocol\":1}"), 0)), "hello");
    require(!ok(send(session, request(2, "snapshot", snapshot(1, 0, 1000)), 10)), "missing challenge");
    require(ok(send(session, request(3, "heartbeat", "{}"), 20)), "heartbeat");
    const std::string accepted = request(4, "snapshot", snapshot(1, 3, 1000));
    require(ok(send(session, accepted, 420)), "challenged snapshot");
    require(std::strcmp(session.view().displayStatus, "working") == 0, "working");
    require(ok(send(session, request(5, "heartbeat", "{}"), 500)), "renew lease");
    require(session.advance(1019) && std::strcmp(session.view().displayStatus, "working") == 0, "before deadline");
    require(session.advance(1020) && std::strcmp(session.view().displayStatus, "unknown") == 0, "device deadline");
    require(!ok(send(session, request(6, "snapshot", snapshot(2, 3, 1000)), 1030)), "old challenge rejected");
    require(ok(send(session, request(7, "heartbeat", "{}"), 1040)), "new heartbeat");
    require(ok(send(session, request(8, "snapshot", snapshot(2, 7, 100)), 1200)), "expired accepted unknown");
    require(std::strcmp(session.view().displayStatus, "unknown") == 0, "expired unknown");
    require(!ok(send(session, request(9, "heartbeat", "{\"unexpected\":true}"), 1210)), "invalid heartbeat");
    require(!ok(send(session, request(10, "snapshot", snapshot(3, 9, 1000)), 1220)), "rejected heartbeat cannot challenge");
    std::cout << "PASS freshness_challenge_device_clock\n";
  } catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; return EXIT_FAILURE; }
}
