#include <cassert>
#include <cmath>
#include <iostream>
#include <fstream>
#include "../src/main.cpp"

void reset(uint8_t id=0x68) {
  Wire=FakeWire();Wire.regs[0x75]=id;Serial.output.clear();
  address=0x68;identity=0;rangeIndex=0;sampleHz=50;busHz=100000;
  ready=false;axisReads=false;streaming=true;epoch=sequence=errors=0;clearWindow();
}
int main() {
  for (int value=-32768;value<=32767;++value) {
    uint16_t bits=uint16_t(value);
    assert(signedWord(bits>>8,bits&255)==value);
  }
  std::cout<<"PASS all 65536 signed word patterns, including -32768 and +32767\n";
  for(uint8_t id:{uint8_t(0x68),uint8_t(0x70),uint8_t(0x69)}) {
    reset(id);setup();assert(ready);assert(Serial.baud==230400);
    assert(Wire.regs[0x1C]==0);assert(Wire.regs[0x19]==19);
    assert(Wire.regs[0x1D]==(id==0x70?3:0));
  }
  std::cout<<"PASS identity-dependent initialization and configuration readback\n";
  reset();Wire.present=false;assert(!initialize());
  Wire.present=true;fakeTime+=3001;loop();assert(ready);
  reset(0x42);assert(!initialize());
  reset();Wire.deviceAddress=0x69;assert(initialize());assert(address==0x69);
  std::cout<<"PASS missing device recovery, alternate address, unknown identity rejected\n";
  for(uint8_t idx=0;idx<4;++idx) {
    reset();rangeIndex=idx;assert(initialize());
    Wire.axis(0,0);Wire.axis(1,0);Wire.axis(2,int16_t(16384>>idx));Wire.regs[0x3A]=1;
    takeSample();assert(samples==1);assert(fabs(normSum-1.0)<1e-6);assert(stale==0);
    Wire.axis(0,int16_t(-32768));takeSample();assert(rails[0]==1);
  }
  std::cout<<"PASS 1 g conversion in all four ranges, stale flag and clipping evidence\n";
  reset();assert(initialize());Wire.shortReg=0x3B;
  takeSample();assert(!ready&&sequence==0&&errors==1);
  reset();assert(initialize());Wire.regs[0x1C]=8;
  takeSample();assert(!ready&&sequence==0);
  reset();Wire.blockedWrite=0x1C;rangeIndex=1;assert(!initialize());
  std::cout<<"PASS truncated read and range drift never emit converted samples; failed writes detected\n";
  reset();assert(initialize());Wire.axis(0,-12000);Wire.axis(1,100);Wire.axis(2,10000);
  takeSample();double expected=normSum;clearWindow();axisReads=true;takeSample();assert(normSum==expected);
  std::cout<<"PASS independent-axis and burst decoding agree for static registers\n";
  command("range 16");assert(rangeIndex==3&&ready&&Wire.regs[0x1C]==24);
  command("rate 25");assert(sampleHz==25&&Wire.regs[0x19]==39);
  command("clock 100");assert(Wire.clock==100000);
  command("range 3");assert(rangeIndex==3);
  Serial.input=std::string(40,'x')+"\nread burst\nstream off\n";readCommands();
  assert(!axisReads&&!streaming);assert(Serial.output.find("command_too_long")!=std::string::npos);
  ready=false;command("probe");assert(Serial.output.find("raw_probe")!=std::string::npos);
  std::cout<<"PASS runtime commands, invalid commands, oversized input and resynchronization\n";
  std::ofstream("tests/simulated_serial.jsonl")<<Serial.output;
}
