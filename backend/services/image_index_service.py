"""图文互搜的索引服务：异步批量建索（特征提取）、向量池缓存、相似度检索。

核心模型：
- 一行 = 一张图的一条向量（`image_embeddings`），kind 区分 `big`（告警大图）/ `crop`（送检小图）；
- **非实时建模**：由后台定时任务（见 image_index_worker）每轮取一小批未建索的告警图片编码入库，
  不阻塞告警接收与接口；也支持手动「重建索引」；
- **增量判据**：告警有图 且 缺 (alert_id, kind, 当前模型) 的行 → 待处理。编码失败（图丢了/损坏）
  写一条 dim=0 的「墓碑行」，避免每轮反复重试同一张坏图（重建索引可清掉重试）；
- **检索**：向量池（per kind 的 numpy 矩阵）常驻内存并按写入版本号自动失效重建，
  文本/图片查询向量与池做矩阵乘 → top-k（`argpartition`）。
  池重建为**一次性 fetchall + 整块 reshape**，5w 张实测 ~0.5s（早期用 `LIMIT/OFFSET` 分页
  要 ~28s，是被 27 次全表扫描拖垮的）；热路径单次检索 ~5ms。
  后台每轮建索完会 `warm_pools()` 预热，避免把重建成本转嫁给用户请求；文本查询向量另有 LRU 缓存。
"""
import asyncio
import os
import time
from collections import Counter, OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import func, select, delete, exists, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

import database
from models.db import AsyncSessionLocal
from models.orm import AlertORM, ImageEmbeddingORM
from services import clip_service

KINDS = ("big", "crop")
# 增量扫描只处理「有图」的告警：分别对应 imageUrl / imageUrlCrop
KIND_FIELD = {"big": AlertORM.imageUrl, "crop": AlertORM.imageUrlCrop}

# ── 运行状态（进程内，供 /search/status 与前端状态条展示）─────────────────
_state = {
    "running": False,          # 当前是否有一轮建索在跑
    "last_run_ts": 0,
    "last_indexed": 0,
    "last_skipped": 0,
    "last_error": "",
    "total_indexed": 0,
}
# 向量池：{kind: {"version": int, "ids": [alert_id...], "mat": np.ndarray(N,512)}}
_pool: Dict[str, dict] = {}
_index_version = 0             # 每次写入/删除自增；池版本落后即重建
_pending_cache = {"ts": 0.0, "value": 0}
_index_lock = asyncio.Lock()   # 同一时刻只允许一轮建索（定时任务与手动触发的互斥）
_last_prune_ts = 0.0           # 孤儿向量清理的节流时间戳（见 run_index_cycle）


# ── 路径处理 ────────────────────────────────────────────────────────────
def to_disk_path(image_url: Optional[str]) -> str:
    """告警里的图片 URL（形如 /uploads/2026-10-12/18/x.jpg）→ 本地磁盘路径。

    与 main.py 的静态目录挂载口径一致：uploads 相对 backend/ 工作目录。
    """
    if not image_url:
        return ""
    return image_url.lstrip("/").replace("/", os.sep)


def normalize_rel_path(image_url: Optional[str]) -> str:
    """归一化相对路径（统一 / 分隔），存进索引表用于诊断与失效判断。"""
    return (image_url or "").lstrip("/")


def _file_exists(image_url: Optional[str]) -> bool:
    p = to_disk_path(image_url)
    return bool(p) and os.path.isfile(p)


# ── 待处理统计 / 增量批次 ────────────────────────────────────────────────
def _missing_condition(kind: str):
    """「该告警的这一类图还没建索（或模型版本过期）」的 SQL 条件。"""
    field = KIND_FIELD[kind]
    has_image = and_(field.isnot(None), field != "")
    not_indexed = ~exists().where(and_(
        ImageEmbeddingORM.alert_id == AlertORM.id,
        ImageEmbeddingORM.kind == kind,
        ImageEmbeddingORM.model == clip_service.MODEL_TAG,
    ))
    return and_(has_image, not_indexed)


