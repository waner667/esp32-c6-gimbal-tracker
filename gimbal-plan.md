# USB 摄像头两轴云台 · 项目规划

> 目标：舵机 + 3D 打印结构件做两轴云台（水平 pan + 俯仰 tilt），USB 摄像头坐在云台上，电脑实时显示画面并控制角度。
> 已有：USB 摄像头 ×1、舵机 ×2、拓竹 A1 mini。
> 方案一句话：**ESP32 做主控，电脑跑 Python/OpenCV，结构件全部 A1 mini 打印，舵机独立 5V 供电。**

> **已锁定参数**（2026-10-19 更新，来自 waner 确认 + 实测/查证）：
> - 舵机：**SG90 ×2**（9g 塑料齿，堵转扭矩 1.8 kg·cm），另备 DS1906B 一只
> - 摄像头负载：机身 8.8 g，含 USB 线共 **38 g** → SG90 余量约 9~16×，扭矩充足
> - 用途：**物体/人脸跟踪**，目标「类 YOLO 框选识别」（电脑端 Python + YOLOv8n）
> - 暂时不脱离电脑（ESP32 经 USB 串口受电脑控制）
> - 供电建议：舵机用**独立 5V 2A 电源**，与 ESP32 共地；ESP32 + 摄像头走电脑 USB（详见第 3、5 节）

---

## 1. 总体架构

数据流：

- 摄像头 →（USB 视频）→ 电脑 OpenCV 显示
- 电脑 →（USB 串口，文本协议 `P<pan>,T<tilt>\n`）→ ESP32
- ESP32 →（2 路 PWM）→ pan / tilt 舵机
- 5V 3A 电源 → 舵机（与 ESP32 **共地**）
- 拓竹 A1 mini → 打印 3 个结构件 → 装配

建议行程：pan ±90°（防止 USB 线绞线），tilt -15°~+60°。

## 2. 硬件清单

### 已有

| 物料 | 说明 |
|---|---|
| USB 摄像头 | UVC 免驱，OpenCV 直接取流；机身 8.8 g，加 USB 线共 38 g |
| 舵机 ×2 | **SG90（9g 塑料齿，1.8 kg·cm）** ×2，另备 DS1906B 一只 |
| 拓竹 A1 mini | 构建体积 180³ mm，打印全部结构件 |

### 其余物料（合计约 ¥15~25；电源与主控已用现有设备替代）

| 物料 | 规格 | 数量 | 参考价 | 备注 |
|---|---|---|---|---|
| 主控板 | **ESP32-C6 DevKitC-1**（waner 已有；WiFi6/BLE/Thread，后续可脱离电脑走无线） | 1 | 已有 | 用 ESP32Servo 库 + LEDC 出舵机 PWM |
| 舵机供电 | **已有替代**：12V 可调电源 + 降压模块调到 5V（先测再接舵机！） | — | 已有 | 不必另购 5V 适配器；舵机必须独立 5V 供电，与 C6 共地 |
| 杜邦线 | 公对母 20cm | 1 套 | ¥5 | |
| 螺丝 | **基本可复用 SG90 自带件**：中心固定螺丝（锁舵机臂于花键轴）+ 机体安装螺丝（锁舵机入底座）。仅"舵机臂↔打印摆臂"连接处可能需 2 颗 M2×6 自攻（¥1~2），或先用热熔胶临时固定 | 若干 | ¥1~2（可选） | |
| 可选 | MPU6050 陀螺仪 / 0.96" OLED / 608 轴承 | | | 姿态闭环、状态显示、减小摩擦 |

## 3. 舵机扭矩核算（先对号入座）

公式：**需求扭矩 = 摄像头重量(g) × 重心到 tilt 轴距离(cm)，再留 ≥2 倍余量**。
pan 轴转动惯量小，同规格舵机即可，不用加码。

| 舵机 | 堵转扭矩 | 适合摄像头 | 最大力臂（含余量） | 参考价 |
|---|---|---|---|---|
| SG90（9g 塑料齿） | ~1.8 kg·cm | ≤120 g | ~4 cm | ¥3~5 |
| MG996R（55g 金属齿） | ~10 kg·cm | ≤300 g | ~10 cm | ¥10~15 |
| 20kg 数字舵机 | ~20 kg·cm | ≤500 g | ~15 cm | ¥25~40 |

例：摄像头 180 g、重心距 tilt 轴 5 cm → 需求 900 g·cm ×2 = 1.8 kg·cm，SG90 临界，建议 MG996R。

