// gimbal_firmware_ledc.ino
// ESP32-C6 两轴云台 — 舵机 + 遥控输入固件【LEDC 手写版】
//
// ============================================================
// 为什么有这一版
// ============================================================
// 原版 gimbal_firmware/gimbal_firmware.ino 用 ESP32Servo 库，
// 现象：attach=1,1 正常、串口回显 "OK pan=120" 漂漂亮亮，
//       **但舵机一个都不转**。而同一个舵机直接外部供电会转 → 舵机本体没问题。
//
// 破案：ESP32Servo 库在 ESP32-C6 上的兼容问题。
//   ESP32-C6 的 LEDC **只有 LOW_SPEED_MODE**（没有 HIGH_SPEED_MODE），
//   而 ESP32Servo/ESP32PWM 内部默认按有高速模式那套配置走，
//   结果就是「挂载成功、duty 写进去了、引脚上没波形」。
//
// 这一版直接调 ESP-IDF 的 driver/ledc.h 底层 API：
//   - 明确用 LEDC_LOW_SPEDE_MODE（C6 唯一可用的）
//   - timer 和 channel 全部自己指定，不依赖库自动分配
//   - 16-bit 分辨率 + 50Hz，duty 用 us 直算
//
// 附带诊断命令（不烧也能先用万用表验证，见文件末尾注释）：
//   M1000 / M1500 / M2000   直接设脉宽（us），绕过角度换算
//   PWM                      打印当前两路的 duty/脉宽/占空比
//   TEST                     自动扫 1000→1500→2000us 各停 1.5s，方便万用表测
// ============================================================
//
// 开发环境（和原版一样，不用装新东西）：
//   Arduino IDE → 开发板管理装 "esp32" (≥3.0) → 工具→开发板 选 "ESP32C6 Dev Module"
//   ⚠️ 本版**不需要**装 ESP32Servo 库，反而更干净
//
// 烧录后打开串口监视器 115200，应看到 READY；
// 发 "P90,T45\n" 控角度，发 "H\n" 回中。
//
// 接线（和原版完全一致，别改）：
//   C6 GPIO10 → pan 舵机信号(橙/黄)；GPIO11 → tilt 舵机信号(橙/黄)
//   舵机红线→外部 5V、棕/黑→GND(必须与 C6 的 GND 共地)
//   ⚠ 降压模块先用万用表测准 5.0V 再接舵机，12V 直冲会烧毁 SG90
//   ⚠ 舵机电源只认降压模块，**绝不接 C6 的 3.3V/5V 排针**（带不动，C6 会反复重启）
//   遥控接收机信号(单线) → C6 GPIO6（UART1 RX，只收不发）
//
// 引脚说明：原 GPIO2/3 改为 GPIO10/11，收缩到面包板可用列
//   （4/5/8/9/15 是 strapping、12/13 是原生 USB DM/DP、1 是 32K 晶振，均避开）。
//
// 遥控支持三种协议（自动识别，也可用 RC= 命令手动锁定）：
//   i-BUS  FlySky FS-A8S 等      115200 8N1 不反相  帧头 0x20 0x40
//   CRSF   ELRS 接收机           420000 8N1 不反相  帧 0xC8 len 0x16 + CRC8(poly 0xD5)
//   SBUS   FrSky / A8S 也可输出  100000 8E2 【反相】——C6 的 UART 有硬件反相寄存器，
//          打开 invert 即可直接收，不需要外接三极管反相器
//   通道值统一归一为 1000~2000（中位 1500），ch1→pan，ch2→tilt。
//
// 控制模式（最后输入优先，不用记开关）：
//   摇杆偏离中位 → 遥控模式（速度控制）
//   串口收到 P,T/H 命令 → USB 模式（tracker.py 自动追踪接管）

#include <driver/ledc.h>

