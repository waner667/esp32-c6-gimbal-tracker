# camera_test.py
# USB 摄像头点亮测试 —— 路线 A 前置步骤（只点摄像头，不接舵机）
#
# 用法：
#   python camera_test.py            自动扫描 0~9 号摄像头，开实时窗口
#   python camera_test.py 1          指定 1 号摄像头
#   python camera_test.py --once     无窗口模式：抓 1 帧存 snapshot.png 后退出
#   python camera_test.py --once 1   无窗口模式，指定 1 号
#
# 窗口按键：q / Esc 退出 | s 截图存 snapshot.png | m 镜像开关 | 0-9 切换摄像头
# 依赖：pip install opencv-python
#
# 防呆/防卡死设计（都有 2026-10-20 实测依据）：
#   1) 切换前先 release 旧设备再开新的：两个采集设备同时开着会互相抢占，
#      新设备"能打开、读不到帧"，read() 无限期阻塞，画面冻住
#   2) 读帧带 3 秒超时（独立线程）：设备被微信/腾讯会议等独占时 read() 会阻塞，
#      超时就换设备，主循环不被单次读帧拖死
#   3) 暖机窗口 60 帧/6 秒：USB 摄像头 set 分辨率后传感器要收敛，前若干帧
#      全黑是正常的（实测 #1 第 1 帧亮度 0.0，约 5 帧后爬坡到 120+）。
#      只读 2 帧就判"被挡"会误杀——2026-10-20 这么误判过，别改回去
#   4) 画面连续 4 秒逐字节不变判假冻结（驱动吐陈旧帧），自动重开

import sys
import threading
import time

import cv2

SNAP = "snapshot.png"
TRY_W, TRY_H = 1280, 720
READ_TIMEOUT = 3.0    # 单次读帧超时（秒）
WARM_FRAMES = 60      # 暖机最多读多少帧
WARM_SECONDS = 6.0    # 暖机最多等多少秒
BLACK_MEAN = 8.0      # 平均亮度低于此值视为黑帧
STILL_TIMEOUT = 4.0   # 画面连续不变多久判假冻结（秒）
BLACK_RUN = 30        # 实时流连续多少帧全黑按卡死处理

DEAD = set()  # 确认没有摄像头的索引，自动扫描时跳过


def read_frame(cap, timeout=READ_TIMEOUT):
    """带超时的读帧，返回 (ok, frame)。

    设备被其它程序独占或驱动挂死时，cap.read() 会无限期阻塞——
    这就是"画面卡住、窗口点不动"的元凶。这里放到独立线程里读，
    超时就放弃返回 (False, None)，主循环不被单次读帧拖死。
    """
    box = {}

    def worker():
        try:
            box["res"] = cap.read()
        except Exception as e:  # 设备抽风时 read 也可能抛异常
            box["err"] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return False, None          # 读帧线程卡死了
    if "err" in box:
        return False, None
    return box.get("res", (False, None))


def warm_up(cap):
    """等摄像头吐出第一帧有效画面，返回 (ok, frame, n_black)。

    USB 摄像头 set 分辨率后传感器要重新收敛，前若干帧全黑完全正常：
    2026-10-20 实测 #1(USB) DSHOW 第 1 帧亮度 0.0，约 5 帧后爬到 120+；
    waner 机器上 set 1280x720 后黑帧更多。只读 2 帧就判"被挡"是误杀。
    """
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


def open_camera(index=None):
    # 候选 backend：DSHOW 打开最快；MSMF 高分辨率支持好；ANY 兜底
    global DEAD
    names = {cv2.CAP_DSHOW: "DSHOW", cv2.CAP_MSMF: "MSMF", cv2.CAP_ANY: "ANY"}
    indices = [index] if index is not None else [i for i in range(10) if i not in DEAD]
    for i in indices:
        for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
            cap = cv2.VideoCapture(i, backend)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, TRY_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, TRY_H)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 降延迟
            except Exception:
                pass
            ok, frame, n_black = warm_up(cap)
            if ok:
                DEAD.discard(i)
                return cap, i, backend
            # 暖机超时仍全黑：这个 backend 救不了，释放换下一个
            print(f"#{i} {names.get(backend, backend)} 暖机 {n_black} 帧仍全黑（镜头盖？被挡？），跳过")
            cap.release()
    if index is not None:
        DEAD.add(index)
    return None, None, None


def describe(cap, index, backend):
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    names = {cv2.CAP_DSHOW: "DSHOW", cv2.CAP_MSMF: "MSMF", cv2.CAP_ANY: "ANY"}
    return (f"摄像头 #{index}  backend={names.get(backend, backend)}  "
            f"分辨率={w}x{h}  FPS={fps:.1f}")


def no_camera():
    print("没找到可用摄像头。排查顺序：")
    print("  1) 是否被微信/QQ/其它程序占用（关掉再试）")
    print("  2) Windows 设置 -> 隐私和安全性 -> 摄像头，是否允许桌面应用访问")
    print("  3) 换个 USB 口（优先主板后置 USB，别用无源 HUB）")
    print("  4) 设备管理器里“图像设备/照相机”是否认得到")