**结论先行：普通 USB 摄像头大多 100~250 g，直接上 MG996R 最稳；SG90 只适合很轻的小摄像头。**
如果你手上的舵机是串行总线舵机（LX-16A / SCS0009 这类，三根线级联、可读角度和温度），告诉我，方案会更简单——一个串口带两个舵机，布线大幅简化。

## 4. 机械结构（A1 mini 打印）

侧视结构：底座 → pan 舵机（轴朝上）→ U 型框 → tilt 舵机（横装）→ 摄像头夹 → 摄像头。

### 打印件清单（3+1 件）

| # | 零件 | 要点 |
|---|---|---|
| 1 | 底座 | pan 舵机座（舵机耳朵孔距约 27.5×10 mm，按型号核实）、中心让位孔、侧面走线孔、底部防滑垫 |
| 2 | U 型框 | pan 舵机臂连接盘 + 双立柱 + 顶部 tilt 舵机座，一体打印；立柱开走线孔 |
| 3 | 摄像头夹 | tilt 舵机臂连接 + 摄像头仓（按实测尺寸设计，顶部压片夹紧，别用螺丝直接拧摄像头外壳） |
| 4 | 可选 | 理线环 / 限位块 / 尾部配重块 |

### 设计避坑要点

- **舵机齿轴是花键，不要打印内齿去啮合**——用舵机自带臂 + 螺丝锁进打印件。SG90 自带两类螺丝：**中心固定螺丝**（把臂锁在花键轴上，**必须螺丝，胶粘不住、会打滑**）+ **机体安装螺丝**（可复用，把舵机锁进打印底座的耳朵孔）。仅"臂↔打印摆臂"那道连接可用 2 颗 M2 自攻做硬连接；**PETG 表面热熔胶附着力差，不建议用热熔胶**，临时固定可用环氧胶或双面泡棉胶（轻负载可行，但会有旷量、不可调，跟踪精度要求高时换螺丝）。
- **旋转中心对齐**：tilt 舵机轴心与摄像头重心尽量共面。重心越靠近轴，所需扭矩越小、抖动越小
- **间隙**：活动配合留 0.2~0.3 mm；M3 通孔打 φ3.2 mm（补偿打印缩孔）；自攻孔打 φ2.0 mm
- **打印方向**：U 框立着打（层理垂直于受力方向），底座 / 摄像头夹平打
- **填充**：舵机座、连接盘 40%，其余 20%；墙 3 层
- **材料**：**PETG（waner 已定）**。比 PLA 韧、耐温、抗冲击，适合常拆装的云台结构件；但更粘刀/易拉丝、对热熔胶附着力差、打印需更高床温与更慢速度。见下方 PETG 打印要点。
- **A1 mini 参数（PETG）**：0.4 喷嘴 / 0.2 mm 层高；喷嘴 230~245℃、热床 75~85℃；速度比 PLA 降 20~30%；风扇 30~50%（PETG 别全开，需层间热量）；高 U 框首层加 brim/raft 防翘边；开启支撑（U 框顶部横梁朝下开口、夹子内壁都有悬空）；PETG 易拉丝，收尾回抽调好。PETG 自攻螺丝孔建议先打 φ2.0 引孔再拧，避免开裂。三个零件合计约 6~10 小时。

### 走线设计（重点）

摄像头 USB 线从 U 框立柱走线孔穿到 pan 中心，从底座侧面出；pan 行程限 ±90°，线留足余量。
想 360° 连续旋转才需要滑环，本项目不需要。

## 5. 电控与固件

### 接线

| 信号 | ESP32-C6 | 舵机 |
|---|---|---|
| pan 信号 | **GPIO 2** | 信号线（橙/黄） |
| tilt 信号 | **GPIO 3** | 信号线（橙/黄） |
| 5V | 外部 5V 2A 电源 + | 电源线（红） |
| GND | 外部电源 GND **与 C6 GND 共地** | 地线（棕/黑） |

注意（ESP32-C6 特有问题）：

