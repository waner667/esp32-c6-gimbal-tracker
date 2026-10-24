// gimbal_firmware.ino
// ESP32-C6 两轴云台 — 舵机 + 遥控输入固件
//
// 开发环境：
//   Arduino IDE → 开发板管理装 "esp32" (≥3.0) → 工具→开发板 选 "ESP32C6 Dev Module"
//   库管理装 "ESP32Servo" (≥0.13)
// 烧录后打开串口监视器 115200，应看到 READY；
// 发 "P90,T45\n" 控角度，发 "H\n" 回中。
//
// 接线：C6 GPIO10 → pan 舵机信号(橙/黄)；GPIO11 → tilt 舵机信号(橙/黄)
//       舵机红线→5V(12V降压模块调到5V的输出)、棕/黑→GND(必须与 C6 的 GND 共地)
//       ⚠ 降压模块先用万用表测准 5.0V 再接舵机，12V 直冲会烧毁 SG90
//       遥控接收机信号(单线) → C6 GPIO6（UART1 RX，只收不发）
// 引脚说明：原 GPIO2/3 改为 GPIO10/11，收缩到面包板可用列（4/5/8/9/15 是 strapping、12/13 是原生 USB DM/DP、1 是 32K 晶振，均避开）。
//       GPIO10/11 为普通 GPIO，相邻并排插，防看串。GPIO6/7 留作遥控串口（RX/TX）。
//
// 遥控支持三种协议（自动识别，也可用 RC= 命令手动锁定）：
//   i-BUS  FlySky FS-A8S 等      115200 8N1 不反相  帧头 0x20 0x40
//   CRSF   ELRS 接收机           420000 8N1 不反相  帧 0xC8 len 0x16 + CRC8(poly 0xD5)
//   SBUS   FrSky / A8S 也可输出  100000 8E2 【反相】——C6 的 UART 有硬件反相寄存器，
//          打开 invert 即可直接收，不需要外接三极管反相器
//   通道值统一归一为 1000~2000（中位 1500），ch1→pan，ch2→tilt。
//
// 控制模式（最后输入优先，不用记开关）：
//   摇杆偏离中位 → 遥控模式（速度控制：偏得越多转越快，中位附近有死区防抖）
//   串口收到 P,T/H 命令 → USB 模式（tracker.py 自动追踪接管）
//   两种输入会自动互相接管，串口命令 RC= 可查看/锁定协议，RCV 打印 16 通道原始值。


#include <ESP32Servo.h>

Servo panServo, tiltServo;
const int PAN_PIN  = 10, TILT_PIN = 11;  // 收缩到面包板同一列；避开 strapping 脚 4/5/8/9/15 与 USB 脚 12/13
const int PAN_MIN  = 10, PAN_MAX  = 170;
// ⚠️⚠️ 本文件是【ESP32Servo 版】，在 ESP32-C6 上 attach 成功但 PWM 无波形，舵机不会转——已废弃，勿烧录！
// ⚠️⚠️ 量程也是旧的：TILT 20/110 按自研 gimbal.scad 定。现用 MakerWorld #2045352，正确值见 gimbal_firmware_ledc/ 的 10/170。
const int TILT_MIN = 20, TILT_MAX = 110;

float panCur = 90, tiltCur = 90;
int panTgt = 90, tiltTgt = 90;   // 必须 int：printf %d 打 float 在 RISC-V 上读到的是寄存器残留乱值
const float STEP = 1.5;                 // 每步度数（平滑插值）

// ---------------- 遥控输入（i-BUS / CRSF / SBUS 三协议） ----------------
const int RC_RX_PIN = 6;                 // UART1 RX：面包板剩余安全脚（10/11 被舵机占，4/5/8/9/15 strapping、12/13 USB、1 晶振均避开）
const int RC_TX_PIN = 7;                 // UART1 TX：预留（遥测回传，当前不用）

enum { RC_NONE = 0, RC_IBUS, RC_CRSF, RC_SBUS };
const char *RC_NAME[4] = { "none", "i-BUS", "CRSF", "SBUS" };
int rcProto = RC_NONE;                   // 当前锁定的协议
uint16_t rcCh[16];                       // 归一化后的通道值 1000~2000
unsigned long rcLastFrame = 0;           // 最近一个有效帧的时间
unsigned long rcNextScan = 0;            // 下次协议扫描时间
int rcScanIdx = RC_IBUS;                 // 扫描进度
bool rcLocked = false;                   // RC= 命令手动锁定后停止自动切换
bool rcManual = false;                   // true=遥控接管 false=USB命令接管
float panRate = 0, tiltRate = 0;         // 摇杆速度（度/循环），死区外才非零

const int   RC_DEAD = 25;                // 摇杆死区（±25us ≈ ±1.4°），防抖
const float RC_RATE_PAN  = 2.2;          // 摇杆打满时 pan 每循环转角（度）
const float RC_RATE_TILT = 2.0;          // 摇杆打满时 tilt 每循环转角（度）

