#pragma once

#ifndef OMIPET_WIFI_PAIRING
#define OMIPET_WIFI_PAIRING 0
#endif

namespace OmiPetPairing {
//  主循环仅做非阻塞维护，网络和密码运算留在服务线程 / The main loop only performs nonblocking maintenance; network and crypto stay on service threads
void updateWirelessPairing(bool connected);
}
