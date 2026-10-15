"""一次性回填：修正历史告警的 `channelid`（此前误取了 additional.channel_id，实测恒为 0）。

背景：真实通道号在报文的 `additional.device_id`（与设备快照 channels[].device_id 对得上，
例如 device_id=4 ↔ 通道名 "36"）。旧代码取 `additional.channel_id`，导致 alerts.channelid 恒为 0，
预警详情无法匹配通道快照、按通道筛选也失效。

用法（在 backend/ 目录下执行）：
    python tools/backfill_channelid.py            # 只预览（默认不写库）
    python tools/backfill_channelid.py --apply    # 实际写库
"""
import argparse
import asyncio
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update  # noqa: E402

from models.db import AsyncSessionLocal  # noqa: E402
from models.orm import AlertORM  # noqa: E402

BATCH = 500
# rawPayload 超长会被截断（8KB），截断后 json 解析失败时退回正则粗取 additional 里的 device_id
ADDITIONAL_DEVICE_ID_RE = re.compile(r'"additional"\s*:\s*\{.*?"device_id"\s*:\s*"?([0-9A-Za-z_-]+)"?', re.S)


def channel_from_payload(raw: str):
    """从原始报文里取 (通道号, 通道名)；取不到返回 (None, None)。"""
    if not raw:
        return None, None
    try:
        d = json.loads(raw)
    except Exception:  # noqa: BLE001  截断/非法 JSON → 正则兜底
        m = ADDITIONAL_DEVICE_ID_RE.search(raw)
        return (m.group(1) if m else None), None
    additional = d.get("additional") or {}
    cid = additional.get("device_id")
    if cid is None:
        cid = additional.get("channel_id")
    return (str(cid) if cid is not None else None), (additional.get("device_name") or None)


async def main() -> int:
    parser = argparse.ArgumentParser(description="回填 alerts.channelid（按报文 additional.device_id 修正）")
    parser.add_argument("--apply", action="store_true", help="实际写库（默认只预览）")
    args = parser.parse_args()

    fixed = skipped = scanned = 0
    samples = []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AlertORM.id, AlertORM.channelid, AlertORM.channelname, AlertORM.rawPayload)
            .where(AlertORM.rawPayload.isnot(None), AlertORM.rawPayload != "")
        )).all()
        print(f"扫描到有原始报文的告警 {len(rows)} 条")
        for alert_id, old_cid, old_name, raw in rows:
            scanned += 1
            cid, cname = channel_from_payload(raw)
            if cid is None:
                skipped += 1
                continue
            want_name = cname or old_name
            if str(old_cid or "") == str(cid) and (old_name or "") == (want_name or ""):
                continue
            if len(samples) < 5:
                samples.append((alert_id[:28], old_cid, cid, old_name, want_name))
            if args.apply:
                await db.execute(
                    update(AlertORM).where(AlertORM.id == alert_id)
                    .values(channelid=str(cid), channelname=want_name or ""))
            fixed += 1
            if args.apply and fixed % BATCH == 0:
                await db.commit()
        if args.apply:
            await db.commit()

    print(f"扫描 {scanned} 条；{'已修正' if args.apply else '待修正'} {fixed} 条；报文不可解析跳过 {skipped} 条")
    for s in samples:
        print(f"   样例 {s[0]}… : channelid {s[1]!r} → {s[2]!r} | channelname {s[3]!r} → {s[4]!r}")
    if not args.apply:
        print("（预览模式，未写库；确认无误后加 --apply 执行）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
