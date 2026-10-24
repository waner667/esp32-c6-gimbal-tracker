#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# test_servolink.py —— 直接用 tracker.py 自己的 ServoLink 类测串口发送链路
# 不碰摄像头，专门回答：「tracker 的串口代码路径到底通不通」
# 用法：
#   <python> test_servolink.py [COM10]
# 判据：
#   - 打印 [串口] 已连接 + 每条命令回 [C6] OK pan=.. tilt=.. → tracker 串口层没问题
#   - 打印 [串口] 连接 COMx 失败：拒绝访问 → 端口被占（查谁开着：tracker 旧窗口/监视器）
#   - 打印 [串口] pyserial 未安装 → 解释器用错了

import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tracker  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM10"

print("=" * 60)
print(f"  tracker.ServoLink 直连测试  端口={PORT}")
print("=" * 60)

link = tracker.ServoLink(PORT)
print(f"\nlink.ok = {link.ok}")
if not link.ok:
    print("→ connect 失败。如果上面是「拒绝访问」：端口被占，")
    print("  关掉 tracker 旧窗口 / Arduino IDE 串口监视器后重跑本测试。")
    sys.exit(1)

print("\n依次发送 5 条命令（每条间隔 0.6s，盯住舵机看动不动）：")
cmds = [(60, 90), (120, 90), (90, 60), (90, 120), (90, 90)]
all_ok = True
for pan, tilt in cmds:
    ok = link.send(pan, tilt)
    print(f"  send P{pan},T{tilt} -> {'已写入' if ok else '失败'}")
    if not ok:
        all_ok = False
    time.sleep(0.6)

time.sleep(0.5)  # 等回显刷完
print("\n" + "=" * 60)
if all_ok:
    print("结论：tracker 串口层完全正常（连接+发送都通）")
    print("→ 如果刚才舵机动了：问题在你跑 tracker 时的现场（端口被占/按了暂停/脸在死区）")
    print("→ 如果刚才舵机没动：固件或舵机问题（但 preflight 刚验证过 PWM 有输出，"
          "请确认外部 5V 电源开着）")
else:
    print("结论：发送链路有断点，看上面的失败信息")
print("=" * 60)

link.close()