// 各协议收帧状态机
uint8_t rcBuf[64];
int rcLen = 0;

void rcBegin(int proto) {
  switch (proto) {
    case RC_IBUS: Serial1.begin(115200, SERIAL_8N1, RC_RX_PIN, RC_TX_PIN, false); break;
    case RC_CRSF: Serial1.begin(420000, SERIAL_8N1, RC_RX_PIN, RC_TX_PIN, false); break;
    case RC_SBUS: Serial1.begin(100000, SERIAL_8E2, RC_RX_PIN, RC_TX_PIN, true);  break; // true=硬件反相，免外部电路
  }
  rcLen = 0;
}

// CRC8 poly 0xD5（CRSF 用）
uint8_t crc8(const uint8_t *d, int n) {
  uint8_t c = 0;
  while (n--) {
    c ^= *d++;
    for (int i = 0; i < 8; i++) c = (c & 0x80) ? (c << 1) ^ 0xD5 : (c << 1);
  }
  return c;
}

// 从 11bit 打包（LSB-first）取第 idx 通道
uint16_t bits11(const uint8_t *b, int idx) {
  int bit = idx * 11, byte = bit / 8, off = bit % 8;
  uint32_t v = b[byte] | (b[byte + 1] << 8) | (b[byte + 2] << 16);
  return (v >> off) & 0x7FF;
}

// 喂一个字节给当前协议状态机；解出完整合法帧返回 true
bool rcFeed(uint8_t b) {
  if (rcProto == RC_CRSF) {
    if (rcLen == 0 && b != 0xC8) return false;           // 等帧头
    if (rcLen == 1 && b > 62)    { rcLen = 0; return false; }
    if (rcLen < 64) rcBuf[rcLen++] = b;
    if (rcLen >= 2 && rcLen == rcBuf[1] + 2) {           // 收满一帧
      bool ok = false;
      if (rcBuf[2] == 0x16 && rcBuf[1] == 0x18) {        // RC 通道帧
        if (crc8(&rcBuf[2], rcBuf[1]) == rcBuf[rcLen - 1]) {
          for (int i = 0; i < 16; i++) {
            uint16_t v = bits11(&rcBuf[3], i);           // 172~1811
            rcCh[i] = 1000 + (int)((v - 172) * 1000.0 / (1811 - 172) + 0.5);
          }
          ok = true;
        }
      }
      rcLen = 0;
      return ok;
    }
    return false;
  }
  if (rcProto == RC_SBUS) {
    if (rcLen == 0 && b != 0x0F) return false;           // 等帧头
    if (rcLen < 25) rcBuf[rcLen++] = b;
    if (rcLen == 25) {
      bool ok = (rcBuf[24] == 0x00);                     // 帧尾
      if (ok && !(rcBuf[23] & 0x0C)) {                   // bit2=丢帧 bit3=failsafe，置位则不用
        for (int i = 0; i < 16; i++) {
          uint16_t v = bits11(&rcBuf[1], i);             // 172~1811
          rcCh[i] = 1000 + (int)((v - 172) * 1000.0 / (1811 - 172) + 0.5);
        }
      } else ok = false;
      rcLen = 0;
      return ok;
    }
    return false;
  }
  // i-BUS：0x20 0x40 起，14 通道 × 2 字节小端，末 2 字节校验
  if (rcLen == 0 && b != 0x20) return false;
  if (rcLen == 1 && b != 0x40) { rcLen = 0; return false; }
  if (rcLen < 32) rcBuf[rcLen++] = b;
  if (rcLen == 32) {
    uint16_t sum = 0x20 + 0x40;
    for (int i = 2; i < 30; i++) sum += rcBuf[i];
    uint16_t chk = rcBuf[30] | (rcBuf[31] << 8);
    bool ok = (chk == (uint16_t)(0xFFFF - sum));
    if (ok) {
      for (int i = 0; i < 14; i++) {
        uint16_t v = rcBuf[2 + i * 2] | (rcBuf[3 + i * 2] << 8);  // 1000~2000
        rcCh[i] = constrain(v, 1000, 2000);
      }
    }
    rcLen = 0;
    return ok;
  }
  return false;
}