async def pending_count(db: Optional[AsyncSession] = None, ttl: float = 10.0) -> int:
    """待建索告警数（两类图任一缺失即计入）；带 TTL 缓存，避免每次轮询都全表统计。"""
    now = time.time()
    if db is None and now - _pending_cache["ts"] < ttl:
        return _pending_cache["value"]
    owns = db is None
    if owns:
        db = AsyncSessionLocal()
    try:
        q = select(func.count()).select_from(AlertORM).where(
            or_(_missing_condition("big"), _missing_condition("crop")))
        value = int((await db.execute(q)).scalar() or 0)
    finally:
        if owns:
            await db.close()
    _pending_cache.update({"ts": now, "value": value})
    return value


async def fetch_pending(limit: int) -> List[dict]:
    """取一批待建索的告警（新的优先）：返回 [{alert_id, kind, image_url}]，每张图一条。"""
    limit = max(1, int(limit))
    items: List[dict] = []
    async with AsyncSessionLocal() as db:
        # 先按「整条告警」取，再展开成逐图任务，避免同一告警被两类图各算一次批次上限
        alerts = (await db.execute(
            select(AlertORM.id, AlertORM.imageUrl, AlertORM.imageUrlCrop)
            .where(or_(_missing_condition("big"), _missing_condition("crop")))
            .order_by(AlertORM.timestamp.desc())
            .limit(limit)
        )).all()
        if not alerts:
            return []
        ids = [a[0] for a in alerts]
        done = set()
        rows = (await db.execute(
            select(ImageEmbeddingORM.alert_id, ImageEmbeddingORM.kind)
            .where(ImageEmbeddingORM.alert_id.in_(ids),
                   ImageEmbeddingORM.model == clip_service.MODEL_TAG)
        )).all()
        for alert_id, kind in rows:
            done.add((alert_id, kind))
    for alert_id, image_url, image_crop in alerts:
        for kind, url in (("big", image_url), ("crop", image_crop)):
            if url and (alert_id, kind) not in done:
                items.append({"alert_id": alert_id, "kind": kind, "image_url": url})
    return items[:limit]


# ── 建索写入 ────────────────────────────────────────────────────────────
def _vec_to_blob(vec: Optional[np.ndarray]) -> bytes:
    """向量 → BLOB；None（无可用图/解码失败）写成空向量作为「已尝试」墓碑行。"""
    if vec is None:
        return b""
    return np.asarray(vec, dtype=np.float32).tobytes()


async def index_batch(limit: int) -> dict:
    """编码一批待处理图片并写库。返回 {indexed, skipped, remaining}。"""
    global _index_version
    if not clip_service.is_configured():
        return {"indexed": 0, "skipped": 0, "remaining": 0, "error": "图文互搜已在配置中关闭"}
    tasks = await fetch_pending(limit)
    if not tasks:
        return {"indexed": 0, "skipped": 0, "remaining": 0, "error": ""}

    indexed = skipped = 0
    now_ms = int(time.time() * 1000)
    async with AsyncSessionLocal() as db:
        # 逐 kind 分组编码：同一批图尺寸一致，显存/内存更省
        for kind in KINDS:
            chunk = [t for t in tasks if t["kind"] == kind]
            if not chunk:
                continue
            paths = [to_disk_path(t["image_url"]) for t in chunk]
            try:
                vectors = await clip_service.encode_images(paths)
            except Exception as e:  # noqa: BLE001
                # 模型不可用：整轮放弃（不清空任务，下轮再试），把原因抛给调用方记录
                _state["last_error"] = f"{type(e).__name__}: {e}"
                raise
            for task, vec in zip(chunk, vectors):
                ok = vec is not None
                blob = _vec_to_blob(vec)
                row_id = f"{task['alert_id']}:{kind}"
                existing = await db.get(ImageEmbeddingORM, row_id)
                if existing is None:
                    db.add(ImageEmbeddingORM(
                        id=row_id, alert_id=task["alert_id"], kind=kind,
                        image_path=normalize_rel_path(task["image_url"]),
                        model=clip_service.MODEL_TAG,
                        dim=(0 if not ok else int(np.asarray(vec).shape[0])),
                        vector=blob, created_at=now_ms))
                else:
                    existing.image_path = normalize_rel_path(task["image_url"])
                    existing.model = clip_service.MODEL_TAG
                    existing.dim = 0 if not ok else int(np.asarray(vec).shape[0])
                    existing.vector = blob
                    existing.created_at = now_ms
                indexed += 1 if ok else 0
                skipped += 0 if ok else 1
        await db.commit()
    _index_version += 1          # 池失效，下次检索重建
    _pending_cache["ts"] = 0.0
    return {"indexed": indexed, "skipped": skipped, "remaining": await pending_count()}


