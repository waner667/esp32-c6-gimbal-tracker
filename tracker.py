#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tracker.py — 人脸追踪闭环：检测 → dx/dy → P/T 命令 → ESP32-C6 → SG90 云台

用法（PowerShell，项目根目录）：
    python tracker.py --port COM10     # 连舵机，闭环追踪（COM 号按设备管理器改）
    python tracker.py                  # 不连串口，仅检测显示 dx/dy（摄像头彩排）
    python tracker.py --once           # 无窗口抓一帧（自检用）

控制律：比例控制（kx/ky 度每像素）+ 死区 + 指数平滑 + 发送节流。
  人脸偏离中心超过死区 → pan/tilt 目标按偏移量比例追过去 → 平滑后节流发给 C6。

按键：
    q / Esc  退出          s  截图            m  镜像开关
    h  回中(90,90)         空格 暂停/恢复追踪
    x  反转 pan 方向        y  反转 tilt 方向
    c  连接/重连串口       0-9 切换摄像头

方向反了不用改代码：转错方向就按 x 或 y，即时反转，下次启动仍默认。
"""

import argparse
import os
import queue
import sys
import threading
import time

import cv2
import numpy as np

try:
    import serial
except ImportError:
    serial = None

SNAP = "tracker_snapshot.png"
TRY_W, TRY_H = 1280, 720
DEAD = set()                      # 打开失败过的索引，避免反复重试卡顿

PAN_MIN, PAN_MAX = 10, 170       # 与固件软件限位一致（2026-10-24 同步：固件 tilt 已放到 10/170）
TILT_MIN, TILT_MAX = 10, 170


# ---------- 摄像头 ----------

def find_model():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (
        os.path.join(here, "models", "face_detection_yunet_2023mar.onnx"),
        os.path.join(os.getcwd(), "models", "face_detection_yunet_2023mar.onnx"),
    ):
        if os.path.isfile(p):
            return p
    print("找不到模型 models/face_detection_yunet_2023mar.onnx")
    sys.exit(1)


def make_detector():
    det = cv2.FaceDetectorYN.create(
        model=find_model(),
        config="",
        input_size=(TRY_W, TRY_H),
        score_threshold=0.6,
        nms_threshold=0.3,
        top_k=10,
    )
    return det


def read_frame(cap, timeout=3.0):
    """带超时的读帧：设备被抢占/卡死时最多等 timeout 秒，绝不无限阻塞主循环。"""
    q = queue.Queue()

    def grab():
        try:
            q.put(cap.read())
        except Exception:
            q.put((False, None))

    t = threading.Thread(target=grab, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return False, None
    return q.get()


def open_camera(index=None):
    """开摄像头：DSHOW→MSMF→ANY 三级 backend；暖机窗口容忍 USB 摄像头的启动黑帧。"""
    indices = [index] if index is not None else range(6)
    for i in indices:
        if i in DEAD and index is None:
            continue
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            cap = cv2.VideoCapture(i, backend)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, TRY_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, TRY_H)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            ok, frame = read_frame(cap)
            if ok and frame is not None:
                # 暖机：USB 摄像头 set 分辨率后前若干帧可能全黑（传感器收敛），
                # 60 帧 / 约 6 秒内等到有效画面都算正常；超时才判"真黑"。
                warm = 0
                while ok and frame is not None and frame.mean() < 8 and warm < 60:
                    ok, frame = read_frame(cap)
                    warm += 1
                if ok and frame is not None and frame.mean() >= 8:
                    DEAD.discard(i)
                    return cap, i, backend
                if ok and frame is not None:
                    print(f"#{i} 暖机 6 秒仍全黑（镜头盖？被挡？），跳过")
                    cap.release()
                    break          # 黑是设备本身的问题，换 backend 没用，直接下一个索引
            cap.release()
    if index is not None:
        DEAD.add(index)
    return None, None, None


def describe(cap, i, backend):
    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    return f"摄像头 #{i} {int(w)}x{int(h)} backend={'DSHOW' if backend == cv2.CAP_DSHOW else 'MSMF' if backend == cv2.CAP_MSMF else 'ANY'}"


def detect_faces(detector, frame):
    h, w = frame.shape[:2]
    detector.setInputSize((w, h))
    _, faces = detector.detect(frame)
    if faces is None:
        return []
    return faces


# ---------- 串口链路 ----------

class ServoLink:
    """C6 串口：发 P/T 命令，后台线程读回显（OK/ERR）。"""

    def __init__(self, port, baud=115200):
        self.port = port
        self.baud = baud
        self.ser = None
        self.ok = False
        self.connect()

    def connect(self):
        if serial is None:
            print("[串口] pyserial 未安装，降级为仅检测模式")
            return False
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            self.ok = True
            print(f"[串口] 已连接 {self.port} @ {self.baud}")
            threading.Thread(target=self._reader, daemon=True).start()
            return True
        except Exception as e:
            print(f"[串口] 连接 {self.port} 失败：{e}（继续仅检测模式，按 c 重试）")
            self.ok = False
            return False

    def _reader(self):
        while self.ok and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode(errors="replace").strip()
                if line:
                    print(f"[C6] {line}")
            except Exception:
                break

    def send(self, pan, tilt):
        if not self.ok or not self.ser or not self.ser.is_open:
            return False
        try:
            self.ser.write(f"P{int(round(pan))},T{int(round(tilt))}\n".encode())
            return True
        except Exception:
            self.ok = False
            print("[串口] 发送失败，链路断开，按 c 重连")
            return False

    def close(self):
        self.ok = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass


# ---------- 主循环 ----------

def pick_target(faces, cx, cy):
    """多张脸时选最靠近画面中心的（当前最可能的主角）。"""
    best = None
    for f in faces:
        fx, fy, fw, fh = f[:4]
        fcx, fcy = fx + fw / 2, fy + fh / 2
        d = ((fcx - cx) ** 2 + (fcy - cy) ** 2) ** 0.5
        if best is None or d < best[0]:
            best = (d, fcx, fcy, fw, fh)
    return best


def draw_hud(frame, faces, target, dx, dy, cx, cy, dead_x, dead_y, st):
    # 死区框 + 中心十字（偏移小于死区不追，防抖）
    cv2.rectangle(frame, (cx - dead_x, cy - dead_y), (cx + dead_x, cy + dead_y), (0, 200, 255), 1)
    cv2.line(frame, (cx - 12, cy), (cx + 12, cy), (0, 200, 255), 1)
    cv2.line(frame, (cx, cy - 12), (cx, cy + 12), (0, 200, 255), 1)
    for f in faces:
        x, y, fw, fh = [int(v) for v in f[:4]]
        cv2.rectangle(frame, (x, y), (x + fw, y + fh), (150, 150, 150), 1)
    if target is not None:
        _, fcx, fcy, fw, fh = target
        x, y = int(fcx - fw / 2), int(fcy - fh / 2)
        cv2.rectangle(frame, (x, y), (int(x + fw), int(y + fh)), (0, 200, 0), 2)
        cv2.circle(frame, (int(fcx), int(fcy)), 4, (0, 0, 255), -1)
        cv2.line(frame, (cx, cy), (int(fcx), int(fcy)), (0, 200, 0), 1)
    lines = [
        f"FPS {st['fps']:.0f}  cam #{st['idx']}  faces {len(faces)}",
        f"dx {('%d' % dx) if dx is not None else '--'}  dy {('%d' % dy) if dy is not None else '--'}  (dead {dead_x}/{dead_y})",
        f"pan tgt {st['pan_tgt']:.0f} -> cur {st['pan_cur']:.0f}   tilt tgt {st['tilt_tgt']:.0f} -> cur {st['tilt_cur']:.0f}",
        f"servo {st['servo']}  {'TRACK' if st['tracking'] else 'PAUSE'}  inv p{st['invp']:+d} t{st['invt']:+d}",
    ]
    for i, ln in enumerate(lines):
        cv2.putText(frame, ln, (10, 24 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 30, 30), 1, cv2.LINE_AA)


def live(args):
    cap, idx, be = open_camera(args.camera)
    if cap is None:
        print("找不到可用摄像头（被微信/腾讯会议占用？）")
        sys.exit(1)
    print(describe(cap, idx, be))
    detector = make_detector()

    # 连接失败也保留 link 对象：HUD 才能显示「COM10·未连上」。置 None 会显示成 OFF，
    # 分不清「没给 --port」和「给了但连不上」——2026-10-24 实测这个歧义坑过人。
    # 发送门用 link.ok 把关，不会往死链路发命令。
    link = ServoLink(args.port, args.baud) if args.port else None
    if link is not None and link.ok:
        # 启动自检：立刻发一条回中命令。控制台紧跟的 [C6] OK pan=90 tilt=90 就是链路证据，
        # 同时舵机会 visibly 动一下到中位——一眼确认「真的连上了」。
        link.send(90, 90)
        time.sleep(0.3)
        print("[自检] 已发 P90,T90 —— 上面那行 [C6] OK 就是链路证据；"
              "舵机应刚才动了一下到中位")

    mirror = True
    tracking = True
    invert_pan = -1 if args.invert_pan else 1
    invert_tilt = -1 if args.invert_tilt else 1

    pan_cur = tilt_cur = 90.0
    pan_tgt = tilt_tgt = 90.0
    sent_pan, sent_tilt = -1.0, -1.0
    last_send_t = 0.0
    last_face_t = None
    fps, prev_t = 0.0, time.time()
    prev_bytes, frozen, last_bytes_t = None, 0, time.time()

    win = "tracker  q quit / h home / space pause / x,y invert / c serial"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while True:
        ok, frame = read_frame(cap)
        if not ok or frame is None:
            print("读帧失败/超时，正在重开摄像头…")
            cap.release()
            cap, idx, be = open_camera()
            if cap is None:
                break
            print(describe(cap, idx, be))
            prev_bytes, frozen, last_bytes_t = None, 0, time.time()
            continue
        if mirror:
            frame = cv2.flip(frame, 1)
        now = time.time()
        fps = 0.9 * fps + 0.1 / max(now - prev_t, 1e-3)
        prev_t = now

        # 假冻结检测：画面连续 4 秒逐字节不变（驱动吐陈旧帧）→ 重开
        b = frame.tobytes()
        if b == prev_bytes:
            frozen += 1
            if frozen > 120 and now - last_bytes_t > 4:
                print("画面疑似冻结，正在重开摄像头…")
                cap.release()
                cap, idx, be = open_camera()
                if cap is None:
                    break
                print(describe(cap, idx, be))
                prev_bytes, frozen, last_bytes_t = None, 0, time.time()
                continue
        else:
            prev_bytes, frozen, last_bytes_t = b, 0, now

        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2
        faces = detect_faces(detector, frame)
        target = pick_target(faces, cx, cy)

        dx = dy = None
        if target is not None and tracking:
            _, fcx, fcy, _, _ = target
            dx, dy = fcx - cx, fcy - cy
            last_face_t = now
            # 比例控制：偏移超死区才追；dy 向下为正 → 脸在上(dy<0)应抬头(tilt 增)
            if abs(dx) > args.dead_x:
                pan_tgt += invert_pan * args.kx * dx
            if abs(dy) > args.dead_y:
                tilt_tgt -= invert_tilt * args.ky * dy
            pan_tgt = min(max(pan_tgt, PAN_MIN), PAN_MAX)
            tilt_tgt = min(max(tilt_tgt, TILT_MIN), TILT_MAX)
        elif args.home_timeout > 0 and last_face_t is not None and now - last_face_t > args.home_timeout:
            pan_tgt = tilt_tgt = 90.0      # 丢脸超时，缓慢回中

        # 指数平滑：目标跳变不直接甩给舵机
        pan_cur += args.alpha * (pan_tgt - pan_cur)
        tilt_cur += args.alpha * (tilt_tgt - tilt_cur)

        # 发送节流：固定间隔 + 变化量阈值，避免刷爆串口打断舵机插值
        if link is not None and link.ok and tracking and now - last_send_t > args.send_interval:
            if abs(pan_cur - sent_pan) > 0.5 or abs(tilt_cur - sent_tilt) > 0.5:
                if link.send(pan_cur, tilt_cur):
                    sent_pan, sent_tilt = pan_cur, tilt_cur
                    last_send_t = now

        draw_hud(frame, faces, target, dx, dy, cx, cy, args.dead_x, args.dead_y, {
            "fps": fps, "idx": idx,
            "pan_tgt": pan_tgt, "pan_cur": pan_cur,
            "tilt_tgt": tilt_tgt, "tilt_cur": tilt_cur,
            "servo": (f"{link.port}{' NOT CONNECTED' if not link.ok else ''}" if link else "OFF"), "tracking": tracking,
            "invp": invert_pan, "invt": invert_tilt,
        })
        cv2.imshow(win, frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("s"):
            cv2.imwrite(SNAP, frame)
            print(f"已截图 {SNAP}")
        elif key == ord("m"):
            mirror = not mirror
            print(f"镜像 {'开' if mirror else '关'}")
        elif key == ord("h"):
            pan_tgt = tilt_tgt = 90.0
            print("回中 90/90")
        elif key == ord(" "):
            tracking = not tracking
            print(f"追踪 {'恢复' if tracking else '暂停'}")
        elif key == ord("x"):
            invert_pan *= -1
            print(f"pan 方向反转（inv={invert_pan:+d}）")
        elif key == ord("y"):
            invert_tilt *= -1
            print(f"tilt 方向反转（inv={invert_tilt:+d}）")
        elif key == ord("c"):
            if link is None and args.port:
                link = ServoLink(args.port, args.baud)
            elif link is not None:
                if link.ok:
                    print("[串口] 已连接，无需重连")
                else:
                    print("[串口] 重连中…")
                    link.connect()
                    print("[串口] 重连成功" if link.ok
                          else "[串口] 重连失败——端口被占？关掉串口监视器/旧 tracker 窗口")
            else:
                print("[串口] 未指定 --port，无串口可连")
        elif ord("0") <= key <= ord("9"):
            n = key - ord("0")
            if n == idx:
                continue
            print(f"正在切换到 #{n}…")
            new_cap, ni, nbe = open_camera(n)
            if new_cap is not None:
                cap.release()
                cap, idx, be = new_cap, ni, nbe
                print(describe(cap, idx, be))
                prev_bytes, frozen, last_bytes_t = None, 0, time.time()
            else:
                print(f"打不开 #{n}，继续用当前 #{idx}")

    cap.release()
    cv2.destroyAllWindows()
    if link is not None:
        link.close()


def once(args):
    cap, idx, be = open_camera(args.camera)
    if cap is None:
        print("找不到可用摄像头")
        sys.exit(1)
    detector = make_detector()
    ok, frame = read_frame(cap)
    if ok and frame is not None:
        if args.mirror:
            frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        cx, cy = w // 2, h // 2
        faces = detect_faces(detector, frame)
        target = pick_target(faces, cx, cy)
        print(describe(cap, idx, be), f"faces={len(faces)}")
        if target is not None:
            _, fcx, fcy, _, _ = target
            print(f"target dx={fcx - cx:+.0f} dy={fcy - cy:+.0f}  →  pan_tgt 增量 {0.06 * (fcx - cx):+.1f}°  tilt_tgt 增量 {-0.05 * (fcy - cy):+.1f}°")
        else:
            print("本帧无人脸")
        for f in faces:
            x, y, fw, fh = [int(v) for v in f[:4]]
            cv2.rectangle(frame, (x, y), (x + fw, y + fh), (0, 200, 0), 2)
        cv2.imwrite(SNAP, frame)
        print(f"已存 {SNAP}")
    cap.release()


def main():
    ap = argparse.ArgumentParser(description="人脸追踪闭环：OpenCV 检测 → C6 → SG90 云台")
    ap.add_argument("--port", default=None, help="C6 串口号，如 COM10；不给则仅检测不控制舵机")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--kx", type=float, default=0.06, help="pan 比例增益（度/像素），越大追得越猛")
    ap.add_argument("--ky", type=float, default=0.05, help="tilt 比例增益（度/像素）")
    ap.add_argument("--dead-x", type=int, default=45, help="pan 死区（像素），小于此值不追")
    ap.add_argument("--dead-y", type=int, default=35, help="tilt 死区（像素）")
    ap.add_argument("--alpha", type=float, default=0.25, help="平滑系数 0~1，越小越稳、越慢")
    ap.add_argument("--send-interval", type=float, default=0.08, help="发命令最小间隔（秒）")
    ap.add_argument("--home-timeout", type=float, default=3.0, help="丢脸几秒后回中，0=不回中")
    ap.add_argument("--invert-pan", action="store_true", help="pan 方向反转（转反了用这个或运行时按 x）")
    ap.add_argument("--invert-tilt", action="store_true", help="tilt 方向反转")
    ap.add_argument("--camera", type=int, default=None, help="指定摄像头索引，默认自动挑")
    ap.add_argument("--no-mirror", dest="mirror", action="store_false", help="关镜像（默认开）")
    ap.add_argument("--once", action="store_true", help="无窗口抓一帧自检")
    args = ap.parse_args()
    if args.once:
        once(args)
    else:
        live(args)


if __name__ == "__main__":
    main()