- **舵机信号脚必须用安全 GPIO**：C6 的 GPIO 4/5/8/9/15 是 strapping 脚，上电采样电平，接舵机可能导致无法启动。本项目用 **GPIO 2（pan）/ GPIO 3（tilt）**，备选 GPIO 10/11。
- 舵机**独立 5V 2A 供电**，**必须与 C6 共地**（C6 的 GND 接外部电源 GND），否则 PWM 无参考电平、舵机不响应。**不要从 C6 的 5V 引脚给舵机取电**（只是 USB 直通，带不动）。
- **waner 已有 12V 可调电源 + 降压模块**：可直接替代 5V 适配器——把降压模块输出调到 **5.0V（务必先用万用表测准，再接舵机！12V 直冲会瞬间烧毁 SG90）**，电流余量比充电头更足。舵机红线接降压输出 +，棕/黑接 GND；该 GND 与 C6 的 GND 连到一起（共地）。降压模块输出端建议并一颗 470µF 电解电容，抑制纹波导致的舵机抖动。
- C6 有 **两个 USB-C**：USB-to-UART 口（经桥接，接电脑串口用这个）和 原生 USB（GPIO12/13，Serial/JTAG）。本项目用 USB-to-UART 口供电 + 串口即可。
- C6 是 3.3V 逻辑，SG90 信号阈值约 3V，实测可正常识别，无需电平转换。
- 开发环境：Arduino IDE 选「ESP32C6 Dev Module」，esp32 core ≥ 3.0，库 **ESP32Servo ≥ 0.13**（不要用 AVR 的 Servo.h）。

### 通信协议

`P<pan>,T<tilt>\n`，例：`P90,T45\n`；`H\n` 回中。

### 固件（Arduino for ESP32）

```cpp
#include <ESP32Servo.h>

Servo panServo, tiltServo;
const int PAN_PIN = 10, TILT_PIN = 11;  // C6 安全 GPIO，避开 strapping 脚 4/5/8/9/15 与 USB 脚 12/13
const int PAN_MIN = 10, PAN_MAX = 170;    // 软件限位，按结构调整
const int TILT_MIN = 20, TILT_MAX = 110;

float panCur = 90, tiltCur = 90;          // 当前角度
float panTgt = 90, tiltTgt = 90;          // 目标角度
const float STEP = 1.5;                   // 每步度数（平滑插值）

void setup() {
  Serial.begin(115200);
  ESP32PWM::allocateTimer(0);          // 每舵机独立定时器，避免 LEDC 冲突
  ESP32PWM::allocateTimer(1);
  panServo.setPeriodHertz(50);         // 标准 50Hz 舵机信号
  tiltServo.setPeriodHertz(50);
  panServo.attach(PAN_PIN, 1000, 2000);   // 脉冲 1ms~2ms 对应 0°~180°
  tiltServo.attach(TILT_PIN, 1000, 2000);
  panServo.write((int)panCur);
  tiltServo.write((int)tiltCur);
  Serial.println("READY");
}

void loop() {
  readCommand();
  stepTowards();
  delay(15);
}

void readCommand() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line == "H") { panTgt = 90; tiltTgt = 90; return; }
  int p = line.indexOf('P');
  int t = line.indexOf('T');
  if (p < 0 || t < 0 || p > t) return;    // 协议要求 P 在 T 前
  panTgt  = constrain(line.substring(p + 1, t).toInt(), PAN_MIN,  PAN_MAX);
  tiltTgt = constrain(line.substring(t + 1).toInt(),     TILT_MIN, TILT_MAX);
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
```

固件已内置的细节：

- 平滑插值：15 ms 一步、每步 1.5°，到位前自动收敛，消除瞬跳和异响
- 软件限位：pan 10°~170°，tilt 20°~110°（按实际结构调）
- 上电归中

## 6. 电脑端软件（Python）

依赖：`pip install opencv-python pyserial`（跟踪可加 `mediapipe`）

```python
import cv2
import serial

SER = serial.Serial("COM3", 115200, timeout=0.1)   # 端口按实际改
cap = cv2.VideoCapture(0)                          # 摄像头序号按实际改

PAN_MIN, PAN_MAX = 10, 170
TILT_MIN, TILT_MAX = 20, 110
pan, tilt = 90, 90

def send(p, t):
    SER.write(f"P{int(p)},T{int(t)}\n".encode())

send(pan, tilt)

while True:
    ok, frame = cap.read()
    if not ok:
        break
    frame = cv2.flip(frame, 1)                     # 镜像，操作更直觉

    key = cv2.waitKey(1) & 0xFF
    if   key == ord('a'): pan  = max(PAN_MIN,  pan - 2)
    elif key == ord('d'): pan  = min(PAN_MAX,  pan + 2)
    elif key == ord('w'): tilt = min(TILT_MAX, tilt - 2)   # 方向视安装而定
    elif key == ord('s'): tilt = max(TILT_MIN, tilt + 2)
    elif key == ord('h'): pan, tilt = 90, 90
    elif key == 27: break                            # Esc 退出
    send(pan, tilt)

    cv2.putText(frame, f"pan={int(pan)}  tilt={int(tilt)}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 180, 0), 2)
    cv2.imshow("gimbal", frame)

cap.release()
SER.close()
cv2.destroyAllWindows()
```

