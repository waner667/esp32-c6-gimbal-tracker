# preflight.py —— tracker 启动前的一键自检
#
# 用途：2026-10-24 凌晨那次「摄像头窗口正常、绿框跟脸走，但云台不动」，
#       根因 100% 在串口链路（口号错 / 端口被占 / 解释器缺 pyserial）。
#       本脚本把这三件事一次问清，不用人猜。
#
# 回答三个问题：
#   1. 有哪些 COM 口？哪些是蓝牙串口噪音，哪个是真 USB 串口？谁打不开（被占/卡死）？
#   2. 哪个口上跑的是云台固件（认启动行 BOOT LEDC / READY，或发 PWM 诱出回显）？
#   3. 串口链路双向通吗（发 PWM，看有没有 avg 回显）？
#
# 用法：
#   C:\Users\a\.workbuddy\binaries\python\versions\3.13.12\python.exe preflight.py
#
# 全部通过后会直接打印下一步该跑的 tracker.py 命令（带真实端口号）。
#
# 2026-10-24 修订记录：
#   - 识别阶段改为「主动发 PWM 诱出回显」：实测开端口不会让 C6 复位重刷启动行，
#     原来只被动读，永远认不出板子。现在 PWM 回显是硬判据，启动行是锦上添花。
#   - 加了 DTR/RTS 手动复位脉冲（ESPRESSIF 经典上电时序），能诱出启动行就一起显示。
#   - 蓝牙串口（hwid 含 BTHENUM）直接标注为噪音并跳过，不再误报
#     「被 Arduino IDE 串口监视器占着」（那是 OSError(22) 信号灯超时，纯噪音）。

import sys
import time

BAUD = 115200
BOOT_WAIT = 3.5        # 开端口 + 复位脉冲后，等 C6 刷启动行的总时长
PULSE_AT = 0.5         # 开端口后多久拉一次手动复位（前 0.5s 留给"开口自带复位"的情况）
ECHO_WAIT = 1.5        # 发命令后等回显的秒数

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("❌ 当前解释器没有 pyserial。")
    print("   请用这个解释器跑：")
    print("   C:\\Users\\a\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe preflight.py")
    sys.exit(2)


def list_ports():
    """返回 [(device, hwid)]。hwid 用来区分真实 USB 串口和蓝牙串口。"""
    try:
        return [(p.device, p.hwid or "") for p in serial.tools.list_ports.comports()]
    except Exception:
        return []


def is_bluetooth(hwid):
    return "BTHENUM" in hwid.upper() or "BLUETOOTH" in hwid.upper()


def read_available(ser):
    """把当前缓冲区的字节读出来，按行返回（不阻塞）"""
    lines = []
    n = ser.in_waiting
    if n:
        chunk = ser.read(n).decode("utf8", "ignore")
        for ln in chunk.split("\n"):
            ln = ln.strip()
            if ln:
                lines.append(ln)
    return lines


def try_reset_pulse(ser):
    """拉一次手动复位：RTS 拉低再松开（EN 脚），诱出启动行。
    自动复位电路没接的话就什么都不会发生，无害。"""
    try:
        ser.dtr = False   # IO0 保持高 = 正常启动（千万别置 True，那是下载模式）
        ser.rts = True    # EN 拉低 = 保持复位
        time.sleep(0.12)
        ser.rts = False   # EN 松开 = 板子开始跑，刷启动行
        return True
    except Exception:
        return False


def probe_port(dev):
    """打开单个口：先等启动行（含手动复位脉冲），再主动发 PWM 诱出回显。
    返回 dict: open / boot / echo / err / identified"""
    res = {"open": False, "boot": [], "echo": [], "err": None, "identified": False}
    try:
        ser = serial.Serial(dev, BAUD, timeout=0.2)
    except Exception as e:
        res["err"] = e
        return res
    try:
        res["open"] = True
        # ① 被动读 + 中途拉一次手动复位（覆盖"开口自带复位"和"不带复位"两种情况）
        t0 = time.time()
        pulsed = False
        while time.time() - t0 < BOOT_WAIT:
            res["boot"] += read_available(ser)
            # 只在固件自己的 READY 行上早退：ROM 日志里有 SPI_FAST_FLASH_BOOT，
            # 用 "BOOT" 判断会提前中断，把后面的 BOOT LEDC/pan/tilt 行丢给 echo 阶段。
            if any("READY" in l for l in res["boot"]):
                break
            if not pulsed and time.time() - t0 > PULSE_AT:
                try_reset_pulse(ser)
                pulsed = True
            time.sleep(0.05)
        # ② 主动发 PWM 诱出回显 —— 这一步才是认板的硬判据
        ser.reset_input_buffer()
        ser.write(b"\n")
        time.sleep(0.05)
        ser.write(b"PWM\n")
        t0 = time.time()
        while time.time() - t0 < ECHO_WAIT:
            res["echo"] += read_available(ser)
            if any(l.startswith("PWM") and "avg" in l for l in res["echo"]):
                break
            time.sleep(0.05)
        # 认板标准：启动行命中，或 PWM 带回显（只有云台固件会回 PWM pan gpio=.. avg ..V）
        res["identified"] = (
            any(("BOOT LEDC" in l) or ("READY pan=GPIO" in l) for l in res["boot"])
            or any(l.startswith("PWM") and "avg" in l for l in res["echo"])
        )
        return res
    finally:
        try:
            ser.close()
        except Exception:
            pass