async def prune_orphans() -> int:
    """删除告警已被清理（7 天清理任务）后遗留的向量行，返回删除条数。"""
    global _index_version
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            delete(ImageEmbeddingORM).where(
                ImageEmbeddingORM.alert_id.notin_(select(AlertORM.id))))
        await db.commit()
        deleted = int(res.rowcount or 0)
    if deleted:
        _index_version += 1
        _pending_cache["ts"] = 0.0
        print(f"[ImageIndex] 已清理 {deleted} 条失去关联告警的向量")
    return deleted


async def reset_index(kind: Optional[str] = None) -> int:
    """清空索引（kind 为空则两类都清）；清空后由后台任务重新建索。返回删除条数。"""
    global _index_version
    async with AsyncSessionLocal() as db:
        stmt = delete(ImageEmbeddingORM)
        if kind in KINDS:
            stmt = stmt.where(ImageEmbeddingORM.kind == kind)
        res = await db.execute(stmt)
        await db.commit()
        deleted = int(res.rowcount or 0)
    _index_version += 1
    _pool.clear()
    _pending_cache["ts"] = 0.0
    return deleted


# ── 向量池（检索用） ────────────────────────────────────────────────────
def _assemble(rows) -> Tuple[List[str], np.ndarray]:
    """把 (alert_id, vector, dim) 行拼成 (ids, (N, dim) float32)。

    快路径：向量等长时用 `b"".join + np.frombuffer + reshape`（5w 张实测 22ms，
    比逐行 frombuffer + np.vstack 的 ~90ms 快 4 倍）。

    维度异常的行（blob 长度与 dim 不符、或与主维度不同）会被剔除：
    只保留出现次数最多的维度，避免个别脏行把整池宽度搞乱（也绝不截断后续正常行）。
    """
    ids: List[str] = []
    blobs: List[bytes] = []
    for alert_id, blob, dim in rows:
        if not blob:
            continue
        want = int(dim or 0) * 4
        if want <= 0 or len(blob) != want:
            continue
        ids.append(alert_id)
        blobs.append(blob)
    if not blobs:
        return [], np.zeros((0, 0), dtype=np.float32)

    widths = Counter(len(b) for b in blobs)
    width = widths.most_common(1)[0][0]
    if len(widths) > 1:                       # 极少见：混入其它维度 → 只保留主维度
        kept = [(i, b) for i, b in zip(ids, blobs) if len(b) == width]
        ids = [i for i, _ in kept]
        blobs = [b for _, b in kept]
        if not blobs:
            return [], np.zeros((0, 0), dtype=np.float32)
    mat = np.frombuffer(b"".join(blobs), dtype=np.float32).reshape(len(blobs), width // 4)
    return ids, mat


async def _fetch_pool_rows(kind: str) -> list:
    """按 kind 拉取有效向量行。

    关键：**不分页**。早期用 `LIMIT 2000 OFFSET n` + `ORDER BY created_at DESC` 分批，
    SQLite 每次都要重扫/重排全表，5w 张要 27 次查询、累计 ~28 秒；
    一次性 fetchall 只需 ~0.34 秒（同一份数据，快 84 倍）。内存峰值也只是 110MB 的 BLOB 列表。
    """
    q = (select(ImageEmbeddingORM.alert_id, ImageEmbeddingORM.vector, ImageEmbeddingORM.dim)
         .where(ImageEmbeddingORM.kind == kind,
                ImageEmbeddingORM.model == clip_service.MODEL_TAG,
                ImageEmbeddingORM.dim > 0))
    async with AsyncSessionLocal() as db:
        return (await db.execute(q)).all()


async def _load_pool(kind: str) -> dict:
    """加载某一类图的向量池：ids + (N, dim) float32 矩阵（L2 已归一化，可直接内积）。"""
    ids, mat = _assemble(await _fetch_pool_rows(kind))
    return {"version": _index_version, "ids": ids, "mat": mat}


async def get_pool(kind: str) -> dict:
    """取（必要时重建）某一类图的向量池；版本号变化即重建（已从 ~28s 降到 ~0.4s）。"""
    kind = kind if kind in KINDS else "big"
    pool = _pool.get(kind)
    if pool is None or pool.get("version") != _index_version:
        pool = await _load_pool(kind)
        _pool[kind] = pool
    return pool


async def warm_pools() -> None:
    """预热向量池（后台建索完成后调用）。

    让「用户搜索」尽量命中已就绪的池：否则每次建索新图都会 bump 版本号，
    下一次搜索就要付一次重建成本。
    """
    for kind in KINDS:
        try:
            await get_pool(kind)
        except Exception as e:  # noqa: BLE001
            print(f"[ImageIndex] 预热 {kind} 向量池失败：{type(e).__name__}: {e}")


# ── 过滤与检索 ──────────────────────────────────────────────────────────
# 文本查询向量缓存：CLIP 文本编码是 CPU 上的 transformer 前向，实测 ~380ms/次；
# 同一句描述（含翻页、反复调参）直接复用向量，能省掉这一整段。
_QUERY_CACHE: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_QUERY_CACHE_MAX = 256


async def _encode_text_cached(text: str) -> np.ndarray:
    """文本 → 查询向量（带 LRU 缓存，键含模型标识，换模型自动失效）。"""
    key = (clip_service.MODEL_TAG, text)
    hit = _QUERY_CACHE.get(key)
    if hit is not None:
        _QUERY_CACHE.move_to_end(key)
        return hit
    vec = (await clip_service.encode_texts([text]))[0]
    _QUERY_CACHE[key] = vec
    if len(_QUERY_CACHE) > _QUERY_CACHE_MAX:
        _QUERY_CACHE.popitem(last=False)
    return vec


async def _allowed_alert_ids(filters: dict) -> Optional[set]:
    """按过滤条件取允许的 alert_id 集合；无任何过滤返回 None（不过滤）。"""
    filters = filters or {}
    conds = []
    if filters.get("deviceName"):
        conds.append(AlertORM.deviceName == filters["deviceName"])
    if filters.get("channelname"):
        conds.append(AlertORM.channelname == filters["channelname"])
    if filters.get("channelid"):
        conds.append(AlertORM.channelid == str(filters["channelid"]))
    if filters.get("alertType"):
        conds.append(AlertORM.alertType == filters["alertType"])
    if filters.get("start_ts"):
        conds.append(AlertORM.timestamp >= int(filters["start_ts"]))
    if filters.get("end_ts"):
        conds.append(AlertORM.timestamp <= int(filters["end_ts"]))
    if not conds:
        return None
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(AlertORM.id).where(and_(*conds)))).all()
    return {r[0] for r in rows}


