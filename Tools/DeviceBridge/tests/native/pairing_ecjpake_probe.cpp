#include "pairing_auth_gate.h"
#include "pairing_auth_proof.h"
#include "pairing_credential_record.h"
#include "pairing_key_derivation.h"
#include "pairing_window.h"

#include <mbedtls/ctr_drbg.h>
#include <mbedtls/ecjpake.h>
#include <mbedtls/entropy.h>
#include <mbedtls/md.h>

#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

void check(int result) {
  if (result != 0) throw std::runtime_error("Mbed TLS EC J-PAKE operation failed");
}

struct RandomSource {
  mbedtls_entropy_context entropy;
  mbedtls_ctr_drbg_context drbg;

  RandomSource() {
    mbedtls_entropy_init(&entropy);
    mbedtls_ctr_drbg_init(&drbg);
    const unsigned char label[] = "omipet-pairing-native-probe";
    check(mbedtls_ctr_drbg_seed(&drbg, mbedtls_entropy_func, &entropy,
                                label, sizeof(label) - 1));
  }

  ~RandomSource() {
    mbedtls_ctr_drbg_free(&drbg);
    mbedtls_entropy_free(&entropy);
  }
};

struct Peer {
  mbedtls_ecjpake_context context;

  Peer(mbedtls_ecjpake_role role, const char* code) {
    mbedtls_ecjpake_init(&context);
    check(mbedtls_ecjpake_setup(&context, role, MBEDTLS_MD_SHA256,
                                MBEDTLS_ECP_DP_SECP256R1,
                                reinterpret_cast<const unsigned char*>(code), std::strlen(code)));
  }

  ~Peer() { mbedtls_ecjpake_free(&context); }
};

std::vector<unsigned char> roundOne(Peer& peer, RandomSource& random) {
  std::vector<unsigned char> message(1024);
  size_t length = 0;
  check(mbedtls_ecjpake_write_round_one(&peer.context, message.data(), message.size(),
                                        &length, mbedtls_ctr_drbg_random, &random.drbg));
  message.resize(length);
  return message;
}

std::vector<unsigned char> roundTwo(Peer& peer, RandomSource& random) {
  std::vector<unsigned char> message(1024);
  size_t length = 0;
  check(mbedtls_ecjpake_write_round_two(&peer.context, message.data(), message.size(),
                                        &length, mbedtls_ctr_drbg_random, &random.drbg));
  message.resize(length);
  return message;
}

void appendMessage(std::vector<unsigned char>& transcript, const std::vector<unsigned char>& message) {
  transcript.push_back(static_cast<unsigned char>(message.size() >> 8));
  transcript.push_back(static_cast<unsigned char>(message.size()));
  transcript.insert(transcript.end(), message.begin(), message.end());
}

std::array<unsigned char, 32> proof(const unsigned char* secret, size_t length,
                                    const char* role, const std::vector<unsigned char>& transcript,
                                    const std::array<unsigned char, 32>& certPin) {
  std::vector<unsigned char> material;
  const char prefix[] = "OmiPet pairing primitive probe v1";
  material.insert(material.end(), prefix, prefix + sizeof(prefix));
  material.insert(material.end(), role, role + std::strlen(role) + 1);
  material.insert(material.end(), transcript.begin(), transcript.end());
  material.insert(material.end(), certPin.begin(), certPin.end());
  std::array<unsigned char, 32> output{};
  check(mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), secret, length,
                        material.data(), material.size(), output.data()));
  return output;
}

