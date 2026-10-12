"""Chinese-CLIP 本地推理封装（图文互搜的特征提取）。

设计要点：
- **懒加载单例**：进程内只加载一次模型（ViT-B/16 约 720MB 权重），首次用到时才载入，
  不拖慢后端启动；加载失败会记录原因并把 detail 返回给前端，而不是让接口 500。
- **跨平台设备选择**：显式配置 > cuda > mps（Apple Silicon）> cpu，Mac 与 Windows 同一套代码。
- **纯本地推理**：权重放在 backend/models/ 下（tools/download_clip_model.py 下载），
  运行期不访问网络；模型缺失时 encoder_ready() 返回 False 并给出下载提示。
- 向量一律 L2 归一化后返回，检索端用内积即可等价余弦相似度。
"""
import asyncio
import os
import threading
from typing import List, Optional, Sequence, Tuple

import numpy as np

import database

# 模型/向量标识：写进索引表，换模型或换维度时可识别旧向量并重建
MODEL_TAG = "chinese-clip-vit-base-patch16"

_lock = threading.Lock()          # 保护模型加载（多线程首次并发调用）
_model = None
_processor = None
_device: Optional[str] = None
_load_error = ""                  # 最近一次加载失败原因（供前端提示）
_loaded_from = ""                 # 实际加载的模型目录


def model_dir() -> str:
    """模型目录（相对 backend/ 工作目录或绝对路径）。"""
    return (database.image_search_config.get("model_dir") or "models/chinese-clip-vit-base-patch16").strip()


def is_configured() -> bool:
    """配置开关是否打开（关闭后不建索、不检索）。"""
    return bool(database.image_search_config.get("enabled", True))


def local_model_ready() -> bool:
    """本地是否已有可加载的权重（config.json + 任一权重文件）。"""
    path = model_dir()
    if not os.path.isdir(path):
        return False
    names = set(os.listdir(path))
    return "config.json" in names and any(
        n in names for n in ("pytorch_model.bin", "model.safetensors"))


def pick_device() -> str:
    """选推理设备：配置里的 device 优先，否则 cuda → mps（Mac）→ cpu。"""
    wanted = (database.image_search_config.get("device") or "").strip().lower()
    try:
        import torch
    except ImportError:
        return "cpu"
    if wanted and wanted != "auto":
        if wanted == "cuda" and not torch.cuda.is_available():
            print("[CLIP] 配置指定 cuda 但当前不可用，回落自动选择")
        elif wanted == "mps" and not getattr(torch.backends, "mps", None):
            print("[CLIP] 配置指定 mps 但当前不可用，回落自动选择")
        else:
            return wanted
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def load_model(force: bool = False) -> Tuple[bool, str]:
    """加载（或复用）模型，返回 (成功?, 说明)。线程安全。"""
    global _model, _processor, _device, _load_error, _loaded_from
    with _lock:
        if _model is not None and not force:
            return True, f"已加载（{_device}）"
        _load_error = ""
        if not local_model_ready():
            _load_error = (f"本地未找到模型权重：{model_dir()}；"
                           f"请先执行 `python tools/download_clip_model.py` 下载")
            print(f"[CLIP] {_load_error}")
            return False, _load_error
        try:
            import torch
            from transformers import ChineseCLIPModel, ChineseCLIPProcessor

            _device = pick_device()
            model = ChineseCLIPModel.from_pretrained(model_dir())
            processor = ChineseCLIPProcessor.from_pretrained(model_dir())
            model.eval().to(_device)
            # CPU 上跑 float32；cuda/mps 上用 float16 提速并省显存（ViT-B/16 精度足够）
            if _device in ("cuda", "mps"):
                try:
                    model = model.half()
                except Exception:
                    pass
            with torch.inference_mode():
                _model, _processor = model, processor
            _loaded_from = os.path.abspath(model_dir())
            print(f"[CLIP] 模型加载完成：{_loaded_from}（device={_device}）")
            return True, f"模型加载完成（device={_device}）"
        except Exception as e:  # noqa: BLE001
            _model = _processor = None
            _load_error = f"模型加载失败：{type(e).__name__}: {e}"
            print(f"[CLIP] {_load_error}")
            return False, _load_error


