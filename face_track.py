"""face_track.py — 摄像头实时人脸检测 demo（云台跟踪的视觉前置）

用法：
    python face_track.py            # 实时窗口，自动找第一个能出图的摄像头
    python face_track.py --index 1  # 指定 1 号摄像头
    python face_track.py --once     # 无窗口，抓一帧存 face_snapshot.png 后退出

窗口按键：
    q / Esc  退出
    s        截图（带识别框）存 face_snapshot.png
    m        镜像开关（默认开，自拍视角）
    0-9      切换摄像头索引（切不走保持当前画面）

检测到人脸时：绿框 + 置信度 + 框中心相对画面中心的偏移 dx/dy
（dx/dy 就是将来喂给舵机做跟踪的接口量，右/下为正）

检测器：OpenCV YuNet（models/face_detection_yunet_2023mar.onnx，首次运行需已下载）

防呆/防卡死设计（与 camera_test.py 同一套，2026-10-20 实测依据）：
    1) 切换前先 release 旧设备再开新的，否则双设备抢占、read() 阻塞、画面冻住
    2) 读帧带 3 秒超时（独立线程），设备被独占时不拖死主循环
    3) 暖机窗口 60 帧/6 秒：USB 摄像头 set 分辨率后前若干帧全黑是正常的，
       只读 2 帧就判"被挡"会误杀
    4) 实时流连续 30 帧全黑按卡死重开
"""

import argparse
import os
import threading
import time

import cv2

WIN = "face track (q quit, s snap, m mirror, 0-9 switch)"
SNAP = "face_snapshot.png"
MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "models", "face_detection_yunet_2023mar.onnx")
TRY_W, TRY_H = 1280, 720
READ_TIMEOUT = 3.0
WARM_FRAMES = 60
WARM_SECONDS = 6.0
BLACK_MEAN = 8.0
BLACK_RUN = 30