bool exchange(const char* clientCode, const char* serverCode, RandomSource& random,
              bool pinMismatch = false) {
  Peer client(MBEDTLS_ECJPAKE_CLIENT, clientCode);
  Peer server(MBEDTLS_ECJPAKE_SERVER, serverCode);
  const auto clientOne = roundOne(client, random);
  const auto serverOne = roundOne(server, random);
  check(mbedtls_ecjpake_read_round_one(&client.context, serverOne.data(), serverOne.size()));
  check(mbedtls_ecjpake_read_round_one(&server.context, clientOne.data(), clientOne.size()));
  const auto clientTwo = roundTwo(client, random);
  const auto serverTwo = roundTwo(server, random);
  check(mbedtls_ecjpake_read_round_two(&client.context, serverTwo.data(), serverTwo.size()));
  check(mbedtls_ecjpake_read_round_two(&server.context, clientTwo.data(), clientTwo.size()));
  std::array<unsigned char, 64> clientSecret{};
  std::array<unsigned char, 64> serverSecret{};
  size_t clientLength = 0;
  size_t serverLength = 0;
  check(mbedtls_ecjpake_derive_secret(&client.context, clientSecret.data(), clientSecret.size(),
                                      &clientLength, mbedtls_ctr_drbg_random, &random.drbg));
  check(mbedtls_ecjpake_derive_secret(&server.context, serverSecret.data(), serverSecret.size(),
                                      &serverLength, mbedtls_ctr_drbg_random, &random.drbg));
  std::vector<unsigned char> transcript;
  appendMessage(transcript, clientOne);
  appendMessage(transcript, serverOne);
  appendMessage(transcript, clientTwo);
  appendMessage(transcript, serverTwo);
  std::array<unsigned char, 32> clientPin{};
  for (size_t index = 0; index < clientPin.size(); ++index) {
    clientPin[index] = static_cast<unsigned char>(index + 64);
  }
  auto serverPin = clientPin;
  if (pinMismatch) serverPin[0] ^= 1;
  const auto clientProof = proof(clientSecret.data(), clientLength, "client", transcript, clientPin);
  const auto serverExpectedClient = proof(serverSecret.data(), serverLength, "client", transcript, serverPin);
  const auto serverProof = proof(serverSecret.data(), serverLength, "server", transcript, serverPin);
  const auto clientExpectedServer = proof(clientSecret.data(), clientLength, "server", transcript, clientPin);
  return clientProof == serverExpectedClient && serverProof == clientExpectedServer;
}

std::string hexProof(const std::array<unsigned char, 32>& proof) {
  constexpr char digits[] = "0123456789abcdef";
  std::string output;
  for (unsigned char value : proof) {
    output.push_back(digits[value >> 4]);
    output.push_back(digits[value & 0x0f]);
  }
  return output;
}

