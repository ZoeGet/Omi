#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <stdexcept>

namespace Original {
#include "sof_original.h"
}
namespace Fixed {
#include "sof_fixed.h"
}

void require(bool value, const char* reason) { if (!value) throw std::runtime_error(reason); }

int main() {
  try {
    Original::reset(); Fixed::reset();
    for (int i = 0; i < 100; ++i) {
      Original::tick(true); Fixed::tick(true);
      require(Original::s_usb_serial_jtag_conn_status && Fixed::s_usb_serial_jtag_conn_status, "continuous SOF remains connected");
    }
    std::cout << "PASS sof_continuous\n";
    bool originalFalse = false;
    for (int i = 0; i < 30; ++i) {
      Original::tick(false); Fixed::tick(false);
      originalFalse |= !Original::s_usb_serial_jtag_conn_status;
      require(Fixed::s_usb_serial_jtag_conn_status, "isolated misses must not accumulate");
      Original::tick(true); Fixed::tick(true);
    }
    require(originalFalse, "actual original SDK must reproduce intermittent-miss defect");
    std::cout << "PASS sof_original_intermittent_defect_reproduced\n";
    std::cout << "PASS sof_fixed_intermittent_misses\n";
    Original::reset(); Fixed::reset();
    for (unsigned i = 0; i < Fixed::ALLOWED_NO_SOF_TICKS; ++i) {
      Original::tick(false); Fixed::tick(false);
      require(Original::s_usb_serial_jtag_conn_status && Fixed::s_usb_serial_jtag_conn_status, "original disconnect grace preserved");
    }
    Original::tick(false); Fixed::tick(false);
    require(!Original::s_usb_serial_jtag_conn_status && !Fixed::s_usb_serial_jtag_conn_status, "sustained absence still disconnects");
    std::cout << "PASS sof_sustained_absence_threshold_unchanged\n";
    Original::tick(true); Fixed::tick(true);
    require(Fixed::s_usb_serial_jtag_conn_status && Fixed::remaining_allowed_no_sof_ticks == Fixed::ALLOWED_NO_SOF_TICKS, "SOF recovers full budget");
    std::cout << "PASS sof_recovery\n";
  } catch (const std::exception& error) { std::cerr << "FAIL " << error.what() << '\n'; return EXIT_FAILURE; }
}
