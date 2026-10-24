# verify_powerup.py —— 云台电源恢复 · 上电验收向导
#
# 用途：外部 5V 电源接好后，一键走完「servo-status.md 第 3 节」的验收 checklist，
#       每步都有明确判据，不靠猜。
#
# 用法：
#   C:\Users\a\.workbuddy\binaries\python\versions\3.13.12\python.exe verify_powerup.py
#   （不带参数会自动扫描所有 COM 口，找回 READY 的那个；也可手动指定 verify_powerup.py COM10）
#
# 流程：
#   S0 找板子     → 扫 COM 口，等 "READY pan=GPIO10 tilt=GPIO11 attach=a,b"
#   S1 attach 检查 → attach 必须是 1,1；出现 0 说明 PWM 没挂上（见排障）
#   S2 归中       → 发 H，等 "OK center"（两个舵机应同时抬到 90°）
#   S3 pan 测试   → 发 P120,T90，等回显；问你"底座舵机转了吗？"
#   S4 tilt 测试  → 发 P90,T60，等回显；问你"顶部舵机转了吗？"
#   S5 极限行程   → 发 P10,T20 → P170,T110，看是否到限位（软件限位）
#   S6 回中收尾   → 发 H，打印验收报告
#
# 判据速查（与 wiring-guide.md 第 4 节对应）：
#   舵机完全不动+无声 → 查共地（电源 GND ↔ C6 GND）
#   回显正常但不动   → 橙线插错脚（重点 GPIO12/13，2026-10-20 实际翻车点）
#   嗡嗡响/抖动      → 供电不足或纹波，输出端并 470µF
#   C6 反复重启      → 舵机从 C6 取电了，舵机只认降压模块输出
#
# ==================== LEDC 版固件新增（2026-10-22） ====================
# 如果烧的是 gimbal_firmware_ledc/gimbal_firmware_ledc.ino（ESP32Servo 在 C6 上
# attach 成功但无波形输出时的手写 LEDC 替代版），本脚本会自动识别并多跑两步：
#   S2b PWM 自检  → 发 PWM，解析 us/duty/平均电压，直接判断波形有没有真的出来
#   S3b 万用表引导 → 发 TEST，固件扫 5 档脉宽，脚本打印每档期望平均电压
# 50Hz/3.3V 的 PWM，万用表直流档读到的是平均电压，与脉宽成正比：
#   1000us→0.165V  1250us→0.206V  1500us→0.248V  1750us→0.289V  2000us→0.330V
#   读到 0V = 固件没输出；读到 0.16~0.33V = 波形正常，问题在舵机侧或共地。

import serial, time, sys

BAUD = 115200
WATCH = 2.5      # 每步等回显的秒数
PY = sys.executable or "python"

SEEN = []        # 一路上见过的所有串口行，用来识别固件版本

def is_ledc_fw():
    return any("BOOT LEDC" in l for l in SEEN)

