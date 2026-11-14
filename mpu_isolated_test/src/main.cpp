#include <Arduino.h>
#include <Wire.h>
#include <esp_system.h>
#include <math.h>
#include <string.h>
#include <stdint.h>
#include <initializer_list>

constexpr int SDA_PIN = 21, SCL_PIN = 22;
uint8_t address = 0x68, identity = 0, rangeIndex = 0;
uint32_t busHz = 100000, sampleHz = 50;
bool ready = false, axisReads = false, streaming = true;
uint32_t epoch = 0, sequence = 0, errors = 0, samples = 0, stale = 0;
uint32_t lastAttempt = 0, lastSample = 0, lastReport = 0;
int16_t lo[3] = {32767,32767,32767}, hi[3] = {-32768,-32768,-32768};
uint32_t rails[3] = {0,0,0};
double normSum = 0;

// Explicit conversion avoids unspecified evaluation order of two Wire.read()
// calls in one expression and preserves the signed two's-complement endpoints.
int16_t signedWord(uint8_t high, uint8_t low) {
  const uint16_t bits = (uint16_t(high) << 8) | low;
  return int16_t(bits >= 0x8000 ? int32_t(bits) - 65536 : bits);
}
float sensitivity(uint8_t index) { return float(16384U >> index); }
void clearWindow() {
  samples = stale = 0; normSum = 0;
  for (int i=0;i<3;++i) { lo[i]=32767; hi[i]=-32768; rails[i]=0; }
}
void i2cError(uint8_t reg, const char* stage, unsigned detail) {
  ++errors;
  Serial.printf("{\"type\":\"i2c_error\",\"ms\":%lu,\"address\":%u,\"reg\":%u,\"stage\":\"%s\",\"detail\":%u}\n",
                (unsigned long)millis(),address,reg,stage,detail);
}
bool readBytes(uint8_t reg, uint8_t* data, uint8_t n) {
  Wire.beginTransmission(address); Wire.write(reg);
  uint8_t result = Wire.endTransmission(false);
  if (result) { i2cError(reg,"address",result); return false; }
  size_t got = Wire.requestFrom(address,n);
  if (got != n || Wire.available() != n) {
    while (Wire.available()) Wire.read();
    i2cError(reg,"short_read",unsigned(got)); return false;
  }
  for (uint8_t i=0;i<n;++i) data[i]=uint8_t(Wire.read());
  return true;
}
bool writeReg(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(address); Wire.write(reg); Wire.write(value);
  uint8_t result=Wire.endTransmission();
  if (result) i2cError(reg,"write",result);
  return result == 0;
}
bool verify(uint8_t reg, uint8_t expected, uint8_t mask=0xFF) {
  uint8_t actual;
  if (!readBytes(reg,&actual,1)) return false;
  if ((actual & mask) == (expected & mask)) return true;
  Serial.printf("{\"type\":\"config_mismatch\",\"ms\":%lu,\"reg\":%u,\"actual\":%u,\"expected\":%u,\"mask\":%u}\n",
                (unsigned long)millis(),reg,actual,expected,mask);
  return false;
}
bool verifyConfig() {
  return verify(0x75,identity) && verify(0x6B,1) && verify(0x6C,0,0x3F) &&
    verify(0x19,uint8_t(1000/sampleHz-1)) && verify(0x1A,3,0x3F) &&
    verify(0x1B,0,0xFB) && verify(0x1C,uint8_t(rangeIndex<<3),0xF8) &&
    (identity!=0x70 || verify(0x1D,3,0x0F)) &&
    verify(0x23,0) && verify(0x6A,0,0xE0) && verify(0x37,0,0xF0) && verify(0x38,1);
}
void dumpRegisters() {
  const uint8_t regs[]={0x75,0x6B,0x6C,0x19,0x1A,0x1B,0x1C,0x23,0x6A,0x37,0x38};
  for (uint8_t reg:regs) {
    uint8_t value;
    if (readBytes(reg,&value,1)) Serial.printf("{\"type\":\"register\",\"ms\":%lu,\"reg\":%u,\"value\":%u}\n",(unsigned long)millis(),reg,value);
  }
  if (identity==0x70) {
    uint8_t value;
    if (readBytes(0x1D,&value,1)) Serial.printf("{\"type\":\"register\",\"reg\":29,\"value\":%u}\n",value);
  }
}
bool initialize() {
  ready=false; lastAttempt=millis();
  bool found=false;
  for (uint8_t candidate: {uint8_t(0x68),uint8_t(0x69)}) {
    address=candidate;
    uint8_t id;
    if (!readBytes(0x75,&id,1)) continue;
    Serial.printf("{\"type\":\"identity\",\"address\":%u,\"who_am_i\":%u,\"supported\":%s}\n",address,id,(id==0x68||id==0x70||id==0x69)?"true":"false");
    if (id==0x68||id==0x70||id==0x69) { identity=id; found=true; break; }
  }
  if (!found) return false;
  dumpRegisters(); // Preserve state before reset; do not silently assume range.
  if (!writeReg(0x6B,0x80)) return false;
  delay(100);
  if (!writeReg(0x6B,1) || !writeReg(0x6C,0) || !writeReg(0x6A,0) ||
      !writeReg(0x23,0) || !writeReg(0x1A,3) || !writeReg(0x1B,0) ||
      !writeReg(0x1C,uint8_t(rangeIndex<<3)) ||
      (identity==0x70 && !writeReg(0x1D,3)) ||
      !writeReg(0x19,uint8_t(1000/sampleHz-1)) ||
      !writeReg(0x37,0) || !writeReg(0x38,1)) return false;
  delay(100);
  if (!verifyConfig()) return false;
  ++epoch; clearWindow(); lastSample=lastReport=millis(); ready=true;
  Serial.printf("{\"type\":\"config\",\"valid\":true,\"epoch\":%lu,\"who_am_i\":%u,\"range_g\":%u,\"lsb_per_g\":%.0f,\"rate_hz\":%lu,\"i2c_hz\":%lu}\n",
    (unsigned long)epoch,identity,2U<<rangeIndex,double(sensitivity(rangeIndex)),(unsigned long)sampleHz,(unsigned long)busHz);
  return true;
}
void takeSample() {
  uint8_t range, status, bytes[14]={0};
  if (!readBytes(0x1C,&range,1) || !readBytes(0x3A,&status,1)) { ready=false; return; }
  if ((range & 0xF8) != uint8_t(rangeIndex<<3)) {
    Serial.println("{\"type\":\"range_changed\"}"); ready=false; return;
  }
  if (axisReads) {
    // Diagnostic comparison only: separate transactions are not simultaneous.
    for (uint8_t i=0;i<3;++i) if (!readBytes(0x3B+2*i,bytes+2*i,2)) {ready=false;return;}
  } else if (!readBytes(0x3B,bytes,14)) {ready=false;return;}
  int16_t raw[3]; float g[3];
  for (int i=0;i<3;++i) {
    raw[i]=signedWord(bytes[2*i],bytes[2*i+1]); g[i]=raw[i]/sensitivity(rangeIndex);
    if (raw[i]<lo[i]) lo[i]=raw[i];
    if (raw[i]>hi[i]) hi[i]=raw[i];
    if (raw[i]==-32768 || raw[i]==32767) ++rails[i];
  }
  float norm=sqrtf(g[0]*g[0]+g[1]*g[1]+g[2]*g[2]);
  ++sequence; ++samples; normSum+=norm; if (!(status&1)) ++stale;
  if (streaming) Serial.printf("{\"type\":\"sample\",\"seq\":%lu,\"ms\":%lu,\"epoch\":%lu,\"range_g\":%u,\"axis_reads\":%s,\"fresh\":%s,\"raw\":[%d,%d,%d],\"g\":[%.5f,%.5f,%.5f],\"norm\":%.5f}\n",
    (unsigned long)sequence,(unsigned long)millis(),(unsigned long)epoch,2U<<rangeIndex,axisReads?"true":"false",status&1?"true":"false",raw[0],raw[1],raw[2],double(g[0]),double(g[1]),double(g[2]),double(norm));
}
void reportStatus() {
  if (ready && !verifyConfig()) ready=false;
  Serial.printf("{\"type\":\"status\",\"ms\":%lu,\"ready\":%s,\"epoch\":%lu,\"range_g\":%u,\"samples\":%lu,\"stale\":%lu,\"errors\":%lu,\"window_ms\":%lu",
    (unsigned long)millis(),ready?"true":"false",(unsigned long)epoch,2U<<rangeIndex,(unsigned long)samples,(unsigned long)stale,(unsigned long)errors,(unsigned long)(millis()-lastReport));
  if (samples) Serial.printf(",\"raw_min\":[%d,%d,%d],\"raw_max\":[%d,%d,%d],\"rails\":[%lu,%lu,%lu],\"norm_mean\":%.5f",lo[0],lo[1],lo[2],hi[0],hi[1],hi[2],(unsigned long)rails[0],(unsigned long)rails[1],(unsigned long)rails[2],normSum/samples);
  Serial.println("}"); clearWindow(); lastReport=millis();
}
void probeRaw() {
  // Available even if configuration verification failed. No g conversion and
  // no assertion of sample freshness or valid operating mode in this output.
  uint8_t bytes[14], config;
  if (!readBytes(0x1C,&config,1) || !readBytes(0x3B,bytes,14)) return;
  Serial.printf("{\"type\":\"raw_probe\",\"ms\":%lu,\"accel_config\":%u,\"bytes\":[",(unsigned long)millis(),config);
  for (int i=0;i<14;++i) Serial.printf("%s%u",i?",":"",bytes[i]);
  Serial.printf("],\"raw\":[%d,%d,%d]}\n",signedWord(bytes[0],bytes[1]),signedWord(bytes[2],bytes[3]),signedWord(bytes[4],bytes[5]));
}
void command(const char* text) {
  // Exact whitelist: no unrestricted register writes or flash modifications.
  bool accepted=true, reconfigure=false;
  if (!strcmp(text,"dump")) dumpRegisters();
  else if (!strcmp(text,"probe")) probeRaw();
  else if (!strcmp(text,"reinit")) reconfigure=true;
  else if (!strcmp(text,"range 2")) {rangeIndex=0;reconfigure=true;}
  else if (!strcmp(text,"range 4")) {rangeIndex=1;reconfigure=true;}
  else if (!strcmp(text,"range 8")) {rangeIndex=2;reconfigure=true;}
  else if (!strcmp(text,"range 16")) {rangeIndex=3;reconfigure=true;}
  else if (!strcmp(text,"rate 10")) {sampleHz=10;reconfigure=true;}
  else if (!strcmp(text,"rate 25")) {sampleHz=25;reconfigure=true;}
  else if (!strcmp(text,"rate 50")) {sampleHz=50;reconfigure=true;}
  else if (!strcmp(text,"clock 100")) {busHz=100000;Wire.setClock(busHz);reconfigure=true;}
  else if (!strcmp(text,"clock 400")) {busHz=400000;Wire.setClock(busHz);reconfigure=true;}
  else if (!strcmp(text,"read axis")) {axisReads=true;clearWindow();++epoch;lastReport=millis();}
  else if (!strcmp(text,"read burst")) {axisReads=false;clearWindow();++epoch;lastReport=millis();}
  else if (!strcmp(text,"stream off")) streaming=false;
  else if (!strcmp(text,"stream on")) streaming=true;
  else accepted=false;
  Serial.printf("{\"type\":\"command_result\",\"accepted\":%s}\n",accepted?"true":"false");
  if (reconfigure) initialize();
}
void readCommands() {
  static char buffer[32]; static uint8_t length=0; static bool discard=false;
  while (Serial.available()) {
    char c=char(Serial.read());
    if (c=='\r') continue;
    if (c=='\n') {
      if (!discard) {buffer[length]=0;command(buffer);}
      else Serial.println("{\"type\":\"command_too_long\"}");
      length=0;discard=false;
    } else if (!discard && length<sizeof(buffer)-1) buffer[length++]=c;
    else discard=true;
  }
}
void setup() {
  Serial.begin(230400); delay(500);
  Serial.printf("{\"type\":\"boot\",\"test\":\"mpu-isolated-v1\",\"reset_reason\":%d,\"sda\":21,\"scl\":22}\n",int(esp_reset_reason()));
  Wire.begin(SDA_PIN,SCL_PIN,busHz); Wire.setTimeOut(50);
  initialize(); lastReport=millis();
}
void loop() {
  readCommands();
  if (!ready && millis()-lastAttempt>=3000) initialize();
  if (ready && millis()-lastSample>=1000/sampleHz) {lastSample=millis();takeSample();}
  if (millis()-lastReport>=1000) reportStatus();
  delay(1);
}
