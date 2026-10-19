#include "omi_pet_ui.h"
#include "NV3007_Display.h"
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <cstring>
namespace OmiPetDisplay { Display lcd; }
void require(bool value,const char* message) { if(!value) throw std::runtime_error(message); }
void tick() { for(int i=0;i<24;++i) OmiPetUi::update(); }
int main(int argc,char** argv) {
  try {
    OmiPetUi::begin();
    OmiPetProtocol::TaskScreen screen;
    screen.available=true; screen.active=6;
    std::ifstream titles(argc>1?argv[1]:"", std::ios::binary);
    for(unsigned i=0;i<4;++i) {
      screen.cards[i].used=true; screen.cards[i].waiting=i==0;
      titles.read(reinterpret_cast<char*>(screen.cards[i].pixels),320);
    }
    if (titles.read(reinterpret_cast<char*>(screen.labels),256)) screen.hasLabels=true;
    auto& lcd=OmiPetDisplay::lcd;
    lcd.rectangles=0; lcd.maxFill=0; lcd.bitmaps=0;
    OmiPetUi::setTaskScreen(true,true,&screen); tick();
    require(lcd.bitmaps==6,"four buffered cards plus header and footer");
    lcd.maxFill=0;
    unsigned transfers=lcd.bitmaps;
    screen.cards[0].waiting = !screen.cards[0].waiting;
    OmiPetUi::setTaskScreen(true,true,&screen); tick();
    require(lcd.bitmaps == transfers + 1,"status changes one region");
    transfers=lcd.bitmaps;
    screen.cards[1].pixels[0] ^= 128;
    OmiPetUi::setTaskScreen(true,true,&screen); tick();
    require(lcd.bitmaps == transfers + 1,"title changes one region");
    transfers=lcd.bitmaps;
    screen.cards[2].used=false;
    OmiPetUi::setTaskScreen(true,true,&screen); tick();
    require(lcd.bitmaps == transfers + 1,"remove only one card");
    require(lcd.pixels[80*428+230]==0,"removed card erased");
    screen.cards[2].used=true;
    OmiPetUi::setTaskScreen(true,true,&screen); tick();
    require(lcd.maxFill<=1,"normal updates never clear display regions first");
    transfers=lcd.bitmaps;
    screen.cards[3].waiting=true;
    OmiPetUi::setTaskScreen(true,true,&screen);
    screen.cards[3].waiting=false;
    OmiPetUi::setTaskScreen(true,true,&screen);tick();
    require(lcd.bitmaps==transfers,"coalesced changes compare rendered state");
    const unsigned writes=lcd.writes;
    OmiPetUi::setEnvironment(23,60,true);
    OmiPetUi::setNetworkStatus(true,false,"synthetic");
    OmiPetUi::setDateTime(true,2026,10,19,12,30);
    OmiPetUi::setVoiceStatus("IDLE");
    OmiPetUi::setTaskScreen(true,true,&screen);tick();
    require(lcd.writes==writes,"no dashboard leak or unchanged redraw");
    if(argc>2) {
      std::ofstream out(argv[2],std::ios::binary);
      out.write(reinterpret_cast<char*>(lcd.pixels),sizeof(lcd.pixels));
    }
    OmiPetUi::setTaskScreen(true,false,nullptr);tick();
    uint16_t local[428*142];
    std::memcpy(local,lcd.pixels,sizeof(local));
    const unsigned disconnected=lcd.writes;
    OmiPetUi::setTaskScreen(false,false,nullptr);tick();
    require(lcd.writes==disconnected,"disconnect already restored local page");
    OmiPetUi::setTaskScreen(true,true,&screen);tick();
    OmiPetUi::setTaskScreen(true,false,nullptr);tick();
    require(std::memcmp(local,lcd.pixels,sizeof(local))==0,"disconnect restores dashboard pixels");
    OmiPetUi::setTaskScreen(true,true,&screen);tick();
    OmiPetUi::setPairingCode("123456",120,"192.0.2.1");
    const unsigned paired=lcd.writes;
    OmiPetUi::setTaskScreen(true,false,nullptr);tick();
    require(lcd.writes==paired,"pairing dominates task redraw");
    OmiPetUi::setPairingCode(nullptr,0);tick();
    require(lcd.writes>paired,"disconnect page after pairing");
    OmiPetUi::setTaskScreen(false,false,nullptr);tick();
    require(lcd.maxFill==428*142,"local dashboard restored");
    std::cout<<"PASS task_ui_four_cards_bounds_stability_pairing_disconnect_local\n";
  } catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
}