async def _hits_from_scores(kind: str, scores: np.ndarray, top_k: int,
                            allowed: Optional[set]) -> List[dict]:
    """把相似度数组转成告警明细列表（按分数降序，最多 top_k 条）。"""
    pool = await get_pool(kind)
    ids = pool["ids"]
    if not ids or scores.size == 0:
        return []
    # 只需 top-k：用 argpartition 代替全排序（5w 张：1ms → 0.3ms，且过滤时不用遍历全量）
    k = min(len(ids), max(top_k * 4, top_k + 32))
    cand = np.argpartition(-scores, k - 1)[:k]
    order = cand[np.argsort(-scores[cand])]
    picked: List[Tuple[str, float]] = []
    for idx in order:
        alert_id = ids[int(idx)]
        if allowed is not None and alert_id not in allowed:
            continue
        picked.append((alert_id, float(scores[int(idx)])))
        if len(picked) >= top_k:
            break
    if not picked:
        return []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AlertORM).where(AlertORM.id.in_([p[0] for p in picked]))
        )).scalars().all()
    by_id = {a.id: a for a in rows}
    out = []
    for alert_id, score in picked:
        a = by_id.get(alert_id)
        if a is None:          # 告警刚被清理，跳过
            continue
        out.append({
            "alert_id": a.id,
            "score": round(score, 4),
            "kind": kind,
            # 关联关系：同一告警的【大图 + 小图】一并返回，前端检索命中小图时可看对应大图，反之亦然
            "imageUrl": a.imageUrl,          # 告警大图（整帧）
            "imageUrlCrop": a.imageUrlCrop,  # 送检小图（目标裁切），可能为空
            # 本次实际命中的是哪一张（前端据此高亮缩略图/文案）
            "matched_image": a.imageUrl if kind == "big" else a.imageUrlCrop,
            "matched_kind": kind,
            "deviceName": a.deviceName,
            "alertType": a.alertType,
            "channelname": a.channelname,
            "time": a.time,
            "timestamp": a.timestamp,
            "feedback_status": a.feedback_status,
        })
    return out


