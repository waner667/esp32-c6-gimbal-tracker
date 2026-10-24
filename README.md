# ESP32-C6 两轴云台 · 项目索引（README）

> 一句话：**ESP32-C6 带两个 SG90 做两轴云台，USB 摄像头坐在云台上。电脑 OpenCV（YuNet）检测人脸 → 算偏移 → 串口发角度 → 舵机追人。也支持遥控器（FS-i6X+A8S / ELRS）拨杆直接控。**
>
> 状态更新：2026-10-24 晚。**追人闭环已跑通**（人动云台跟动，waner 12:13 确认）；灵敏度调优进行中。当日根案：「舵机不动」= 外部 5V 电源未开（USB 只供板子，回显全正常也测不出）。晚间补记：HUD 状态词已全 ASCII 化（中文会被 cv2.putText 渲染成问号）；跑脚本必须用全路径解释器（原因见下文警告）。

---

## 当前状态

| 线 | 状态 | 说明 |
|---|---|---|
| 📷 摄像头 | ✅ 全通 | 内置/USB 双摄切换、防冻死、暖机黑帧不再误判 |
| 👤 人脸检测 | ✅ 全通 | YuNet（opencv5 已无 Haar），模型在 `models/` |
| 🎯 追踪闭环 | ✅ **已跑通** | 人动云台跟动（2026-10-24 12:13 确认）；灵敏度调优中（默认 `kx0.06/ky0.05/alpha0.25/死区45,35`） |
| 🔧 舵机固件 | ✅ 全通 | 串口 `P,T` 协议 + 回显 + 遥控三协议（i-BUS/CRSF/SBUS 自动识别） |
| 🔌 舵机硬件 | ✅ 已点亮 | 现成模型 #2045352 已打印组装、摄像头已固定；tilt 限位实测约 180° 无死挡、固件 `10/170` 已烧录、手动五条命令全过、串口链路预检全绿 |
| 🧊 3D 模型 | ✅ 现成模型 | MakerWorld **#2045352**「Sg90舵机云台修改（仰角限位以及底座）」，圆总改版 SG90 双臂云台：底座延长 + 释放约 45° 仰角 + **电缆导线槽**；22g / 1.3h。自研 `gimbal.scad` 已弃用 |

---

## 文档分工（遇到问题看哪份）

| 文档 | 管什么 | 什么时候查 |
|---|---|---|
| **`open-issues.md`** | 未解决问题清单：打印前必须核对的估测参数、装配待办、已解决存档 | 不知道现在还有什么没做完 / 打印前核对尺寸 |
| **`wiring-guide.md`** | 施工级接线：每根线的去向、上电顺序、故障速查 | 接线/舵机不动/遥控没反应，**只查它** |
| **`servo-status.md`** | 舵机线存档：已验证清单、模块烧毁事故、恢复 checklist、排障时间线 | 想知道"舵机这条线到哪了" |
| **`gimbal-plan.md`** | 总规划：架构、扭矩核算、物料、打印参数、历史 checkpoint | 查背景/查为什么这么设计 |
| **`README.md`** | 本页：索引 + 状态 + 怎么跑 | 不知道从哪下手 |

---

## 代码与运行方式

| 文件 | 是什么 | 怎么跑 |
|---|---|---|
| `gimbal_firmware/gimbal_firmware.ino` | C6 固件【ESP32Servo 版，⚠️ 已废弃勿烧】：串口 `P,T`/`H` + 遥控三协议（GPIO6 收） | 仅存档；ESP32Servo 在 C6 上 attach 成功但无波形，烧这版舵机不转 |
| `gimbal_firmware_ledc/gimbal_firmware_ledc.ino` | C6 固件【LEDC 手写版】：同上，但 PWM 走底层 `driver/ledc.h`，绕开 ESP32Servo 在 C6 上「attach 成功但无波形」的坑。带 `M<us>`/`PWM`/`TEST` 诊断命令 | 舵机不转时烧这版 |
| `gimbal_firmware/verify_powerup.py` | **上电验收向导**：自动找板子→查 attach→归中→pan/tilt→极限行程→回中，出验收报告 | `python verify_powerup.py`（不带参数自动扫 COM 口） |
| `preflight.py` | **串口一键自检**（项目根目录）：列 COM 口并区分 USB/蓝牙噪音 → DTR/RTS 复位脉冲认板 → 发 `PWM` 验双向链路 → 直接打印该跑的 tracker 命令 | `python preflight.py`；串口有任何不对劲先跑它 |
| `gimbal_firmware/servo_test.py` | PC 端角度测试（输入 `90 45` 控角） | `python servo_test.py COM10` |
| `camera_test.py` | 摄像头实时窗口（q 退出/s 截图/m 镜像/0-9 切换） | `python camera_test.py` |
| `face_track.py` | 人脸检测 demo（绿框 + dx/dy 偏移量 HUD） | `python face_track.py` |
| `tracker.py` | **闭环追踪**：检测 → 比例控制+死区 → 自动发令 | `python tracker.py --port COM10`；不带 `--port` 为彩排模式 |
| `models/face_detection_yunet_2023mar.onnx` | YuNet 模型（232KB，已就位） | 不用管，脚本自动加载 |

