"""下载 Chinese-CLIP 权重到本地（默认 backend/models/chinese-clip-vit-base-patch16）。

为什么要这个脚本：
- 国内直连 huggingface.co 常常不通，脚本默认走 https://hf-mirror.com 镜像（可用 --endpoint 覆盖）；
- 仓库里同时放了 pytorch_model.bin 与 clip_cn_vit-b-16.pt 两份等价权重，脚本默认跳过 .pt，下载量减半（约 720MB）；
- 下载到本地目录后，检索/建模全程离线可用，不再依赖网络。

用法（在 backend/ 目录下执行）：
    python tools/download_clip_model.py                 # 下载到默认目录
    python tools/download_clip_model.py --force         # 已存在也重新下载
    python tools/download_clip_model.py --endpoint https://huggingface.co   # 直连（能翻墙时）
"""
import argparse
import os
import sys

DEFAULT_REPO = "OFA-Sys/chinese-clip-vit-base-patch16"
DEFAULT_ENDPOINT = "https://hf-mirror.com"
DEFAULT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "chinese-clip-vit-base-patch16",
)


def dir_ready(path: str) -> bool:
    """目录里是否已有可加载的权重（config + 任一权重文件）。"""
    if not os.path.isdir(path):
        return False
    names = set(os.listdir(path))
    has_cfg = "config.json" in names
    has_weight = any(n in names for n in ("pytorch_model.bin", "model.safetensors"))
    return has_cfg and has_weight


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 Chinese-CLIP 权重到本地目录")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"HF 仓库（默认 {DEFAULT_REPO}）")
    parser.add_argument("--endpoint", default=os.environ.get("HF_ENDPOINT", DEFAULT_ENDPOINT),
                        help=f"HF 端点/镜像（默认 {DEFAULT_ENDPOINT}）")
    parser.add_argument("--dir", default=DEFAULT_DIR, help=f"本地目录（默认 {DEFAULT_DIR}）")
    parser.add_argument("--force", action="store_true", help="已存在也重新下载")
    args = parser.parse_args()

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("缺少 huggingface_hub：请先 pip install huggingface_hub（或升级 transformers）", file=sys.stderr)
        return 2

    if dir_ready(args.dir) and not args.force:
        print(f"模型已存在：{args.dir}\n如需重新下载请加 --force")
        return 0

    os.makedirs(args.dir, exist_ok=True)
    print(f"从 {args.endpoint} 下载 {args.repo}\n  → {args.dir}\n（约 720MB，跳过重复的 .pt 权重）")
    try:
        snapshot_download(
            repo_id=args.repo,
            local_dir=args.dir,
            endpoint=args.endpoint,
            # 仓库里的 clip_cn_vit-b-16.pt 与 pytorch_model.bin 等价，跳过前者省一半流量
            ignore_patterns=["*.pt"],
            max_workers=4,
        )
    except Exception as e:  # noqa: BLE001
        print(f"下载失败：{type(e).__name__}: {e}\n"
              f"可改用其它端点重试：--endpoint https://huggingface.co", file=sys.stderr)
        return 2

    if not dir_ready(args.dir):
        print("下载完成但目录里缺少权重文件，请检查网络/镜像。", file=sys.stderr)
        return 2
    total = sum(os.path.getsize(os.path.join(args.dir, f))
                for f in os.listdir(args.dir) if os.path.isfile(os.path.join(args.dir, f)))
    print(f"完成：{args.dir}（{total / 1048576:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