// ================= 引脚与量程 =================
const int PAN_PIN  = 10, TILT_PIN = 11;   // 避开 strapping 脚 4/5/8/9/15 与 USB 脚 12/13
// 量程标定（2026-10-24，现用 MakerWorld #2045352「Sg90舵机云台修改」）：
//   实测方法：不通电手推 tilt 全程，无明显结构死挡位 → 约束来自 SG90 内部行程（约 180°），
//   结构件（含作者「抬高限位」改进）不提前干涉 → 限位按舵机安全行程设，与 pan 对齐。
//   两端各留 10°：防止舵机长期顶内部死点（嗡嗡声/电流/齿轮磨损）。
//   ⚠️ 原值 TILT 20~110 是按自研 gimbal.scad 定的，已弃用；那版 tilt 上仰被结构吃到只有 20°。
const int PAN_MIN  = 10, PAN_MAX  = 170;
const int TILT_MIN = 10, TILT_MAX = 170;

const int   SERVO_MIN_US = 1000;          // 角度 0°  对应脉宽
const int   SERVO_MAX_US = 2000;          // 角度 180° 对应脉宽
const int   SERVO_MID_US = 1500;          // 中位

float panCur = 90, tiltCur = 90;
int   panTgt = 90, tiltTgt = 90;          // 必须 int：printf %d 打 float 在 RISC-V 上读到的是寄存器残留乱值
const float STEP = 1.5;                   // 每步度数（平滑插值）

// ================= LEDC 配置（C6 只有 LOW_SPEED_MODE） =================
const ledc_mode_t      LEDC_MODE   = LEDC_LOW_SPEED_MODE;   // ⚠️ C6 没有 HIGH_SPEED_MODE
const ledc_timer_t     TIM_PAN     = LEDC_TIMER_0;
const ledc_timer_t     TIM_TILT    = LEDC_TIMER_1;
const ledc_channel_t   CH_PAN      = LEDC_CHANNEL_0;
const ledc_channel_t   CH_TILT     = LEDC_CHANNEL_1;
const uint32_t         LEDC_FREQ   = 50;                    // 舵机标准 50Hz（周期 20000us）
const ledc_timer_bit_t LEDC_RES    = LEDC_TIMER_16_BIT;     // 16-bit → duty 0..65535

// 当前实际输出的脉宽（us），PWM 命令用
int panUs = SERVO_MID_US, tiltUs = SERVO_MID_US;

// ================= 底层 PWM 写入 =================
// us → duty（16-bit）。1500us → 4915；1000us → 3276；2000us → 6553
uint32_t usToDuty(int us) {
  if (us < 500)  us = 500;
  if (us > 2500) us = 2500;
  return (uint32_t)((uint64_t)us * 65535ULL / 20000ULL);
}

// 角度 → 脉宽
int angleToUs(int a) {
  return SERVO_MIN_US + (int)((float)(SERVO_MAX_US - SERVO_MIN_US) * a / 180.0f + 0.5f);
}

// 写 pan 脉宽
void panWriteUs(int us) {
  panUs = us;
  ledc_set_duty(LEDC_MODE, CH_PAN, usToDuty(us));
  ledc_update_duty(LEDC_MODE, CH_PAN);
}
void tiltWriteUs(int us) {
  tiltUs = us;
  ledc_set_duty(LEDC_MODE, CH_TILT, usToDuty(us));
  ledc_update_duty(LEDC_MODE, CH_TILT);
}

// 初始化一路：timer 配 50Hz/16bit，channel 绑 GPIO，先给中位 duty
void servoInit(ledc_timer_t tim, ledc_channel_t ch, int pin, const char *name) {
  ledc_timer_config_t tc = {
    .speed_mode      = LEDC_MODE,
    .duty_resolution = LEDC_RES,
    .timer_num       = tim,
    .freq_hz         = LEDC_FREQ,
    .clk_cfg         = LEDC_AUTO_CLK,
  };
  ledc_timer_config(&tc);

  ledc_channel_config_t cc = {
    .gpio_num   = (gpio_num_t)pin,
    .speed_mode = LEDC_MODE,
    .channel    = ch,
    .intr_type  = LEDC_INTR_DISABLE,
    .timer_sel  = tim,
    .duty       = usToDuty(SERVO_MID_US),
    .hpoint     = 0,
  };
  esp_err_t e = ledc_channel_config(&cc);
  Serial.printf("%s: gpio=%d ch=%d tim=%d %s\n", name, pin, (int)ch, (int)tim,
                e == ESP_OK ? "OK" : "FAIL");
}

