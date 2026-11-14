#pragma once
#include <cstdint>
#include <cstddef>
#include <cstdarg>
#include <cstdio>
#include <string>
inline uint32_t fakeTime=0;
inline uint32_t millis() {return fakeTime;}
inline void delay(uint32_t ms) {fakeTime+=ms;}
struct FakeSerial {
  std::string output, input;
  unsigned baud=0;
  void begin(unsigned b) {baud=b;}
  void printf(const char* fmt, ...) __attribute__((format(printf,2,3))) {
    char buffer[2048]; va_list args; va_start(args,fmt);
    int n=vsnprintf(buffer,sizeof(buffer),fmt,args);va_end(args);
    if (n<0 || n>=int(sizeof(buffer))) throw "serial formatting overflow";
    output+=buffer;
  }
  void println(const char* s) {output+=s;output+='\n';}
  int available() {return input.size();}
  int read() {if(input.empty())return -1;int c=input[0];input.erase(0,1);return c;}
};
inline FakeSerial Serial;