def once(index=None):
    cap, i, be = open_camera(index)
    if cap is None:
        no_camera()
        return 1
    ok, frame = read_frame(cap)
    print(describe(cap, i, be))
    if ok and frame is not None:
        cv2.imwrite(SNAP, frame)
        print(f"已抓 1 帧并保存到 {SNAP}（{frame.shape[1]}x{frame.shape[0]}）")
    else:
        print("读取帧失败（设备可能被其它程序独占）")
    cap.release()
    return 0


def switch_to(target, cur_index):
    """切换到 target 号摄像头，返回 (cap, index, backend) 或 (None, None, None)。

    先释放当前设备再开新的——两个采集设备同时开着会互相抢占，
    新设备表现为"能打开、读不到帧"，画面直接冻住。释放由调用方做。
    """
    print(f"切换到 #{target} ...")
    ncap, ni, nbe = open_camera(target)
    if ncap is not None:
        return ncap, ni, nbe
    print(f"打不开 #{target}，尝试恢复原来的 #{cur_index}")
    ncap, ni, nbe = open_camera(cur_index)
    if ncap is not None:
        return ncap, ni, nbe
    print("原摄像头也开不回来了，自动扫描 ...")
    return open_camera(None)


def reopen_same(cap, i):
    """卡死/假冻结后重开当前索引，失败则自动扫描。返回新 cap 或 None。"""
    print(f"#{i} 重开摄像头 ...")
    ncap, ni, nbe = open_camera(i)
    if ncap is not None:
        return ncap, ni, nbe
    print(f"重开 #{i} 失败，自动扫描 ...")
    ncap, ni, nbe = open_camera(None)
    return ncap, ni, nbe


def live(index=None):
    cap, i, be = open_camera(index)
    if cap is None:
        no_camera()
        return 1
    print(describe(cap, i, be))
    print("按键：q/Esc 退出 | s 截图 | m 镜像开关 | 0-9 切换摄像头")
    mirror = True
    t0, n = time.time(), 0
    last_frame = None
    still_since = None
    black_run = 0
    while True:
        ok, frame = read_frame(cap)
        if not ok or frame is None:
            # 读帧超时/失败：设备被抢占或驱动卡死。
            # 注意不 release 卡死的设备（读帧线程还挂在里面），直接另开一个。
            print(f"#{i} 读帧失败/超时（摄像头可能被其它程序抢占了），自动换设备 ...")
            ncap, ni, nbe = open_camera(None)
            if ncap is None:
                print("没有可用摄像头了，退出。先关掉可能占用摄像头的程序（微信/腾讯会议等）再试")
                break
            cap, i, be = ncap, ni, nbe
            print(describe(cap, i, be))
            last_frame, still_since, black_run = None, None, 0
            t0, n = time.time(), 0
            continue

        # 连续全黑：驱动吐黑帧卡死（区别于暖机——暖机在 open 阶段就挡住了）
        if frame.mean() < BLACK_MEAN:
            black_run += 1
            if black_run >= BLACK_RUN:
                print(f"#{i} 连续 {BLACK_RUN} 帧全黑，按卡死处理，重开摄像头 ...")
                ncap, ni, nbe = reopen_same(cap, i)
                if ncap is None:
                    print("没有可用摄像头了，退出")
                    break
                cap, i, be = ncap, ni, nbe
                print(describe(cap, i, be))
                last_frame, still_since, black_run = None, None, 0
                t0, n = time.time(), 0
                continue
        else:
            black_run = 0

        # 假冻结检测：驱动吐陈旧帧时 read() 一直成功但画面逐字节不变
        if (last_frame is not None and last_frame.shape == frame.shape
                and (last_frame == frame).all()):
            if still_since is None:
                still_since = time.time()
            elif time.time() - still_since > STILL_TIMEOUT:
                print(f"#{i} 画面连续 {STILL_TIMEOUT:.0f} 秒无变化，按假冻结处理，重开摄像头 ...")
                ncap, ni, nbe = reopen_same(cap, i)
                if ncap is None:
                    print("重开失败，退出")
                    break
                cap, i, be = ncap, ni, nbe
                print(describe(cap, i, be))
                last_frame, still_since, black_run = None, None, 0
                t0, n = time.time(), 0
                continue
        else:
            still_since = None
        last_frame = frame.copy()

        if mirror:
            frame = cv2.flip(frame, 1)
        n += 1
        if n % 30 == 0:
            fps = n / (time.time() - t0)
            cv2.putText(frame, f"#{i} {fps:.0f}fps", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 180, 0), 2)
        cv2.imshow("gimbal camera", frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord("s"):
            cv2.imwrite(SNAP, frame)
            print(f"已保存 {SNAP}")
        elif key == ord("m"):
            mirror = not mirror
        elif ord("0") <= key <= ord("9"):
            target = key - ord("0")
            if target == i:
                print(f"已经在 #{i} 了")
                continue
            cap.release()  # 先放旧设备，避免双设备抢占把新设备冻住
            ncap, ni, nbe = switch_to(target, i)
            if ncap is None:
                print("所有摄像头都打不开了，退出")
                break
            cap, i, be = ncap, ni, nbe
            print(describe(cap, i, be))
            last_frame, still_since, black_run = None, None, 0
            t0, n = time.time(), 0
    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--once" in args:
        idx = None
        for a in args:
            if a.isdigit():
                idx = int(a)
        sys.exit(once(idx))
    idx = None
    for a in args:
        if a.isdigit():
            idx = int(a)
    sys.exit(live(idx))
