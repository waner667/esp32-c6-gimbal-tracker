# servo_test.py
# 路线 A 舵机点亮验证（纯串口发角度，不接摄像头）
# 用法：pip install pyserial
#       python servo_test.py COM3        # 端口按设备管理器实际改
# 指令：输入 "90 45" 表示 P90 T45；输入 H 回中；输入 q 退出
import serial, time, sys

port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
ser = serial.Serial(port, 115200, timeout=0.2)
time.sleep(2)
print(f"已连接 {port}。输入 '90 45' 控角度，'H' 回中，'q' 退出")
try:
    while True:
        s = input("> ").strip()
        if s.lower() == 'q':
            break
        if s.upper() == 'H':
            ser.write(b"H\n")
            continue
        try:
            p, t = s.split()
            ser.write(f"P{int(p)},T{int(t)}\n".encode())
        except Exception:
            print("格式: 90 45")
finally:
    ser.close()