def list_ports():
    try:
        import serial.tools.list_ports
        return [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        return []

def wait_line(ser, want, timeout):
    """在 timeout 秒内等一行包含 want 的串口输出；返回该行或 None"""
    t0 = time.time()
    buf = ""
    while time.time() - t0 < timeout:
        n = ser.in_waiting
        if n:
            buf += ser.read(n).decode("utf8", "ignore")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if line:
                    print("      ←", line)
                    SEEN.append(line)
                    if want in line:
                        return line
        time.sleep(0.02)
    return None

def ask_yes(q):
    try:
        r = input(f"      ? {q} [y/N] ").strip().lower()
    except EOFError:
        r = ""
    return r in ("y", "yes", "是", "转", "动了")

def banner(step, title):
    print(f"\n{'─'*62}\n[{step}] {title}\n{'─'*62}")

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else None
    print("=" * 62)
    print("  云台上电验收向导  ·  电源恢复后 10 分钟收尾")
    print("=" * 62)
    print("⚠️  开始前确认：舵机红/棕已接外部 5V、橙线已接 GPIO10/11、")
    print("    电源 GND 已接 C6 GND 排针（共地，唯一不能省的线）。\n")

    # ---------- S0 找板子 ----------
    if not port:
        cands = list_ports()
        print(f"S0 扫描到 COM 口: {cands or '（空，检查 USB 线/驱动）'}")
        for c in cands:
            try:
                ser = serial.Serial(c, BAUD, timeout=0.2)
            except Exception as e:
                print(f"    {c}: 打不开（{e}）")
                continue
            time.sleep(1.5)
            ser.write(b"H\n")
            line = wait_line(ser, "READY", 2.0)
            if line:
                port = c
                break
            ser.close()
        if not port:
            print("\n❌ 没找到回 READY 的板子。检查：")
            print("   - USB 线接的是 C6 的 **USB-to-UART 口**（带桥接芯片那个），不是原生 USB 口")
            print("   - 设备管理器里端口号是多少，直接 python verify_powerup.py COMx")
            print("   - Arduino IDE 里开发板是否选 ESP32C6 Dev Module、固件是否已烧录")
            return
    ser = serial.Serial(port, BAUD, timeout=0.2)
    time.sleep(1.5)

    # ---------- S1 READY / attach ----------
    banner("S1", "等 READY，检查 PWM 挂载状态")
    line = wait_line(ser, "READY", 6.0)
    if not line:
        ser.write(b"\n")
        line = wait_line(ser, "READY", 4.0)
    if not line:
        print("❌ 6 秒没等到 READY。按 C6 的 RST 键，或重新烧录固件。")
        return
    attach_ok = True
    if "attach=" in line:
        a, b = line.split("attach=")[-1].strip().split(",")[:2]
        print(f"\n   attach={a},{b}")
        if a != "1" or b != "1":
            attach_ok = False
            print("   ⚠️ attach 不是 1,1 → PWM 没挂上 GPIO10/11。")
            print("      怀疑橙线没插好/插到了 strapping 或 USB 脚（GPIO12/13）。")
            print("      继续往下测也无妨——如果舵机完全不动，就是这个原因。")
    print("   ✅ 板子在线。" if attach_ok else "   ⚠️ 继续测，但先记下 attach 异常。")

    ledc = is_ledc_fw()
    if ledc:
        print("\n   识别到：**LEDC 手写版固件**（gimbal_firmware_ledc.ino）")
        print("   ESP32Servo 在 C6 上 attach 成功但无波形输出的已知坑，换底层 driver/ledc.h 绕开")
    else:
        print("\n   识别到：ESP32Servo 版固件（gimbal_firmware.ino）")
        print("   ⚠️ 如果后面 pan/tilt 回显正常但舵机不转，请改烧 LEDC 版：")
        print("      gimbal_firmware_ledc/gimbal_firmware_ledc.ino")

    # ---------- S1b PWM 自检（仅 LEDC 版固件支持） ----------
    pwm_ok = None
    if ledc:
        banner("S1b", "PWM 输出自检：发 PWM，读回 duty 和平均电压")
        ser.write(b"PWM\n")
        got = []
        for _ in range(6):
            l = wait_line(ser, "PWM", 0.6)
            if l and l.startswith("PWM"):
                got.append(l)
            if len(got) >= 2:
                break
        for g in got:
            print("   ", g)
        if not got:
            print("   ❌ 没等到 PWM 回显（这一版固件才支持，换版后重试）")
        else:
            # 解析 "PWM pan  gpio=10 us=1500 duty=4915 pct=7.5%  (avg 0.248V)"
            volts = []
            for g in got:
                if "avg" in g:
                    try:
                        volts.append(float(g.split("avg")[1].strip().rstrip("V)").strip()))
                    except Exception:
                        pass
            if volts:
                print(f"\n   读到 pan 平均电压 {volts[0]:.3f}V")
                if volts[0] < 0.02:
                    pwm_ok = False
                    print("   ❌ ≈0V → **PWM 根本没输出**。固件/引脚/烧录问题，不是舵机问题。")
                    print("      ① 确认烧的是 gimbal_firmware_ledc.ino（文件夹也要对应）")
                    print("      ② Arduino IDE 开发板选 ESP32C6 Dev Module")
                    print("      ③ 换引脚试试：把 PAN_PIN/TILT_PIN 改成 8/9 之类，重烧")
                elif 0.15 <= volts[0] <= 0.36:
                    pwm_ok = True
                    print("   ✅ 0.15~0.36V 区间 → **PWM 波形正常输出**！舵机不动的原因在舵机侧。")
                    print("      下一步查共地：万用表蜂鸣档测 舵机棕 ↔ C6 GND 排针 通不通")
                else:
                    pwm_ok = None
                    print(f"   ⚠️ 电压不在预期区间（1000us→0.165V / 2000us→0.330V）。")
                    print("      发 TEST，固件扫 5 档脉宽，万用表直流档测 GPIO10 对 GND 跟着看。")

    # ---------- S2 归中 ----------
    banner("S2", "归中（两个舵机都应抬到 90°）")
    ser.write(b"H\n")
    ok = wait_line(ser, "OK center", WATCH)
    time.sleep(1.5)
    if ok:
        print("   ✅ 回显正常。两个舵机现在应该是 90° 水平位。")

    # ---------- S3 pan ----------
    banner("S3", "pan 测试：发 P120,T90（底座舵机应转到 120°）")
    ser.write(b"P120,T90\n")
    ok = wait_line(ser, "OK pan=120", WATCH)
    time.sleep(2.0)
    if ok:
        moved = ask_yes("底座舵机转了吗？（顺时针/逆时针都算）")
        print("   ✅ pan 通！" if moved else "   ❌ pan 回显正常但没动 → 见下方排障")
        pan_ok = moved
    else:
        print("   ❌ 没等到回显，串口链路有问题")
        pan_ok = False

    # ---------- S4 tilt ----------
    banner("S4", "tilt 测试：发 P90,T60（顶部舵机应转到 60°）")
    ser.write(b"P90,T60\n")
    ok = wait_line(ser, "OK pan=90 tilt=60", WATCH)
    time.sleep(2.0)
    if ok:
        moved = ask_yes("顶部舵机转了吗？")
        print("   ✅ tilt 通！" if moved else "   ❌ tilt 回显正常但没动 → 见下方排障")
        tilt_ok = moved
    else:
        print("   ❌ 没等到回显")
        tilt_ok = False

    # ---------- S5 极限行程 ----------
    banner("S5", "极限行程：P10,T20 → P170,T110（应平滑走到软件限位，不卡不抖）")
    ser.write(b"P10,T20\n")
    wait_line(ser, "OK pan=10", WATCH)
    time.sleep(2.5)
    print("   发 P170,T110 ...")
    ser.write(b"P170,T110\n")
    wait_line(ser, "OK pan=170", WATCH)
    time.sleep(2.5)
    jitter = ask_yes("全程有没有卡顿/嗡嗡响/抖动？")
    if jitter:
        print("   ⚠️ 有异响 → 供电电流余量不足或纹波，输出端并一颗 470µF 电解电容")
    else:
        print("   ✅ 全程平滑。")

    # ---------- S6 回中 + 报告 ----------
    banner("S6", "回中收尾")
    ser.write(b"H\n")
    wait_line(ser, "OK center", WATCH)
    time.sleep(1.5)

    print("\n" + "=" * 62)
    print("  验收报告")
    print("=" * 62)
    print(f"   端口        : {port}")
    print(f"   固件        : {'LEDC 手写版' if ledc else 'ESP32Servo 版'}")
    if pwm_ok is not None:
        print(f"   PWM 输出    : {'✅ 波形正常' if pwm_ok else '❌ 无输出'}")
    print(f"   pan  (底座) : {'✅ 通' if pan_ok else '❌ 不通'}")
    print(f"   tilt (顶部) : {'✅ 通' if tilt_ok else '❌ 不通'}")
    print(f"   极限行程    : {'⚠️ 有异响' if jitter else '✅ 平滑'}")
    if pan_ok and tilt_ok:
        print("\n🎉 双轴联调通过！下一步：")
        print(f"   {PY} tracker.py --port {port}")
        print("   （电脑 YuNet 检测人脸 → 算偏移 → 自动发角度，云台追人）")
        print("\n   遥控也接上的话：遥控器开机，串口应打印 RC LOCK i-BUS")
        print("   然后拨右手柄 ch1(左右)/ch2(上下) 直接控云台。")
    else:
        print("\n排障（按顺序，别跳）：")
        print("   1. 万用表直流档：舵机红↔棕 = 5.0V ？（不到 4.8V 就是电源问题）")
        print("   2. 蜂鸣档：舵机棕 ↔ C6 GND 排针 通不通？（不通=共地漏了）")
        print("   3. 橙线直碰 C6 的 GPIO10 排针（绕过面包板）：转=面包板孔虚/线断")
        print("   4. 橙线是不是插到 GPIO12/13 了？（2026-10-20 翻车点，回显全正常但不转）")
        print("   5. ESP32Servo 版在 C6 上可能 attach 成功但无波形 → 改烧 gimbal_firmware_ledc.ino")
        print("   6. 换引脚：PAN_PIN/TILT_PIN 改成 8/9 之类重烧，把日志发我")
    print("=" * 62)
    ser.close()

if __name__ == "__main__":
    main()