// ================= 遥控输入（i-BUS / CRSF / SBUS 三协议） =================
const int RC_RX_PIN = 6;
const int RC_TX_PIN = 7;

enum { RC_NONE = 0, RC_IBUS, RC_CRSF, RC_SBUS };
const char *RC_NAME[4] = { "none", "i-BUS", "CRSF", "SBUS" };
int rcProto = RC_NONE;
uint16_t rcCh[16];
unsigned long rcLastFrame = 0;
unsigned long rcNextScan = 0;
int rcScanIdx = RC_IBUS;
bool rcLocked = false;
bool rcManual = false;
float panRate = 0, tiltRate = 0;

const int   RC_DEAD = 25;
const float RC_RATE_PAN  = 2.2;
const float RC_RATE_TILT = 2.0;

uint8_t rcBuf[64];
int rcLen = 0;

void rcBegin(int proto) {
  switch (proto) {
    case RC_IBUS: Serial1.begin(115200, SERIAL_8N1, RC_RX_PIN, RC_TX_PIN, false); break;
    case RC_CRSF: Serial1.begin(420000, SERIAL_8N1, RC_RX_PIN, RC_TX_PIN, false); break;
    case RC_SBUS: Serial1.begin(100000, SERIAL_8E2, RC_RX_PIN, RC_TX_PIN, true);  break;
  }
  rcLen = 0;
}

uint8_t crc8(const uint8_t *d, int n) {
  uint8_t c = 0;
  while (n--) {
    c ^= *d++;
    for (int i = 0; i < 8; i++) c = (c & 0x80) ? (c << 1) ^ 0xD5 : (c << 1);
  }
  return c;
}

uint16_t bits11(const uint8_t *b, int idx) {
  int bit = idx * 11, byte = bit / 8, off = bit % 8;
  uint32_t v = b[byte] | (b[byte + 1] << 8) | (b[byte + 2] << 16);
  return (v >> off) & 0x7FF;
}