def main():
    print("=" * 64)
    print("  云台串口预检  ·  tracker 跑之前先跑这个")
    print("=" * 64)

    ports = list_ports()
    if not ports:
        print("\n[1] ❌ 一个 COM 口都没扫到。检查：")
        print("    - USB 线插的是 C6 的 **USB-to-UART 口**（带 CH343 桥接芯片那个，不是原生 USB 口）")
        print("    - 设备管理器里 CH343 设备有没有感叹号（驱动问题）")
        print("    - 换根 USB 线试试")
        return

    usb_ports = [d for d, h in ports if not is_bluetooth(h)]
    bt_ports = [d for d, h in ports if is_bluetooth(h)]
    print(f"\n[1] 扫到 {len(ports)} 个 COM 口：")
    print(f"    真实 USB 串口 {len(usb_ports)} 个: {usb_ports or '（无）'}")
    if bt_ports:
        print(f"    蓝牙串口 {len(bt_ports)} 个: {bt_ports}  ← 设备没连，正常噪音，忽略")

    print("\n[2] 逐个开口认板（发 PWM 诱出回显；认不出启动行是正常的，开口不一定触发复位）")
    board_port = None
    board = None
    for dev, hwid in ports:
        if is_bluetooth(hwid):
            continue  # 蓝牙串口开了只会报"信号灯超时"，纯噪音
        r = probe_port(dev)
        if not r["open"]:
            print(f"    {dev}: ⚠️ 打不开 —— {r['err']}")
            print("       → 被别的程序占着，或端口卡死。按顺序处理：")
            print("          ① 关掉一切串口工具：Arduino IDE 串口监视器、tracker 窗口、其他终端")
            print("          ② 还不行：把 C6 的 USB 线拔掉重插（强制重新枚举，释放卡死的句柄）")
            print("          ③ 还不行：重启 Arduino IDE / 电脑")
            continue
        if r["identified"]:
            print(f"    {dev}: ✅ 是云台固件")
            board_port, board = dev, r
        else:
            print(f"    {dev}: · 开着了，但发了 PWM 没回显 → 不是云台固件（或无响应）")
        for l in r["boot"][:8]:
            print(f"        ← {l}")
        for l in r["echo"][:6]:
            print(f"        ← {l}")

    if not board_port:
        print("\n❌ 没有哪个口在跑云台固件。按顺序查：")
        print("   1. USB 线插的是 C6 的 **USB-to-UART 口**（带 CH343 桥接芯片那个）")
        print("   2. 固件烧进去没有 → 重烧 gimbal_firmware_ledc/gimbal_firmware_ledc.ino")
        print("   3. 按一下 C6 板上的 RST 键，再跑一次本脚本")
        print("   4. 还认不出 → USB 线拔掉重插，再跑")
        print("   5. 烧录时注意：Arduino IDE 串口监视器必须关着，否则上传失败（老坑）")
        return

    # ---------- 汇总 ----------
    # 固件标识可能落在 boot 阶段也可能落在 echo 阶段（启动行到达时间不定），两处都查
    ledc = any("BOOT LEDC" in l for l in board["boot"] + board["echo"])
    limit = ""
    for l in board["boot"] + board["echo"]:
        if "limit=" in l:
            limit = l.split("limit=")[-1].strip()
    echo_ok = any(l.startswith("PWM") and "avg" in l for l in board["echo"])

    volts = []
    for l in board["echo"]:
        if l.startswith("PWM") and "avg" in l:
            try:
                volts.append(float(l.split("avg")[1].strip().rstrip("V)").strip()))
            except Exception:
                pass

    print("\n" + "=" * 64)
    print("  预检通过")
    print("=" * 64)
    print(f"   端口     : {board_port}")
    if board["boot"]:
        print(f"   固件     : {'LEDC 手写版' if ledc else 'ESP32Servo 版（建议改烧 LEDC 版）'}")
    else:
        print("   固件     : PWM 回显确认在跑（没看到启动行：开口不触发复位，属正常；"
              "按 RST 或重烧后会看到）")
    if limit:
        print(f"   限位     : {limit}   （pan/tilt，期望 10..170/10..170）")
    print(f"   串口链路 : {'✅ 双向通' if echo_ok else '⚠️ 存疑'}")
    if volts:
        v = volts[0]
        print(f"   PWM 电压 : pan {v:.3f}V（1500us 期望 ≈0.248V）")
        if v < 0.02:
            print("   ❌ ≈0V → PWM 没输出。固件/引脚/烧录问题。")
            return
        print("   ✅ 在正常区间，波形是真的。")
    print("\n下一步，复制这条跑：")
    print(f'   & "C:\\Users\\a\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe" '
          f'"E:\\QRS\\Project\\3esp32_云台_摄像头\\tracker.py" --port {board_port}')
    print("\n成功的标志：HUD 显示 servo " + board_port + "（不带「未连上」）"
          "，且控制台开始刷 [C6] OK pan=.. tilt=..")
    print("=" * 64)


if __name__ == "__main__":
    main()
