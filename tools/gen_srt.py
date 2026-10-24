#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成两份 SRT：
  1) srt_en_raw.srt   —— 剪映「识别歌词/字幕」用：从视频音轨原样转写（英）
  2) srt_zh_timeline.srt —— 剪辑后成片用：30秒时间轴上的中文字幕（口播稿）

用法：改下面的 CUTS / LINES 然后重跑
"""
import os

OUT = r"E:\video\小智AI\输出"
os.makedirs(OUT, exist_ok=True)


def ts(sec, sep=","):
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return "%02d:%02d:%02d%s%03d" % (h, m, s, sep, int(round((s - int(s)) * 1000)))


def write(path, cues):
    lines = []
    for i, (a, b, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append("%s --> %s" % (ts(a), ts(b)))
        lines.append(text)
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("wrote", path, len(cues), "cues")


# ---------- 1) 原素材英文字幕（时间戳 = 原视频 82 秒轴） ----------
RAW = [
    (2.6, 5.0, "哈喽小智"),
    (5.4, 7.6, "hello 小智"),
    (8.4, 10.2, "uh um"),
    (10.8, 12.2, "uh um"),
    (14.0, 17.2, "twenty-nine degrees"),
    (20.0, 22.4, "ah ok"),
    (23.4, 26.6, "can you sit down"),
    (44.0, 47.4, "all right lie down now"),
    (47.4, 50.6, "OK 小智 stand up"),
    (53.0, 56.4, "you can have a rest"),
    (59.2, 62.6, "嗯嗯 thank you 小智"),
    (64.8, 69.4, "i raise my left paw for you"),
    (78.6, 81.6, "对小 w take care"),
]
write(os.path.join(OUT, "srt_en_raw.srt"), RAW)


# ---------- 2) 30 秒成片中文字幕（时间戳 = 成片轴） ----------
# 严格对应「剪辑时间表」那一节
ZH = [
    (0.2, 1.9, "我用 ESP32-C6 造了个\nAI 语音助手"),
    (2.2, 4.8, "叫它名字，它就醒了"),
    (5.2, 8.6, "指令 1：坐下"),
    (9.0, 12.6, "指令 2：趴下 → 起立"),
    (13.2, 15.8, "它还能听出语气"),
    (16.1, 20.8, "★ 它居然会抬爪"),
    (21.2, 24.6, "全程 ESP32-C6 + 舵机\n一套代码"),
    (25.0, 29.6, "踩过的坑下期全讲\n评论区扣「舵机」发接线图"),
]
write(os.path.join(OUT, "srt_zh_timeline.srt"), ZH)


# ---------- 3) 口播稿（给配音的人念） ----------
VO = """【0:00-0:05】
这语音助手，是我自己用 ESP32-C6 做的。
叫它名字，它就醒了。

【0:05-0:13】
我说坐下，它就坐下。我说趴下、起立，它都跟着做。
整套动作全靠几个 SG90 舵机，加一块 ESP32-C6 就够了。

【0:13-0:21】
最离谱的是这句——我让它抬个爪，它居然真的抬起来了。

【0:21-0:30】
没有云端 API，没有手机 App，一套代码跑起来的。
踩的坑我下期全讲，评论区扣「舵机」，我把接线图发你。
"""
with open(os.path.join(OUT, "vo_zh_30s.txt"), "w", encoding="utf-8") as f:
    f.write(VO)
print("wrote vo_zh_30s.txt")

print("\n成片轴跳转表（剪映里照这个时间点切）:")
CUTS = [(0.0, 2.0, "静图推近", "IMG_20261017_185345_edit_16811.jpg"),
        (2.0, 5.0, "唤醒", "原 2.6-7.6"),
        (5.0, 9.0, "坐下", "原 23.4-28.5"),
        (9.0, 13.0, "趴下+起立", "原 44.0-50.6"),
        (13.0, 16.0, "致谢", "原 59.2-63.0"),
        (16.0, 21.0, "抬爪★", "原 64.8-70.5 慢放 0.8x"),
        (21.0, 25.0, "定格+清单", "从 24s/48s 里挑动作最明显帧"),
        (25.0, 30.0, "静图收尾", "IMG_20261017_185345_edit_16811.jpg")]
for a, b, what, src in CUTS:
    print("  成片 %4.1f-%4.1f  %-12s  <- %s" % (a, b, what, src))