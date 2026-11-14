#pragma once
#include <array>
#include <vector>
#include <cstdint>
#include <algorithm>
struct FakeWire {
  std::array<uint8_t,256> regs{};
  std::vector<uint8_t> tx,rx;
  bool present=true;
  uint8_t deviceAddress=0x68, currentAddress=0, pointer=0;
  int shortReg=-1, blockedWrite=-1;
  unsigned clock=0;
  bool begin(int,int,unsigned hz) {clock=hz;return true;}
  void setClock(unsigned hz) {clock=hz;}
  void setTimeOut(unsigned) {}
  void beginTransmission(uint8_t addr) {currentAddress=addr;tx.clear();}
  size_t write(uint8_t b) {tx.push_back(b);return 1;}
  uint8_t endTransmission(bool=true) {
    if(!present||currentAddress!=deviceAddress)return 2;
    pointer=tx.at(0);
    if(tx.size()==2 && int(pointer)!=blockedWrite) {
      if(pointer==0x6B && tx[1]==0x80) {
        uint8_t id=regs[0x75];auto data=regs;
        regs.fill(0);regs[0x75]=id;regs[0x6B]=0x40;
        std::copy(data.begin()+0x3B,data.begin()+0x49,regs.begin()+0x3B);
      } else regs[pointer]=tx[1];
    }
    return 0;
  }
  size_t requestFrom(uint8_t addr,uint8_t count) {
    rx.clear();if(!present||addr!=deviceAddress)return 0;
    uint8_t actual=count-(int(pointer)==shortReg?1:0);
    for(uint8_t i=0;i<actual;++i)rx.push_back(regs[uint8_t(pointer+i)]);
    if(pointer==0x3A)regs[0x3A]=0;
    return actual;
  }
  int available(){return rx.size();}
  int read(){if(rx.empty())return -1;int c=rx.front();rx.erase(rx.begin());return c;}
  void axis(int i,int16_t value){regs[0x3B+2*i]=uint16_t(value)>>8;regs[0x3C+2*i]=uint16_t(value)&255;}
};
inline FakeWire Wire;