async def search_by_text(query: str, kind: str = "big", top_k: int = 30,
                         filters: Optional[dict] = None) -> dict:
    """文搜图：中文（或英文）自然语言描述 → 相似图。"""
    query = (query or "").strip()
    if not query:
        return {"hits": [], "pool_size": 0, "error": "查询文本为空"}
    ok, msg = clip_service.load_model()
    if not ok:
        return {"hits": [], "pool_size": 0, "error": msg}
    vec = await _encode_text_cached(query)
    pool = await get_pool(kind)
    if pool["mat"].size == 0:
        return {"hits": [], "pool_size": 0, "error": "该索引还没有任何图片，请先等待后台建索完成"}
    if pool["mat"].shape[1] != vec.shape[0]:
        return {"hits": [], "pool_size": len(pool["ids"]),
                "error": f"向量维度不一致（索引 {pool['mat'].shape[1]} / 查询 {vec.shape[0]}），请重建索引"}
    scores = pool["mat"] @ vec
    allowed = await _allowed_alert_ids(filters or {})
    hits = await _hits_from_scores(kind, scores, max(1, int(top_k)), allowed)
    return {"hits": hits, "pool_size": len(pool["ids"]), "error": "", "query": query}


async def search_by_image(image_bytes: bytes, kind: str = "big", top_k: int = 30,
                          filters: Optional[dict] = None) -> dict:
    """以图搜图：上传图片 → 相似图（复用同一套索引）。"""
    if not image_bytes:
        return {"hits": [], "pool_size": 0, "error": "上传内容为空"}
    ok, msg = clip_service.load_model()
    if not ok:
        return {"hits": [], "pool_size": 0, "error": msg}
    import io
    import tempfile
    from PIL import Image

    # 编码接口按路径读图，这里落一个临时文件即可复用同一条编码链路（含异常处理）
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im.convert("RGB")     # 触发真正的解码校验（截断/损坏文件在这里就会报错）
    except Exception as e:  # noqa: BLE001
        return {"hits": [], "pool_size": 0, "error": f"图片无法解码：{e}"}
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    try:
        tmp.write(image_bytes)
        tmp.close()
        vecs = await clip_service.encode_images([tmp.name])
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    if not vecs or vecs[0] is None:
        return {"hits": [], "pool_size": 0, "error": "图片编码失败"}
    pool = await get_pool(kind)
    if pool["mat"].size == 0:
        return {"hits": [], "pool_size": 0, "error": "该索引还没有任何图片，请先等待后台建索完成"}
    scores = pool["mat"] @ vecs[0]
    allowed = await _allowed_alert_ids(filters or {})
    hits = await _hits_from_scores(kind, scores, max(1, int(top_k)), allowed)
    return {"hits": hits, "pool_size": len(pool["ids"]), "error": ""}