int main() {
  check(mbedtls_ecjpake_self_test(0));
  std::cout << "PASS installed_mbedtls_ecjpake_self_test\n";

  RandomSource random;
  if (!exchange("000001", "000001", random)) return 1;
  std::cout << "PASS matching_six_digit_code_confirms_both_peers\n";

  if (exchange("000001", "000002", random)) return 1;
  std::cout << "PASS different_code_fails_key_confirmation\n";

  if (exchange("000001", "000001", random, true)) return 1;
  std::cout << "PASS different_certificate_pin_fails_key_confirmation\n";

  Peer client(MBEDTLS_ECJPAKE_CLIENT, "123456");
  Peer server(MBEDTLS_ECJPAKE_SERVER, "123456");
  auto malformed = roundOne(client, random);
  malformed[0] = 0;
  if (mbedtls_ecjpake_read_round_one(&server.context, malformed.data(), malformed.size()) == 0) {
    return 1;
  }
  std::cout << "PASS malformed_round_rejected\n";

  OmiPetPairing::PairingWindow window;
  if (!window.open(0, 300000, 5)) return 1;
  for (uint64_t attempt = 1; attempt <= 4; ++attempt) {
    if (!window.beginAttempt(attempt)) return 1;
    if (window.finishAttempt(exchange("000002", "000001", random), attempt + 1)) return 1;
  }
  if (!window.beginAttempt(10) || !window.finishAttempt(exchange("000001", "000001", random), 11) ||
      window.state() != OmiPetPairing::WindowState::Paired) return 1;
  std::cout << "PASS confirmed_window_accepts_fifth_correct_proof\n";

  std::array<uint8_t, 32> key{};
  std::array<uint8_t, 32> deviceNonce{};
  std::array<uint8_t, 32> hostNonce{};
  std::array<uint8_t, 32> certPin{};
  for (size_t index = 0; index < 32; ++index) {
    key[index] = static_cast<uint8_t>(index + 1);
    deviceNonce[index] = static_cast<uint8_t>(index);
    hostNonce[index] = static_cast<uint8_t>(index + 32);
    certPin[index] = static_cast<uint8_t>(index + 64);
  }
  std::array<uint8_t, 32> hostProof{};
  std::array<uint8_t, 32> deviceProof{};
  if (!OmiPetPairing::makePairingAuthProof(key.data(), key.size(),
            OmiPetPairing::ProofRole::Host, deviceNonce.data(),
            hostNonce.data(), certPin.data(), hostProof.data()) ||
      !OmiPetPairing::makePairingAuthProof(key.data(), key.size(),
            OmiPetPairing::ProofRole::Device, deviceNonce.data(),
            hostNonce.data(), certPin.data(), deviceProof.data())) return 1;
  if (hexProof(hostProof) != "2e65af28bf6f85216c1a986e773b8e161faf7a62f9a3dbc36fba93557dd9bfda" ||
      hexProof(deviceProof) != "d6193a9c2ef3f109febe9a8c627eab1d91f98295163424b9f87fb9ed715d5b26") return 1;
  if (!OmiPetPairing::verifyPairingAuthProof(key.data(), key.size(),
            OmiPetPairing::ProofRole::Host, deviceNonce.data(),
            hostNonce.data(), certPin.data(), hostProof.data(), hostProof.size())) return 1;
  if (OmiPetPairing::verifyPairingAuthProof(key.data(), key.size(),
            OmiPetPairing::ProofRole::Device, deviceNonce.data(),
            hostNonce.data(), certPin.data(), hostProof.data(), hostProof.size())) return 1;
  certPin[0] ^= 1;
  if (OmiPetPairing::verifyPairingAuthProof(key.data(), key.size(),
            OmiPetPairing::ProofRole::Host, deviceNonce.data(),
            hostNonce.data(), certPin.data(), hostProof.data(), hostProof.size())) return 1;
  certPin[0] ^= 1;
  if (OmiPetPairing::verifyPairingAuthProof(key.data(), key.size(),
            OmiPetPairing::ProofRole::Host, deviceNonce.data(),
            hostNonce.data(), certPin.data(), hostProof.data(), 31)) return 1;
  std::cout << "PASS daily_auth_cross_language_vector_and_spoof_rejection\n";

  OmiPetPairing::PairingAuthGate gate;
  if (gate.authorized() || gate.begin(false, key.data(), certPin.data(), deviceNonce.data()) ||
      !gate.begin(true, key.data(), certPin.data(), deviceNonce.data()) ||
      gate.authorized()) return 1;
  std::array<uint8_t, 32> reply{};
  if (!gate.finish(hostNonce.data(), hostProof.data(), hostProof.size(), reply.data()) ||
      !gate.authorized() || reply != deviceProof) return 1;
  gate.reset();
  if (gate.authorized() || gate.finish(hostNonce.data(), hostProof.data(),
                                       hostProof.size(), reply.data())) return 1;
  if (!gate.begin(true, key.data(), certPin.data(), deviceNonce.data()) ||
      gate.finish(hostNonce.data(), deviceProof.data(), deviceProof.size(), reply.data()) ||
      gate.authorized()) return 1;
  std::cout << "PASS tls_connection_gate_rejects_unverified_and_reset_connections\n";

  const std::array<uint8_t, 32> transcriptDigest = {
      0x18, 0xad, 0x66, 0x77, 0xf2, 0x1e, 0xf3, 0x69,
      0x5b, 0x9a, 0x74, 0x7e, 0x38, 0x39, 0x07, 0xde,
      0x47, 0xde, 0xe5, 0x43, 0x3f, 0x1a, 0x7b, 0x21,
      0x6b, 0xc2, 0x54, 0x3f, 0xa9, 0x06, 0x18, 0x17};
  std::array<uint8_t, 32> derivedKey{};
  if (!OmiPetPairing::derivePairingDailyKey(key.data(), key.size(),
          transcriptDigest.data(), certPin.data(), derivedKey.data()) ||
      hexProof(derivedKey) != "8b38f903d92d1cedea71ce9a8b1d540c415ce2d4aef295f8b075e66c109a630c") return 1;
  std::cout << "PASS hkdf_daily_key_matches_python_vector\n";

  std::array<uint8_t, OmiPetPairing::kCredentialRecordBytes> record{};
  std::array<uint8_t, 32> restoredKey{};
  std::array<uint8_t, 32> restoredPin{};
  if (!OmiPetPairing::encodeCredentialRecord(key.data(), certPin.data(),
                                             record.data()) ||
      !OmiPetPairing::decodeCredentialRecord(record.data(), record.size(),
                                             restoredKey.data(), restoredPin.data()) ||
      restoredKey != key || restoredPin != certPin) return 1;
  std::array<uint8_t, 32> recordDigest{};
  check(mbedtls_sha256_ret(record.data(), record.size(), recordDigest.data(), 0));
  if (hexProof(recordDigest) != "5aab7b11f8278032b31fa5545e1750469b7a7968fda7c30e476850283dcdf47e") return 1;
  record[OmiPetPairing::kCredentialHeaderBytes] ^= 1;
  if (OmiPetPairing::decodeCredentialRecord(record.data(), record.size(),
                                            restoredKey.data(), restoredPin.data()) ||
      restoredKey != std::array<uint8_t, 32>{} ||
      restoredPin != std::array<uint8_t, 32>{}) return 1;
  std::cout << "PASS credential_record_matches_python_and_fails_closed_on_corruption\n";
}