void rcPoll() {
  // 当前协议正常收帧中
  if (rcProto != RC_NONE) {
    while (Serial1.available()) if (rcFeed(Serial1.read())) rcLastFrame = millis();
    if (millis() - rcLastFrame > 800 && !rcLocked) {     // 丢了：重新扫（换过接收机/协议时自愈）
      rcProto = RC_NONE;
      rcNextScan = 0;
    }
  }
  // 没有锁定的协议：每 220ms 换一个协议试
  if (rcProto == RC_NONE && !rcLocked && millis() >= rcNextScan) {
    rcBegin(rcScanIdx);
    unsigned long until = millis() + 200;
    bool got = false;
    while (millis() < until) {
      while (Serial1.available()) {
        if (rcFeed(Serial1.read())) {
          rcLastFrame = millis();
          got = true;
        }
      }
      if (got) break;
    }
    if (got) {
      rcProto = rcScanIdx;
      Serial.printf("RC LOCK %s (ch1=%d ch2=%d)\n", RC_NAME[rcProto], rcCh[0], rcCh[1]);
    } else {
      rcScanIdx = (rcScanIdx == RC_IBUS) ? RC_CRSF : (rcScanIdx == RC_CRSF ? RC_SBUS : RC_IBUS);
      rcNextScan = millis() + 220;
    }
  }
  // 摇杆 → 速度（死区外才动）
  if (rcProto != RC_NONE && millis() - rcLastFrame < 300) {
    int dx = rcCh[0] - 1500, dy = rcCh[1] - 1500;
    panRate  = (abs(dx) > RC_DEAD) ? dx / 500.0 * RC_RATE_PAN  : 0;   // dx/500：中位 0、满推 2.2
    tiltRate = (abs(dy) > RC_DEAD) ? dy / 500.0 * RC_RATE_TILT : 0;
    if (panRate != 0 || tiltRate != 0) {                  // 摇杆动了 → 抢回遥控模式
      if (!rcManual) { rcManual = true; Serial.println("MODE=RC"); }
      panTgt  = constrain(panTgt  + panRate,  PAN_MIN,  PAN_MAX);
      tiltTgt = constrain(tiltTgt + tiltRate, TILT_MIN, TILT_MAX);
    }
  } else {
    panRate = tiltRate = 0;
  }
}

void setup() {
  Serial.begin(115200);
  ESP32PWM::allocateTimer(0);          // 每舵机独立定时器，避免 LEDC 冲突
  ESP32PWM::allocateTimer(1);
  panServo.setPeriodHertz(50);         // 标准 50Hz 舵机信号
  tiltServo.setPeriodHertz(50);
  int pa = panServo.attach(PAN_PIN, 1000, 2000);   // 脉冲 1ms~2ms 对应 0°~180°
  int ta = tiltServo.attach(TILT_PIN, 1000, 2000);
  panServo.write((int)panCur);
  tiltServo.write((int)tiltCur);
  Serial.printf("READY pan=GPIO%d tilt=GPIO%d attach=%d,%d\n", PAN_PIN, TILT_PIN, pa, ta);
  Serial.println("RC: 自动识别 i-BUS/CRSF/SBUS，信号线接 GPIO6");
}

void loop() {
  rcPoll();
  readCommand();
  stepTowards();
  delay(15);
}

void readCommand() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line == "H") {
    panTgt = 90; tiltTgt = 90;
    if (rcManual) { rcManual = false; Serial.println("MODE=USB"); }
    Serial.println("OK center"); return;
  }
  if (line.startsWith("RC=")) {                          // RC=i|c|s 手动锁定协议
    char c = line.charAt(3);
    if (c == 'i') { rcLocked = true;  rcProto = RC_IBUS;  rcBegin(RC_IBUS); }
    if (c == 'c') { rcLocked = true;  rcProto = RC_CRSF;  rcBegin(RC_CRSF); }
    if (c == 's') { rcLocked = true;  rcProto = RC_SBUS;  rcBegin(RC_SBUS); }
    Serial.printf("RC=%s\n", RC_NAME[rcProto]);
    return;
  }
  if (line == "RC") {
    Serial.printf("RC=%s manual=%d\n", RC_NAME[rcProto], rcManual);
    return;
  }
  if (line == "RCV") {                                   // 打印 16 通道原始值（对通道用）
    Serial.print("RCV");
    for (int i = 0; i < 16; i++) Serial.printf(" %d", rcCh[i]);
    Serial.println();
    return;
  }
  int p = line.indexOf('P');
  int t = line.indexOf('T');
  if (p < 0 || t < 0 || p > t) {
    if (line.length() > 0) Serial.println("ERR 格式: P<pan>,T<tilt> / H / RC=i|c|s / RCV");
    return;
  }
  panTgt  = constrain(line.substring(p + 1, t).toInt(), PAN_MIN,  PAN_MAX);
  tiltTgt = constrain(line.substring(t + 1).toInt(),     TILT_MIN, TILT_MAX);
  if (rcManual) { rcManual = false; Serial.println("MODE=USB"); }
  Serial.printf("OK pan=%d tilt=%d\n", panTgt, tiltTgt);
}

void stepTowards() {
  if (panCur != panTgt) {
    panCur += (panTgt > panCur ? STEP : -STEP);
    if (fabs(panTgt - panCur) < STEP) panCur = panTgt;
    panServo.write((int)panCur);
  }
  if (tiltCur != tiltTgt) {
    tiltCur += (tiltTgt > tiltCur ? STEP : -STEP);
    if (fabs(tiltTgt - tiltCur) < STEP) tiltCur = tiltTgt;
    tiltServo.write((int)tiltCur);
  }
}