BACKENDS = (("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF), ("ANY", cv2.CAP_ANY))


def read_frame(cap, timeout=READ_TIMEOUT):
    """带超时的读帧，返回 (ok, frame)。设备被独占/驱动卡死时 read() 会
    无限期阻塞（画面冻住的元凶），放独立线程里读，超时即放弃。"""
    box = {}

    def worker():
        try:
            box["res"] = cap.read()
        except Exception as e:
            box["err"] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return False, None
    if "err" in box:
        return False, None
    return box.get("res", (False, None))


def warm_up(cap):
    """等第一帧有效画面，返回 (ok, frame, n_black)。
    USB 摄像头 set 分辨率后传感器收敛期间前若干帧全黑是正常的。"""
    n_black = 0
    t0 = time.time()
    for _ in range(WARM_FRAMES):
        ok, frame = read_frame(cap)
        if not ok or frame is None:
            return False, None, n_black
        if frame.mean() >= BLACK_MEAN:
            return True, frame, n_black
        n_black += 1
        if time.time() - t0 > WARM_SECONDS:
            return False, None, n_black
    return False, None, n_black


def load_detector(w, h):
    if not os.path.isfile(MODEL):
        raise SystemExit(f"缺少模型文件: {MODEL}（从 opencv_zoo 下载 YuNet onnx 放进去）")
    det = cv2.FaceDetectorYN.create(
        model=MODEL, config="", input_size=(w, h),
        score_threshold=0.6, nms_threshold=0.3, top_k=5000)
    if det is None:
        raise SystemExit("FaceDetectorYN 创建失败")
    return det


def describe(cap, idx, backend):
    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    return f"#{idx} backend={backend} {int(w)}x{int(h)}"


def open_camera(index=None):
    """候选 backend：DSHOW 打开最快；MSMF 高分辨率支持好；ANY 兜底。
    暖机 60 帧/6 秒内不出有效画面才判黑（USB 摄像头 set 分辨率后
    前若干帧全黑是正常暖机，2026-10-20 实测）。"""
    indices = [index] if index is not None else range(10)
    for i in indices:
        for bname, backend in BACKENDS:
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
            ok, frame, n_black = warm_up(cap)
            if ok:
                print(describe(cap, i, bname))
                return cap, i, bname
            print(f"跳过 #{i}（{bname}）：暖机 {n_black} 帧仍全黑（镜头盖/被挡?）")
            cap.release()
    return None, None, None


def detect_faces(det, frame):
    """返回 [(x, y, w, h, score)]。YuNet 输出 Nx15：前4=框，最后1=置信度。"""
    h, w = frame.shape[:2]
    det.setInputSize((w, h))
    _, faces = det.detect(frame)
    if faces is None or len(faces) == 0:
        return []
    return [(int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[14])) for f in faces]


def draw_hud(frame, fps, faces, mirror):
    h, w = frame.shape[:2]
    lines = [
        f"FPS {fps:4.1f}  faces {len(faces)}",
        "q quit  s snap  m mirror 0-9 cam",
    ]
    if mirror:
        lines.append("mirror ON")
    for i, t in enumerate(lines):
        cv2.putText(frame, t, (10, 22 + i * 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1, cv2.LINE_AA)
    for (x, y, fw, fh, score) in faces:
        cx, cy = x + fw // 2, y + fh // 2
        cv2.rectangle(frame, (x, y), (x + fw, y + fh), (0, 220, 0), 2)
        cv2.circle(frame, (cx, cy), 3, (0, 0, 220), -1)
        # 相对画面中心的偏移（将来喂舵机的接口量，右/下为正）
        dx, dy = cx - w // 2, cy - h // 2
        cv2.putText(frame, f"{score:.2f} dx{dx:+d} dy{dy:+d}",
                    (x, max(14, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 0), 1, cv2.LINE_AA)
    return frame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, default=None, help="指定摄像头索引")
    ap.add_argument("--once", action="store_true", help="抓一帧后退出")
    args = ap.parse_args()

    cap, idx, backend = open_camera(args.index)
    if cap is None:
        raise SystemExit("没找到可用摄像头（被微信/QQ 占用? 镜头盖?）")

    det = load_detector(TRY_W, TRY_H)
    mirror = True
    dead = set()          # 打不开过的索引，避免反复重试
    fps = 0.0
    t_prev = time.time()
    fps_cnt = 0
    black_run = 0

    if args.once:
        ok, frame = read_frame(cap)
        cap.release()
        if not ok or frame is None:
            raise SystemExit("抓帧失败")
        if mirror:
            frame = cv2.flip(frame, 1)
        faces = detect_faces(det, frame)
        for (x, y, fw, fh, score) in faces:
            cv2.rectangle(frame, (x, y), (x + fw, y + fh), (0, 220, 0), 2)
        h, w = frame.shape[:2]
        cv2.putText(frame, f"faces {len(faces)}", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 1, cv2.LINE_AA)
        cv2.imwrite(SNAP, frame)
        print(f"faces={len(faces)} -> {SNAP} ({w}x{h})")
        return

    print("按键：q/Esc 退出 | s 截图 | m 镜像开关 | 0-9 切换摄像头")
    while True:
        ok, frame = read_frame(cap)
        if not ok or frame is None:
            # 不 release 卡死的设备（读帧线程还挂在里面），直接另开一个
            print(f"#{idx} 读帧失败/超时，自动换设备 ...")
            ncap, ni, nb = open_camera(None)
            if ncap is None:
                print("没有可用摄像头了，退出")
                break
            cap, idx, backend = ncap, ni, nb
            black_run = 0
            continue

        if frame.mean() < BLACK_MEAN:
            black_run += 1
            if black_run >= BLACK_RUN:
                print(f"#{idx} 连续 {BLACK_RUN} 帧全黑，重开摄像头 ...")
                cap.release()
                ncap, ni, nb = open_camera(idx)
                if ncap is None:
                    ncap, ni, nb = open_camera(None)
                if ncap is None:
                    print("没有可用摄像头了，退出")
                    break
                cap, idx, backend = ncap, ni, nb
                black_run = 0
                continue
        else:
            black_run = 0

        if mirror:
            frame = cv2.flip(frame, 1)
        faces = detect_faces(det, frame)

        fps_cnt += 1
        now = time.time()
        if now - t_prev >= 0.5:
            fps = fps_cnt / (now - t_prev)
            t_prev, fps_cnt = now, 0

        draw_hud(frame, fps, faces, mirror)
        cv2.imshow(WIN, frame)

        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("s"):
            cv2.imwrite(SNAP, frame)
            print(f"已保存 {SNAP}")
        elif key == ord("m"):
            mirror = not mirror
        elif ord("0") <= key <= ord("9"):
            new_idx = key - ord("0")
            if new_idx == idx:
                print(f"已经在 #{idx} 了")
                continue
            if new_idx in dead:
                print(f"打不开 #{new_idx}，继续用当前 #{idx}")
                continue
            print(f"切换到 #{new_idx} ...")
            cap.release()               # 先放旧设备，避免双设备抢占冻住
            new_cap, ni, nb = open_camera(new_idx)
            if new_cap is None:
                print(f"打不开 #{new_idx}，尝试恢复原来的 #{idx}")
                dead.add(new_idx)
                new_cap, ni, nb = open_camera(idx)
                if new_cap is None:
                    print("所有摄像头都打不开了，退出")
                    break
            cap, idx, backend = new_cap, ni, nb
            black_run = 0

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
