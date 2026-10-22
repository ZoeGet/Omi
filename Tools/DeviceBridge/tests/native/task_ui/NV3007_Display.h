#pragma once
#include <cstdint>
#include <algorithm>
#include <stdexcept>
namespace OmiPetDisplay {
constexpr uint16_t kPanelWidth = 142, kPanelHeight = 428;
class Display {
 public:
  uint16_t pixels[428 * 142] = {};
  unsigned writes = 0;
  unsigned rectangles = 0;
  unsigned bitmaps = 0;
  unsigned titleRows = 0;
  unsigned maxFill = 0;
  unsigned maxBitmap = 0;
  static constexpr uint16_t color565(uint8_t r, uint8_t g, uint8_t b) {
    return ((r & 248) << 8) | ((g & 252) << 3) | (b >> 3);
  }
  void fillRect(int x,int y,int w,int h,uint16_t color) {
    if(x<0 || y<0 || x+w>428 || y+h>142) throw std::runtime_error("UI bounds");
    ++writes;
    maxFill = std::max(maxFill, static_cast<unsigned>(w*h));
    for(int row=y;row<y+h;++row) for(int col=x;col<x+w;++col) pixels[row*428+col]=color;
  }
  void fillScreen(uint16_t color) { fillRect(0,0,428,142,color); }
  void drawBitmap(int x,int y,int w,int h,const uint16_t* data) {
    if (w <= 0 || h <= 0 || w * h > 206 * 50) throw std::runtime_error("UI region budget");
    maxBitmap = std::max(maxBitmap, static_cast<unsigned>(w * h));
    ++bitmaps;
    if (w == 160 && h == 1) ++titleRows;
    for(int row=0;row<h;++row) for(int col=0;col<w;++col) fillRect(x+col,y+row,1,1,data[row*w+col]);
  }
  void drawRoundRect(int x,int y,int w,int h,int radius,uint16_t color,uint16_t =0) {
    ++rectangles;
    fillRect(x+radius,y,w-2*radius,1,color);
    fillRect(x+radius,y+h-1,w-2*radius,1,color);
    fillRect(x,y+radius,1,h-2*radius,color);
    fillRect(x+w-1,y+radius,1,h-2*radius,color);
    for(int yy=0;yy<radius;++yy) for(int xx=0;xx<radius;++xx) {
      const int d=(radius-xx)*(radius-xx)+(radius-yy)*(radius-yy);
      if(d>=(radius-1)*(radius-1) && d<=radius*radius) {
        fillRect(x+xx,y+yy,1,1,color); fillRect(x+w-1-xx,y+yy,1,1,color);
        fillRect(x+xx,y+h-1-yy,1,1,color); fillRect(x+w-1-xx,y+h-1-yy,1,1,color);
      }
    }
  }
};
extern Display lcd;
}
