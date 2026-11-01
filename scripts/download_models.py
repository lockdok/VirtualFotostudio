"""
Model downloader for Virtual AI Photostudio.

Downloads everything the identity workflow needs into ComfyUI's models folder:

* an SDXL portrait checkpoint            -> models/checkpoints
* IP-Adapter FaceID Plus V2 (SDXL) + LoRA -> models/ipadapter, models/loras
* IP-Adapter Plus Face SDXL                  -> models/ipadapter
* CLIP Vision ViT-H image encoder         -> models/clip_vision

Usage:
    python scripts/download_models.py                 # everything (default checkpoint)
    python scripts/download_models.py --what identity # identity adapters + CLIP Vision
    python scripts/download_models.py --what checkpoint --model sdxl-base

The InsightFace face-analysis model is fetched automatically by the IPAdapter
node on first use; the custom node itself and ``pip install insightface
onnxruntime-gpu`` are still manual steps (see README.md).
"""

import argparse
import os
import tempfile
from pathlib import Path

COMFY_BASE_DIR = Path(os.environ.get("COMFY_BASE_DIR", Path.home() / "Documents" / "ComfyUI"))
MODELS_DIR = COMFY_BASE_DIR / "models"

CHECKPOINTS = {
    "juggernaut-xl-v9": {
        "repo_id": "RunDiffusion/Juggernaut-XL-v9",
        "filename": "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
        "size_bytes": 7_105_348_188,
        "desc": "Juggernaut XL v9 (recommended for realistic portraiture, ~6.6 GB)",
    },
    "sdxl-base": {
        "repo_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "filename": "sd_xl_base_1.0.safetensors",
        "size_bytes": 6_938_078_334,
        "desc": "Official Stability AI SDXL Base 1.0 (~6.9 GB)",
    },
}

# repo file -> (destination folder under models/, destination filename)
IDENTITY_FILES = [
    {
        "repo_id": "h94/IP-Adapter-FaceID",
        "filename": "ip-adapter-faceid-plusv2_sdxl.bin",
        "dest_dir": "ipadapter",
        "dest_name": "ip-adapter-faceid-plusv2_sdxl.bin",
        "size_bytes": 1_487_555_181,
        "desc": "FaceID Plus V2 adapter (SDXL)",
    },
    {
        "repo_id": "h94/IP-Adapter-FaceID",
        "filename": "ip-adapter-faceid-plusv2_sdxl_lora.safetensors",
        "dest_dir": "loras",
        "dest_name": "ip-adapter-faceid-plusv2_sdxl_lora.safetensors",
        "size_bytes": 371_842_896,
        "desc": "FaceID Plus V2 LoRA (SDXL)",
    },
    {
        "repo_id": "h94/IP-Adapter",
        "filename": "sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors",
        "dest_dir": "ipadapter",
        "dest_name": "ip-adapter-plus-face_sdxl_vit-h.safetensors",
        "size_bytes": 847_517_512,
        "desc": "IP-Adapter Plus Face SDXL model",
    },
    {
        # Same encoder IPAdapter_plus documents as CLIP-ViT-H-14-laion2B-s32B-b79K.
        "repo_id": "h94/IP-Adapter",
        "filename": "models/image_encoder/model.safetensors",
        "dest_dir": "clip_vision",
        "dest_name": "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors",
        "size_bytes": 2_528_373_448,
        "desc": "CLIP Vision ViT-H image encoder",
    },
]


def _fetch(repo_id: str, filename: str, dest: Path, desc: str, size_bytes: int,
           force: bool = False) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise RuntimeError("Install the declared dependency with: python -m pip install huggingface-hub") from exc

    print(f"\n==> {desc}\n    -> {dest}")
    if dest.is_file() and dest.stat().st_size == size_bytes and not force:
        print("    already present, skipping.")
        return dest
    if dest.exists() and not dest.is_file():
        raise IsADirectoryError(f"Model destination is not a file: {dest}")
    if dest.exists():
        print(f"    existing file has {dest.stat().st_size} bytes; expected {size_bytes}. Replacing it.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        downloaded = hf_hub_download(repo_id=repo_id, filename=filename, local_dir=tmp)
        downloaded_path = Path(downloaded)
        actual_size = downloaded_path.stat().st_size
        if actual_size != size_bytes:
            raise RuntimeError(
                f"Downloaded {filename} has {actual_size} bytes; expected {size_bytes}. "
                "The incomplete file was not installed."
            )
        os.replace(downloaded_path, dest)
    print("    done.")
    return dest


def download_checkpoint(key: str = "juggernaut-xl-v9", force: bool = False) -> Path:
    item = CHECKPOINTS[key]
    return _fetch(item["repo_id"], item["filename"], MODELS_DIR / "checkpoints" / item["filename"],
                  item["desc"], item["size_bytes"], force)


def download_identity_models(force: bool = False) -> None:
    for item in IDENTITY_FILES:
        _fetch(item["repo_id"], item["filename"], MODELS_DIR / item["dest_dir"] / item["dest_name"],
               item["desc"], item["size_bytes"], force)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download models for Virtual AI Photostudio")
    parser.add_argument("--what", choices=["all", "checkpoint", "identity"], default="all",
                        help="which group of models to download (default: all)")
    parser.add_argument("--model", choices=list(CHECKPOINTS), default="juggernaut-xl-v9",
                        help="checkpoint to download when --what is 'all' or 'checkpoint'")
    parser.add_argument("--force", action="store_true",
                        help="redownload even when an existing file has the expected size")
    args = parser.parse_args()

    print(f"ComfyUI base directory: {COMFY_BASE_DIR}")
    if args.what in ("all", "identity"):
        download_identity_models(force=args.force)
    if args.what in ("all", "checkpoint"):
        download_checkpoint(args.model, force=args.force)
    print("\nFinished. Restart ComfyUI so it picks up the new files.")


if __name__ == "__main__":
    main()
