"""
Model Downloader Utility for Virtual AI Photostudio
Downloads top-tier SDXL portrait checkpoints directly into ComfyUI's models/checkpoints folder.
"""

import os
import sys
import argparse
from pathlib import Path
from huggingface_hub import hf_hub_download

COMFY_BASE_DIR = Path(os.environ.get("COMFY_BASE_DIR", Path.home() / "Documents" / "ComfyUI"))
CHECKPOINTS_DIR = COMFY_BASE_DIR / "models" / "checkpoints"
CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)

MODELS = {
    "juggernaut-xl-v9": {
        "repo_id": "RunDiffusion/Juggernaut-XL-v9",
        "filename": "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
        "desc": "Juggernaut XL v9 (Recommended for ultra-realistic portraiture, skin tones & lighting, ~6.6GB)",
    },
    "sdxl-base": {
        "repo_id": "stabilityai/stable-diffusion-xl-base-1.0",
        "filename": "sd_xl_base_1.0.safetensors",
        "desc": "Official Stability AI SDXL Base 1.0 (~6.9GB)",
    },
}

def download_model(key: str = "juggernaut-xl-v9"):
    if key not in MODELS:
        print(f"Unknown model key '{key}'. Choices: {list(MODELS.keys())}")
        return

    m = MODELS[key]
    dest_path = CHECKPOINTS_DIR / m["filename"]
    print(f"\n========================================================")
    print(f"📥 Downloading: {m['desc']}")
    print(f"   Destination: {dest_path}")
    print(f"========================================================\n")

    if dest_path.exists():
        print(f"✓ Model file already exists at {dest_path}!")
        return dest_path

    path = hf_hub_download(
        repo_id=m["repo_id"],
        filename=m["filename"],
        local_dir=str(CHECKPOINTS_DIR),
        local_dir_use_symlinks=False,
    )
    print(f"\n✓ Download complete! Saved to {path}\n")
    return path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download portrait checkpoints for Virtual AI Photostudio")
    parser.add_argument("--model", choices=list(MODELS.keys()), default="juggernaut-xl-v9", help="Model to download")
    args = parser.parse_args()
    download_model(args.model)