def status() -> dict:
    """对外暴露的模型状态（供 /search/status 与前端状态条）。"""
    return {
        "enabled": is_configured(),
        "model": MODEL_TAG,
        "model_dir": os.path.abspath(model_dir()),
        "model_ready": local_model_ready(),
        "loaded": _model is not None,
        "loaded_from": _loaded_from,
        "device": _device or "",
        "error": _load_error,
    }


def _torch():
    import torch
    return torch


def _cast(value, half: bool):
    """把浮点张量转成模型一致的精度（half 模型 + float 输入会直接报 dtype 不匹配）。"""
    torch = _torch()
    if half and hasattr(value, "dtype") and torch.is_floating_point(value):
        return value.half()
    return value


def _extract_features(out):
    """从模型输出中取【投影后的多模态向量】。

    transformers 5.x 的 get_text_features / get_image_features 返回的是
    `BaseModelOutputWithPooling`（其中 pooler_output 即投影后的 (N, projection_dim) 向量），
    而 4.x 直接返回张量；这里两种都兼容，取不到就报明确错误而不是静默拿到 768 维的 last_hidden_state。
    """
    pooler = getattr(out, "pooler_output", None)
    if pooler is not None:
        return pooler
    if hasattr(out, "detach"):
        return out
    raise RuntimeError(f"无法从模型输出取到特征向量（{type(out).__name__}），请检查 transformers 版本")


def _normalize(feats) -> np.ndarray:
    """L2 归一化（float32 numpy）。"""
    arr = feats.detach().to("cpu").float().numpy()
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).astype(np.float32)


def encode_images_sync(paths: Sequence[str], batch_size: Optional[int] = None) -> List[Optional[np.ndarray]]:
    """批量编码图片，返回与入参等长的列表（读不出/解码失败的位置为 None）。

    同步、CPU/GPU 阻塞式调用：在异步上下文里请用 encode_images()（内部走线程池）。
    """
    ok, msg = load_model()
    if not ok:
        raise RuntimeError(msg)
    from PIL import Image

    torch = _torch()
    bs = int(batch_size or database.image_search_config.get("batch_size") or 8)
    out: List[Optional[np.ndarray]] = [None] * len(paths)

    for start in range(0, len(paths), bs):
        chunk = list(enumerate(paths[start:start + bs]))
        imgs, slots = [], []
        for idx, p in chunk:
            try:
                with Image.open(p) as im:
                    imgs.append(im.convert("RGB"))
                slots.append(idx)
            except Exception as e:  # noqa: BLE001
                print(f"[CLIP] 图片读取失败，跳过 {p}: {e}")
        if not imgs:
            continue
        try:
            inputs = _processor(images=imgs, return_tensors="pt")
            # cuda/mps 上模型是 half：像素张量必须同步转 half，否则 dtype 不一致会报错
            inputs = {k: _cast(v, half=_device in ("cuda", "mps")) for k, v in inputs.items()}
            inputs = {k: (v.to(_device) if hasattr(v, "to") else v) for k, v in inputs.items()}
            with torch.inference_mode():
                feats = _extract_features(_model.get_image_features(**inputs))
            vecs = _normalize(feats)
            for row, idx in enumerate(slots):
                out[idx] = vecs[row]
        except Exception as e:  # noqa: BLE001
            print(f"[CLIP] 批编码失败（跳过该批 {len(imgs)} 张）：{type(e).__name__}: {e}")
    return out


def encode_texts_sync(texts: Sequence[str]) -> np.ndarray:
    """批量编码文本查询，返回 (N, dim) 的 L2 归一化向量。"""
    ok, msg = load_model()
    if not ok:
        raise RuntimeError(msg)
    torch = _torch()
    inputs = _processor(text=list(texts), return_tensors="pt", padding=True, truncation=True, max_length=52)
    inputs = {k: (v.to(_device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    with torch.inference_mode():
        feats = _extract_features(_model.get_text_features(**inputs))
    return _normalize(feats)


async def encode_images(paths: Sequence[str], batch_size: Optional[int] = None) -> List[Optional[np.ndarray]]:
    """异步版图像编码：放到线程池执行，避免阻塞 FastAPI 事件循环（CPU 推理可达秒级）。"""
    if not paths:
        return []
    return await asyncio.to_thread(encode_images_sync, list(paths), batch_size)


async def encode_texts(texts: Sequence[str]) -> np.ndarray:
    """异步版文本编码（同上，走线程池）。"""
    return await asyncio.to_thread(encode_texts_sync, list(texts))