Python 统一用这个解释器（opencv 5.0 + pyserial 都装在它里面）：

```
C:\Users\a\.workbuddy\binaries\python\versions\3.13.12\python.exe <脚本名>
```

> ⚠️ **不要用裸 `python` 启动**：PowerShell 默认的 python 虽装了 opencv/numpy 但**没装 pyserial**——`tracker.py` 会静默降级成「仅检测模式」（控制台只有一行提示，HUD servo 行显示 `NOT CONNECTED`），摄像头画面正常但舵机完全不受控；`preflight.py` 对缺库有保护会明确报错。2026-10-24 夜实测踩过这个坑。

**固件串口命令速查**：`P120,T90` 控角｜`H` 回中｜`RC=i\|c\|s` 锁协议｜`RC` 查状态｜`RCV` 打 16 通道原始值。
**LEDC 版额外命令**：`M1500` 直接设 pan 脉宽(us)｜`PWM` 看当前 duty/平均电压｜`TEST` 扫 5 档脉宽（万用表直流档测 GPIO10 对 GND：1000us→0.165V / 1500us→0.248V / 2000us→0.330V）。

---

## 引脚定案（面包板只剩一列，都是血泪）

| C6 引脚 | 接什么 |
|---|---|
| GPIO10 | pan 舵机信号（橙） |
| GPIO11 | tilt 舵机信号（橙） |
| GPIO6 | 遥控接收机信号（i-BUS/CRSF/SBUS 单线） |
| GND | 共地（舵机电源 + 遥控接收机，唯一不能省的线） |
| USB-to-UART 口 | 接电脑（供电+串口） |

🚫 不碰：GPIO4/5/8/9/15（strapping 脚）、GPIO12/13（原生 USB DM/DP，翻过车）、GPIO1（32K 晶振）。

---

## 当前卡点与下一步

**卡点**：无硬卡点。**追人闭环已跑通**（2026-10-24 12:13 确认：人动→云台跟动）。舵机硬件 / 固件 / 串口 / 检测四层全通。

**下一步（按顺序）**：

1. **灵敏度调参**（下午第一件事）：先试激进版，找到「不抖的最快组合」后告诉我，固化进 `tracker.py` 默认值：

```
& "C:\Users\a\.workbuddy\binaries\python\versions\3.13.12\python.exe" "E:\QRS\Project\3esp32_云台_摄像头\tracker.py" --port COM10 --kx 0.12 --ky 0.10 --alpha 0.45 --dead-x 20 --dead-y 15
```

判据：HUD 第一行 `FPS`（低于 20 就降摄像头分辨率，改 `tracker.py` 的 `TRY_W/TRY_H`）；第三行 `pan tgt -> cur` 差一大截 = 平滑太慢（调 `--alpha`）；抖/过冲就把 `--alpha` 回调 0.3、增益减半。

2. **三个物理小项**（不挡使用）：pan 舵机核对「插入」安装（作者硬警告）、USB 线留松弛圈、摄像头 FPC 排线扎止点——详见 `open-issues.md` 第二档。

3. **遥控联调**：FS-i6X 开机，串口应打印 `RC LOCK i-BUS`；拨右手柄 ch1/ch2 直接控。

**可选**：`python gimbal_firmware/verify_powerup.py` 自动版全量验收（手动五条已过，备查）。

---

## 许可证

MIT License，见 [LICENSE](LICENSE)。Copyright (c) 2026 waner667
