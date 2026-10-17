#!/usr/bin/env python3
"""解析裁判系统串口抓包，统计 DB9 上到底跑了哪些命令码。

用法:
    python tools/parse_capture.py capture.bin
    python tools/parse_capture.py capture.bin --verbose
    python tools/parse_capture.py capture.bin --baud 921600   # 仅记录用

capture.bin 是串口助手保存的原始字节文件（不是十六进制文本）。
"""

import argparse
import collections
import sys

# Windows 控制台默认 GBK，中文和箭头会直接抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 帧结构（协议 V2.0.0 §1.1 表 1-2/1-3/1-4）
SOF = 0xA5
HEADER_LEN = 5      # SOF(1) + data_length(2) + seq(1) + header CRC8(1)
CMD_ID_LEN = 2
TAIL_LEN = 2        # 整包 CRC16

# 命令码 → (说明, 所属链路, 数据段长度)。摘自表 1-5。
KNOWN = {
    0x0001: ("比赛状态数据", "常规链路", 11),
    0x0002: ("比赛结果数据", "常规链路", 1),
    0x0003: ("机器人血量数据", "常规链路", 20),
    0x0101: ("场地事件数据", "常规链路", 4),
    0x0104: ("裁判警告数据", "常规链路", 3),
    0x0105: ("飞镖发射相关数据", "常规链路", 3),
    0x0201: ("机器人性能体系数据", "常规链路", 17),
    0x0202: ("底盘缓冲能量/射击热量", "常规链路", 14),
    0x0203: ("机器人位置数据", "常规链路", 16),
    0x0204: ("机器人增益和底盘能量", "常规链路", 8),
    0x0206: ("伤害状态数据", "常规链路", 1),
    0x0207: ("实时射击数据", "常规链路", 7),
    0x0208: ("允许发弹量与剩余金币", "常规链路", 8),
    0x0209: ("RFID 模块状态", "常规链路", 5),
    0x020A: ("飞镖选手端指令数据", "常规链路", 6),
    0x020B: ("地面机器人位置数据", "常规链路", 40),
    0x020C: ("雷达标记进度数据", "常规链路", 2),
    0x020D: ("哨兵自主决策信息同步", "常规链路", 14),
    0x020E: ("雷达自主决策信息同步", "常规链路", 1),
    0x0301: ("机器人交互数据", "常规链路", 118),
    0x0302: ("自定义控制器→机器人 交互数据", "图传链路", 30),
    0x0303: ("选手端小地图交互数据", "常规链路", 15),
    0x0305: ("选手端小地图接收雷达数据", "常规链路", 48),
    0x0306: ("自定义控制器↔选手端（键鼠）", "非链路", 8),
    0x0307: ("选手端小地图接收路径数据", "常规链路", 103),
    0x0308: ("选手端小地图接收机器人数据", "常规链路", 34),
    0x0309: ("机器人→自定义控制器 数据", "图传链路", 30),
    0x0310: ("机器人→自定义客户端 数据", "图传链路", 300),
    0x0311: ("自定义客户端→机器人 指令", "图传链路", 30),
    0x0A01: ("对方机器人位置", "雷达无线链路", 24),
    0x0A02: ("对方机器人血量", "雷达无线链路", 12),
    0x0A03: ("对方机器人剩余发弹量", "雷达无线链路", 10),
    0x0A04: ("对方队伍宏观状态", "雷达无线链路", 8),
    0x0A05: ("对方机器人增益效果", "雷达无线链路", 41),
}


def crc8(data, crc=0xFF):
    """帧头校验。多项式 x^8+x^5+x^4+1（反射形式 0x8C），初值 0xFF。"""
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc


def crc16(data, crc=0xFFFF):
    """整包校验。反射多项式 0xA001，初值 0xFFFF，小端追加。"""
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def parse(buf):
    """在字节流里同步帧头，返回 (帧列表, 无法解析的字节数)。"""
    frames = []
    pos = 0
    junk = 0
    while pos < len(buf):
        idx = buf.find(bytes([SOF]), pos)
        if idx < 0:
            junk += len(buf) - pos
            break
        junk += idx - pos
        if idx + HEADER_LEN > len(buf):
            junk += len(buf) - idx
            break

        header = buf[idx:idx + HEADER_LEN]
        data_len = header[1] | (header[2] << 8)
        # data_length 明显不合理就当作假帧头，从下一字节重新同步
        if data_len == 0 or data_len > 1024:
            pos = idx + 1
            junk += 1
            continue

        total = HEADER_LEN + CMD_ID_LEN + data_len + TAIL_LEN
        if idx + total > len(buf):
            junk += len(buf) - idx
            break

        frame = buf[idx:idx + total]
        head_ok = crc8(frame[0:4]) == frame[4]
        pkt = frame[0:HEADER_LEN + CMD_ID_LEN + data_len]
        want = frame[HEADER_LEN + CMD_ID_LEN + data_len] | (
            frame[HEADER_LEN + CMD_ID_LEN + data_len + 1] << 8)
        pkt_ok = crc16(pkt) == want
        cmd_id = frame[5] | (frame[6] << 8)

        frames.append({
            "offset": idx,
            "cmd_id": cmd_id,
            "seq": header[3],
            "data_len": data_len,
            "head_ok": head_ok,
            "crc_ok": pkt_ok,
            "payload": frame[HEADER_LEN + CMD_ID_LEN:HEADER_LEN + CMD_ID_LEN + data_len],
        })
        pos = idx + total
    return frames, junk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--verbose", "-v", action="store_true", help="逐帧打印")
    ap.add_argument("--baud", type=int, default=115200, help="仅用于显示")
    args = ap.parse_args()

    with open(args.capture, "rb") as fh:
        buf = fh.read()

    frames, junk = parse(buf)
    if not frames:
        print("没解析出任何帧。检查波特率是否正确、DB9 的 TX/RX 有没有接反。")
        sys.exit(1)

    by_cmd = collections.Counter()
    by_link = collections.Counter()
    bad_crc = 0
    seq_seen = {}

    for fr in frames:
        by_cmd[fr["cmd_id"]] += 1
        name, link, _ = KNOWN.get(fr["cmd_id"], ("未知命令码", "未知", None))
        by_link[link] += 1
        if not (fr["head_ok"] and fr["crc_ok"]):
            bad_crc += 1
        seq_seen.setdefault(fr["cmd_id"], set()).add(fr["seq"])

    secs = len(buf) / (args.baud / 10.0) if args.baud else 0
    print(f"抓包 {len(buf)} 字节（{args.baud} 8N1 下约 {secs:.1f} 秒）")
    print(f"解析出 {len(frames)} 帧，CRC 错误 {bad_crc} 帧"
          f"（{bad_crc / len(frames) * 100:.2f}%），无法同步的字节 {junk}")
    print()
    print("按链路分布：")
    for link, cnt in by_link.most_common():
        print(f"  {link:<12} {cnt:>7}  {cnt / len(frames) * 100:5.1f}%")
    print()
    print("命令码直方图：")
    for cmd_id, cnt in by_cmd.most_common():
        name, link, declared = KNOWN.get(cmd_id, ("未知命令码", "?", None))
        got = next(f["data_len"] for f in frames if f["cmd_id"] == cmd_id)
        flag = "" if declared is None or declared == got else f"  ⚠ 长度{got}≠声明{declared}"
        print(f"  0x{cmd_id:04X}  {cnt:>7}  {link:<10} {name}{flag}")
        if args.verbose:
            print(f"          seq 取值 {sorted(seq_seen[cmd_id])[:12]}{' ...' if len(seq_seen[cmd_id]) > 12 else ''}")

    video = sum(cnt for cid, cnt in by_cmd.items() if KNOWN.get(cid, ("", "未知"))[1] == "图传链路")
    print()
    print("结论提示：")
    if video == 0:
        print("  ✗ 没看到图传链路命令（0x0302/0x0309/0x0310/0x0311）")
        print("    → 这个 DB9 口输出的不是图传链路数据，桥接板要做的是筛选/改写，不是纯透传")
    else:
        print(f"  ✓ 看到 {video} 帧图传链路数据")
        if video < len(frames):
            print(f"    但其余 {len(frames) - video} 帧属于别的链路")
            print("    → 桥接板必须按 cmd_id 过滤，只把图传链路的帧转发给机器人")
        else:
            print("    且全部帧都属于图传链路 → 可以做纯字节透传，固件最简单")


if __name__ == "__main__":
    main()
