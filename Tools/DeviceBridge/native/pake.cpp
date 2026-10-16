#include "pairing_exchange.h"
#include <mbedtls/entropy.h>
#include <mbedtls/ctr_drbg.h>
#include <new>

#ifdef _WIN32
#define EXPORT extern "C" __declspec(dllexport)
#else
#define EXPORT extern "C" __attribute__((visibility("default")))
#endif

struct Peer {
  mbedtls_entropy_context entropy;
  mbedtls_ctr_drbg_context random;
  OmiPetPairing::PairingExchange exchange;
  Peer() { mbedtls_entropy_init(&entropy); mbedtls_ctr_drbg_init(&random); }
  ~Peer() { mbedtls_ctr_drbg_free(&random); mbedtls_entropy_free(&entropy); }
};

EXPORT void* omi_pake_create(int server, const char* code) {
  auto* peer = new (std::nothrow) Peer;
  if (!peer) return nullptr;
  const unsigned char label[] = "OmiPet pairing host v1";
  if (mbedtls_ctr_drbg_seed(&peer->random, mbedtls_entropy_func, &peer->entropy,
      label, sizeof(label) - 1) != 0 || !peer->exchange.begin(server != 0, code,
      mbedtls_ctr_drbg_random, &peer->random)) {
    delete peer;
    return nullptr;
  }
  return peer;
}

EXPORT int omi_pake_write(Peer* peer, unsigned char* output, size_t* length) {
  return peer && peer->exchange.write(output, 1024, length);
}
EXPORT int omi_pake_read(Peer* peer, const unsigned char* input, size_t length) {
  return peer && peer->exchange.read(input, length);
}
EXPORT int omi_pake_derive(Peer* peer, unsigned char* output) {
  return peer && peer->exchange.derive(output);
}
EXPORT void omi_pake_free(Peer* peer) { delete peer; }
EXPORT int omi_pairing_confirmation(const unsigned char* key, char role, const unsigned char* digest,
                                     const unsigned char* pin, unsigned char* output) {
  return OmiPetPairing::pairingConfirmation(key, role, digest, pin, output);
}