# ── 后台一轮（定时任务调用） ─────────────────────────────────────────────
async def run_index_cycle() -> dict:
    """后台一轮：清理孤儿向量 + 增量建索一批。同一时刻只允许一轮在跑。"""
    global _last_prune_ts
    if not clip_service.is_configured():
        return {"skipped": "disabled"}
    if _index_lock.locked():
        return {"skipped": "busy"}
    async with _index_lock:
        _state["running"] = True
        _state["last_error"] = ""
        try:
            # 孤儿清理不必每轮做（告警清理是每小时一次）：节流到 10 分钟一次，省掉大表 NOT IN
            if time.time() - _last_prune_ts > 600:
                _last_prune_ts = time.time()
                await prune_orphans()
            per_cycle = int(database_per_cycle())
            res = await index_batch(per_cycle)
            _state.update({
                "last_run_ts": int(time.time() * 1000),
                "last_indexed": res.get("indexed", 0),
                "last_skipped": res.get("skipped", 0),
            })
            if res.get("indexed") or res.get("skipped"):
                print(f"[ImageIndex] 本轮建索 {res['indexed']} 张，跳过 {res['skipped']} 张，"
                      f"剩余 {res.get('remaining', 0)}")
            # 有新向量入库就预热池：否则版本号已 bump，下一次检索要多付一次重建成本
            if res.get("indexed"):
                await warm_pools()
            return res
        except Exception as e:  # noqa: BLE001
            _state["last_error"] = f"{type(e).__name__}: {e}"
            print(f"[ImageIndex] 本轮失败：{_state['last_error']}")
            return {"error": _state["last_error"]}
        finally:
            _state["running"] = False


def database_per_cycle() -> int:
    """每轮处理张数（配置项 per_cycle）。"""
    try:
        return max(1, int(database.image_search_config.get("per_cycle") or 120))
    except (TypeError, ValueError):
        return 120


async def status() -> dict:
    """索引状态汇总（前端状态条 + /search/status）。"""
    async with AsyncSessionLocal() as db:
        by_kind = {}
        for kind in KINDS:
            total = int((await db.execute(
                select(func.count()).select_from(ImageEmbeddingORM)
                .where(ImageEmbeddingORM.kind == kind,
                       ImageEmbeddingORM.model == clip_service.MODEL_TAG))).scalar() or 0)
            usable = int((await db.execute(
                select(func.count()).select_from(ImageEmbeddingORM)
                .where(ImageEmbeddingORM.kind == kind,
                       ImageEmbeddingORM.model == clip_service.MODEL_TAG,
                       ImageEmbeddingORM.dim > 0))).scalar() or 0)
            by_kind[kind] = {"indexed": total, "usable": usable, "failed": total - usable}
        alert_total = int((await db.execute(
            select(func.count()).select_from(AlertORM))).scalar() or 0)
        with_image = int((await db.execute(
            select(func.count()).select_from(AlertORM)
            .where(or_(and_(AlertORM.imageUrl.isnot(None), AlertORM.imageUrl != ""),
                       and_(AlertORM.imageUrlCrop.isnot(None), AlertORM.imageUrlCrop != "")))
        )).scalar() or 0)
    pending = await pending_count()
    _state["total_indexed"] = by_kind["big"]["usable"] + by_kind["crop"]["usable"]
    return {
        "model": clip_service.status(),
        "index": {
            "by_kind": by_kind,
            "total_indexed": _state["total_indexed"],
            "pending": pending,
            "running": _state["running"],
            "last_run_ts": _state["last_run_ts"],
            "last_indexed": _state["last_indexed"],
            "last_skipped": _state["last_skipped"],
            "last_error": _state["last_error"],
        },
        "data": {"alerts": alert_total, "alerts_with_image": with_image},
        "config": {
            "batch_size": database.image_search_config.get("batch_size"),
            "per_cycle": database_per_cycle(),
            "interval_seconds": database.image_search_config.get("interval_seconds"),
        },
    }


def invalidate_pool() -> None:
    """外部（如告警清理）改了数据后可主动调用，让向量池下次检索时重建。"""
    global _index_version
    _index_version += 1


def reset_state_for_tests() -> None:
    """测试辅助：清掉进程内缓存。"""
    global _index_version
    _pool.clear()
    _index_version += 1
    _pending_cache["ts"] = 0.0
