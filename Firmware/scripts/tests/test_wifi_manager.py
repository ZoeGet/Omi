"""Run the actual Wi-Fi state machine with fake radio/NVS using WSL g++."""
import subprocess
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
STUB = r"""
#pragma once
#include <string>
#include <cstring>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <cassert>
using String = struct S : std::string {
 using std::string::string;
 S(std::string s):std::string(s){}
 S()=default;
 bool isEmpty() const {return empty();}
 void toCharArray(char* p, size_t n) const {std::snprintf(p,n,"%s",c_str());}
 S toString() const {return *this;}
};
static uint32_t tick=100;
uint32_t millis(){return tick;}
struct Log {template<class... T> void printf(const char*,T...){} void println(const char*){}} Serial;
constexpr int WIFI_STA=1, WL_CONNECTED=3;
struct Radio {
 int state=0; String name,pass,legacy="legacy",legacyPass="old";
 std::vector<String> attempts;
 void mode(int){} void setAutoReconnect(bool){} void persistent(bool){}
 void disconnect(){state=0;}
 void begin(const char* s,const char* p){name=s;pass=p;attempts.push_back(name);}
 int status() const{return state;}
 String SSID(){return name;} String psk(){return pass;}
 String softAPIP(){return "192.168.4.1";}
} WiFi;
static std::vector<char> blob;
static bool failWrite=false;
struct Preferences {
 bool begin(const char*,bool){return true;}
 size_t getBytesLength(const char*){return blob.size();}
 size_t getBytes(const char*,void* p,size_t n){memcpy(p,blob.data(),n);return n;}
 size_t putBytes(const char*,const void* p,size_t n){if(failWrite)return 0;blob.assign((const char*)p,(const char*)p+n);return n;}
};
struct WiFiManager {
 bool active=false; uint32_t opened=0;
 void setConfigPortalBlocking(bool){} void setWiFiAutoReconnect(bool){}
 void setConfigPortalTimeout(uint32_t){} void setConnectTimeout(uint32_t){}
 String getWiFiSSID(bool){return WiFi.legacy;} String getWiFiPass(bool){return WiFi.legacyPass;}
 void startConfigPortal(const char*,const char*){active=true;opened=tick;}
 bool getConfigPortalActive(){return active;}
 void stopConfigPortal(){assert(active);active=false;}
 void process(){if(tick-opened>=180000)active=false;}
};
"""
MAIN = r"""
#include "wifi_manager.cpp"
using OmiPetNetwork::WifiManagerService;
void success(WifiManagerService& m,const char* s,const char* p="pw"){
 WiFi.name=s;WiFi.pass=p;WiFi.state=3;m.update();
 WiFi.state=0;m.update();
}
int main(){
 WifiManagerService m;m.begin();assert(WiFi.attempts.back()=="legacy");
 for(const auto* s:{"A","B","C","D","E"})success(m,s);
 WifiManagerService reboot;reboot.begin();
 for(const auto* s:{"E","D","C","B","A"}){
  assert(WiFi.attempts.back()==s);tick+=20000;reboot.update();reboot.update();
 }
 assert(reboot.provisioning());assert(WiFi.attempts.back()=="E");
 //  门户中仍能重连，成功退出门户 / Reconnect and close the active portal on success
 success(reboot,"A","changed");
 assert(!reboot.provisioning());
 WifiManagerService again;again.begin();assert(WiFi.name=="A" && WiFi.pass=="changed");
 success(again,"F");
 WifiManagerService full;full.begin();
 for(const auto* s:{"F","A","E","D","C"}){
  assert(WiFi.name==s);tick+=20000;full.update();full.update();
 }
 assert(WiFi.name=="F");
 //  门户超时后仍会轮换，不停留在最后一个网络 / Rotation continues after portal timeout
 tick+=180001;full.update();tick+=20000;full.update();full.update();assert(WiFi.name=="E");
 //  未成功连接的新密码不写入历史 / Failed new credentials never enter history
 WiFi.name="bad";WiFi.pass="wrong";WiFi.state=0;full.update();
 WifiManagerService failed;failed.begin();assert(WiFi.name=="F");
 //  空凭据首次启动仍有配网入口 / Empty first boot still opens provisioning
 blob.clear();WiFi.legacy="";WiFi.state=0;
 WifiManagerService empty;empty.begin();tick+=5000;empty.update();assert(empty.provisioning());
 puts("wifi history/reboot/rotation/password/eviction/portal/failure/first-boot passed");
}
"""

class WifiTests(unittest.TestCase):
 def test_actual_firmware(self):
  def linux(path):
   value=str(path.resolve()).replace("\\","/")
   return "/mnt/"+value[0].lower()+value[2:]
  with tempfile.TemporaryDirectory(dir=ROOT/"tmp",prefix="wifi-test-") as directory:
   folder=Path(directory)
   (folder/"fake.h").write_text(STUB,encoding="utf-8")
   for name in ("Arduino.h","WiFi.h","WiFiManager.h","Preferences.h"):
    (folder/name).write_text('#include "fake.h"\n',encoding="utf-8")
   (folder/"main.cpp").write_text(MAIN,encoding="utf-8")
   prefix=["wsl","-d","Ubuntu-22.04","--exec"]
   subprocess.run(prefix+["g++","-std=c++11","-Wall","-Wextra","-Werror",
    "-I"+linux(folder),"-I"+linux(ROOT/"Firmware/include"),
    "-I"+linux(ROOT/"Firmware/src"),linux(folder/"main.cpp"),"-o",linux(folder/"test")],check=True)
   subprocess.run(prefix+[linux(folder/"test")],check=True)

if __name__ == "__main__":
 unittest.main()