bool rcFeed(uint8_t b) {
  if (rcProto == RC_CRSF) {
    if (rcLen == 0 && b != 0xC8) return false;
    if (rcLen == 1 && b > 62)    { rcLen = 0; return false; }
    if (rcLen < 64) rcBuf[rcLen++] = b;
    if (rcLen >= 2 && rcLen == rcBuf[1] + 2) {
      bool ok = false;
      if (rcBuf[2] == 0x16 && rcBuf[1] == 0x18) {
        if (crc8(&rcBuf[2], rcBuf[1]) == rcBuf[rcLen - 1]) {
          for (int i = 0; i < 16; i++) {
            uint16_t v = bits11(&rcBuf[3], i);
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
    if (rcLen == 0 && b != 0x0F) return false;
    if (rcLen < 25) rcBuf[rcLen++] = b;
    if (rcLen == 25) {
      bool ok = (rcBuf[24] == 0x00);
      if (ok && !(rcBuf[23] & 0x0C)) {
        for (int i = 0; i < 16; i++) {
          uint16_t v = bits11(&rcBuf[1], i);
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
        uint16_t v = rcBuf[2 + i * 2] | (rcBuf[3 + i * 2] << 8);
        rcCh[i] = constrain(v, 1000, 2000);
      }
    }
    rcLen = 0;
    return ok;
  }
  return false;
}

void rcPoll() {
  if (rcProto != RC_NONE) {
    while (Serial1.available()) if (rcFeed(Serial1.read())) rcLastFrame = millis();
    if (millis() - rcLastFrame > 800 && !rcLocked) {
      rcProto = RC_NONE;
      rcNextScan = 0;
    }
  }
  if (rcProto == RC_NONE && !rcLocked && millis() >= rcNextScan) {
    rcBegin(rcScanIdx);
    unsigned long until = millis() + 200;
    bool got = false;
    while (millis() < until) {
      while (Serial1.available()) {
        if (rcFeed(Serial1.read())) { rcLastFrame = millis(); got = true; }
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
  if (rcProto != RC_NONE && millis() - rcLastFrame < 300) {
    int dx = rcCh[0] - 1500, dy = rcCh[1] - 1500;
    panRate  = (abs(dx) > RC_DEAD) ? dx / 500.0 * RC_RATE_PAN  : 0;
    tiltRate = (abs(dy) > RC_DEAD) ? dy / 500.0 * RC_RATE_TILT : 0;
    if (panRate != 0 || tiltRate != 0) {
      if (!rcManual) { rcManual = true; Serial.println("MODE=RC"); }
      panTgt  = constrain(panTgt  + panRate,  PAN_MIN,  PAN_MAX);
      tiltTgt = constrain(tiltTgt + tiltRate, TILT_MIN, TILT_MAX);
    }
  } else {
    panRate = tiltRate = 0;
  }
}

// ================= 诊断命令 =================
void printPwm() {
  Serial.printf("PWM pan  gpio=%d us=%d duty=%u pct=%.1f%%  (avg %.3fV)\n",
                PAN_PIN, panUs,  usToDuty(panUs),
                panUs  / 200.0,  panUs  / 20000.0 * 3.3);
  Serial.printf("PWM tilt gpio=%d us=%d duty=%u pct=%.1f%%  (avg %.3fV)\n",
                TILT_PIN, tiltUs, usToDuty(tiltUs),
                tiltUs / 200.0, tiltUs / 20000.0 * 3.3);
}

void runTest() {
  Serial.println("TEST: 扫 1000/1250/1500/1750/2000us，每档 1.5s —— 万用表直流档测 GPIO10 对 GND");
  int seq[] = { 1000, 1250, 1500, 1750, 2000 };
  for (int i = 0; i < 5; i++) {
    panWriteUs(seq[i]);
    tiltWriteUs(seq[i]);
    Serial.printf("  us=%d  duty=%u  期望平均 %.3fV\n",
                  seq[i], usToDuty(seq[i]), seq[i] / 20000.0 * 3.3);
    delay(1500);
  }
  printPwm();
  Serial.println("TEST done");
}

// ================= 串口命令 =================
void readCommand() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();

  if (line == "H") {
    panTgt = 90; tiltTgt = 90;
    if (rcManual) { rcManual = false; Serial.println("MODE=USB"); }
    Serial.println("OK center"); return;
  }
  if (line == "PWM") { printPwm(); return; }
  if (line == "TEST") { runTest(); return; }
  if (line.startsWith("M")) {                 // M1500 → 直接设 pan 脉宽（us），诊断用
    int us = line.substring(1).toInt();
    if (us >= 500 && us <= 2500) {
      panWriteUs(us);
      Serial.printf("OK pan_us=%d duty=%u (tilt 不动)\n", us, usToDuty(us));
    } else {
      Serial.println("ERR 脉宽范围 500~2500us");
    }
    return;
  }
  if (line.startsWith("RC=")) {
    char c = line.charAt(3);
    if (c == 'i') { rcLocked = true;  rcProto = RC_IBUS;  rcBegin(RC_IBUS); }
    if (c == 'c') { rcLocked = true;  rcProto = RC_CRSF;  rcBegin(RC_CRSF); }
    if (c == 's') { rcLocked = true;  rcProto = RC_SBUS;  rcBegin(RC_SBUS); }
    Serial.printf("RC=%s\n", RC_NAME[rcProto]);
    return;
  }
  if (line == "RC") { Serial.printf("RC=%s manual=%d\n", RC_NAME[rcProto], rcManual); return; }
  if (line == "RCV") {
    Serial.print("RCV");
    for (int i = 0; i < 16; i++) Serial.printf(" %d", rcCh[i]);
    Serial.println();
    return;
  }

  int p = line.indexOf('P');
  int t = line.indexOf('T');
  if (p < 0 || t < 0 || p > t) {
    if (line.length() > 0) Serial.println("ERR 格式: P<pan>,T<tilt> / H / M<us> / PWM / TEST / RC=i|c|s / RCV");
    return;
  }
  panTgt  = constrain(line.substring(p + 1, t).toInt(), PAN_MIN,  PAN_MAX);
  tiltTgt = constrain(line.substring(t + 1).toInt(),     TILT_MIN, TILT_MAX);
  if (rcManual) { rcManual = false; Serial.println("MODE=USB"); }
  Serial.printf("OK pan=%d tilt=%d\n", panTgt, tiltTgt);
}

// ================= 主流程 =================
void setup() {
  Serial.begin(115200);
  delay(200);

  Serial.println("BOOT LEDC 版（driver/ledc.h 底层，LOW_SPEED_MODE）");
  servoInit(TIM_PAN,  CH_PAN,  PAN_PIN,  "pan ");
  servoInit(TIM_TILT, CH_TILT, TILT_PIN, "tilt");
  panWriteUs(SERVO_MID_US);
  tiltWriteUs(SERVO_MID_US);
  printPwm();
  Serial.printf("READY pan=GPIO%d tilt=GPIO%d range=%d..%d..%dus limit=%d..%d/%d..%d\n",
                PAN_PIN, TILT_PIN, SERVO_MIN_US, SERVO_MID_US, SERVO_MAX_US,
                PAN_MIN, PAN_MAX, TILT_MIN, TILT_MAX);
  Serial.println("RC: 自动识别 i-BUS/CRSF/SBUS，信号线接 GPIO6");
  Serial.println("诊断: M<us> 设脉宽 | PWM 看当前 | TEST 扫脉宽（万用表测）");
}

void loop() {
  rcPoll();
  readCommand();
  stepTowards();
  delay(15);
}

void stepTowards() {
  if (panCur != panTgt) {
    panCur += (panTgt > panCur ? STEP : -STEP);
    if (fabs(panTgt - panCur) < STEP) panCur = panTgt;
    panWriteUs(angleToUs((int)panCur));
  }
  if (tiltCur != tiltTgt) {
    tiltCur += (tiltTgt > tiltCur ? STEP : -STEP);
    if (fabs(tiltTgt - tiltCur) < STEP) tiltCur = tiltTgt;
    tiltWriteUs(angleToUs((int)tiltCur));
  }
}

// ============================================================
// 附：没有示波器怎么验证 PWM 真的在输出（万用表就够）
// ============================================================
// 50Hz、3.3V 高电平的 PWM，用万用表**直流电压档**测 GPIO10 对 GND，
// 读到的是平均电压，和脉宽成正比：
//
//   脉宽 1000us → duty 3276 → 占空比 5.0%  → 平均 0.165V
//   脉宽 1250us → duty 4095 → 占空比 6.25% → 平均 0.206V
//   脉宽 1500us → duty 4915 → 占空比 7.5%  → 平均 0.248V
//   脉宽 1750us → duty 5734 → 占空比 8.75% → 平均 0.289V
//   脉宽 2000us → duty 6553 → 占空比 10.0% → 平均 0.330V
//
// 判读：
//   读到 0V                → 固件根本没输出（引脚/烧录/代码问题）
//   读到 0.16~0.33V 之间的值 → PWM 在正常输出！问题在舵机侧或共地
//   读到 ~3.3V             → duty 被写满了（配置错），不是 50Hz PWM
//
// 串口发 TEST，固件会自动扫上面 5 档各 1.5 秒，盯着万用表读数就行。