进阶：人脸跟踪（比例控制，稳了再换 PID）。替换主循环里的键盘控制部分即可：

```python
face = cv2.CascadeClassifier(cv2.data.haarcascades +
                             "haarcascade_frontalface_default.xml")

gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
faces = face.detectMultiScale(gray, 1.2, 5, minSize=(80, 80))
if len(faces):
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    err_x = (x + w // 2) - frame.shape[1] // 2
    err_y = (y + h // 2) - frame.shape[0] // 2
    pan  = min(max(pan  + 0.08 * err_x, PAN_MIN),  PAN_MAX)   # 比例控制
    tilt = min(max(tilt + 0.08 * err_y, TILT_MIN), TILT_MAX)
    send(pan, tilt)
    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 180, 0), 2)
```

注意：

- 摄像头画面镜像（`cv2.flip`）后操作更直觉
- w/s 增减方向取决于 tilt 舵机安装方向，调试时反过来即可

## 7. 分阶段计划

| 阶段 | 内容 | 产出 |
|---|---|---|
| 1 · 点亮（半天） | ESP32 + 1 个舵机串口控制；OpenCV 取流 | 确认舵机行程、极性、摄像头可用 |
| 2 · 机械（1~2 天） | 量摄像头尺寸和舵机型号 → 建模 → A1 mini 打印试装 | 3 个结构件，修公差 |
| 3 · 联动（1 天） | 固件 + 电脑端联调，键盘控制界面 | 可手动操控的云台 |
| 4 · 智能（选做 2~3 天） | 人脸/颜色跟踪 + PID 跟随、预置位、巡航扫描 | 自动跟踪云台 |

## 8. 风险与对策

| 风险 | 现象 | 对策 |
|---|---|---|
| 扭矩不足 | 抖、嗡嗡响、发热 | 换大扭矩舵机 / 缩短力臂 / 尾部配重 |
| 供电不足 | 主控重启、舵机抽搐 | 独立 5V 3A、共地、电源端并 470µF 电容 |
| 齿轮间隙 | 到位后回弹、画圈 | 打印件消除间隙；软件单向逼近目标 |
| 绞线 | 转到限位发卡 | pan 限 ±90°、走线孔、留余量 |
| 打印公差 | 装不进或太松 | 孔位补偿、活动间隙 0.2~0.3 mm |
| 摄像头太重 | 抬不起来 | 换轻摄像头 / 配重 / 重心靠轴 |

## 9. 已确认事项

| # | 项 | 确认结果 |
|---|---|---|
| 1 | 舵机型号 | **SG90 ×2**（另备 DS1906B） |
| 2 | 摄像头重量 | 机身 8.8 g，含 USB 线 38 g |
| 3 | 用途 | **物体/人脸跟踪**，类 YOLO 框选识别 |
| 4 | 是否脱离电脑 | 暂时不脱离（ESP32 受电脑 USB 串口控制） |

### 待最终拍板（2 项，可口头确认）

- **供电**：推荐舵机独立 5V 2A 电源 + 与 ESP32 共地；ESP32 与摄像头共用电脑 USB。若想从电脑 USB 一口带全部，需确认电脑 USB 口电流（USB3.0 约 900mA，可能不够双舵机峰值）。
- **跟踪方案**：推荐电脑端 **YOLOv8n（ultralytics）** 做通用物体检测框选；人脸可叠加 MediaPipe。ESP32 只管舵机转动，识别全在电脑。

## 10. 下一步我可以直接做

- 生成参数化 3D 模型（OpenSCAD，改尺寸即改模型，直接导入 Bambu Studio 打印）
- 写固件 + 电脑端完整工程
- 跟踪算法 demo

---

## 11. 明日继续 Checkpoint（2026-10-19 收尾）

> 本项目的"存档点"。明天直接从这个状态往下做，不用重聊背景。

### ✅ 已经定死 / 做完的事

| 项 | 状态 |
|---|---|
| 总体架构（ESP32-C6 + 双 SG90 + 电脑 OpenCV/YOLO，结构件全 A1 mini 打） | 已定稿 |
| 舵机型号 | 锁定 **SG90 ×2**（另备 DS1906B） |
| 摄像头负载 | 机身 8.8 g / 含线 38 g → SG90 扭矩余量 9~16×，够 |
| 用途 | 类 YOLO 物体/人脸框选跟踪 |
| 主控板 | 锁定 **ESP32-C6**，信号脚改为安全 GPIO：**GPIO10(pan)/GPIO11(tilt)**（避开 strapping 脚 4/5/8/9/15 与 USB 脚 12/13） |
| 固件库 | 由 AVR Servo.h 改为 **ESP32Servo**，已含完整固件代码（串口协议 `P<pan>,T<tilt>`、平滑插值、软件限位、上电归中） |
| 电脑端代码 | 已含手动键盘控制 + 人脸跟踪 demo（OpenCV + Haar） |
| C6 接线图、采购清单 | 已给出 |
| 3D 结构件（云台骨架） | ✅ 采用现成 MakerWorld「SG90 双轴云台修改版」，waner 已按此完成机械装配 |

### 🔜 明天推荐起手动作（按"先不一次性做完"的节奏，二选一）

- **路线 A · 先点亮验证（最稳，建议先做）** ✅ 零件已齐（waner 已有面包板 + 杜邦线，现在就能做）
  在面包板上接 1 个 SG90 到 C6 的 GPIO10 + 独立 5V（12V 降压模块调到 5V，共地），烧固件 `gimbal_firmware/gimbal_firmware.ino`，串口监视器看到 `READY` 且舵机转到 90° 即成功。这一步能最早暴露供电/接线坑。
- **路线 B · 3D 结构件** ✅ 已采用现成模型
  改为采用 MakerWorld 现成模型「[SG90 舵机云台修改（仰角限位+底座）](https://makerworld.com.cn/zh/models/2045352)」(lilithlying 原设计、作者二次修改)，**A1 mini + PETG 兼容，双 SG90 两轴**，waner 已按此完成机械装配。装机要点：① 下方舵机用**插入式**(夹入会限制上方舵机仰角)；② 导线走槽集中布线。自研 `gimbal.scad` 仅作摄像头转接件参考，不再作为主结构。

> 之前你选过"先理接线/采购"，所以 C6 接线图和采购清单已就绪。**点亮验证和出模型不冲突**，可以先点亮、同时后台出模型。

### 📋 开工前需要你这边的小动作

1. **供电已解决**：用你已有的 **12V 可调电源 + 降压模块调到 5V** 给舵机供电，与 C6 共地；C6 和摄像头共用电脑 USB。**红线：降压模块先调准 5.0V 并用万用表确认，再接舵机——12V 直冲会烧毁 SG90。**
2. **采购**：~5V 电源不用买了（12V+降压模块替代）；螺丝基本可复用 SG90 自带（仅舵机臂↔摆臂连接处或需 2 颗 M2×6）。仍可能要买：面包板 / 杜邦线（合计约 ¥10~15，见第 2 节）。
3. **摄像头实测尺寸**：摄像头已确认为 **PCB 模组(55×19mm)**，`gimbal.scad` 已按 PCB 重写夹具。还差 3 个值需你量：**镜头筒外径、镜头筒高出板面长度、PCB 厚度**（顺带确认 USB 线出线方向和 LED 柱位置）。量好发我，夹子就能一次成型。

### 📁 关键文件

> **📦 归档工作目录（以后从这里打开/编辑）：`E:\QRS\Project\3esp32_云台_摄像头\`**
> 该目录已含本规划、3D 模型、固件与测试脚本，与下方清单同步。

- 本规划：`E:\QRS\Project\3esp32_云台_摄像头\gimbal-plan.md`（旧会话副本：`D:\AppData\workbuddy\2026-10-18-21-56-42\gimbal-plan.md`）
- 3D 模型源文件：`E:\QRS\Project\3esp32_云台_摄像头\gimbal.scad`（OpenSCAD 参数化，改顶部 pcb_* 即改摄像头夹；已按商品图改为 PCB 模组式）
- 固件：`E:\QRS\Project\3esp32_云台_摄像头\gimbal_firmware\gimbal_firmware.ino`
- 舵机测试脚本：`E:\QRS\Project\3esp32_云台_摄像头\gimbal_firmware\servo_test.py`
- 工作日志（会话目录内）：`D:\AppData\workbuddy\2026-10-18-21-56-42\.workbuddy\memory\2026-10-19.md`
