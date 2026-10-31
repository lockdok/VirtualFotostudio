# Virtual AI Photostudio

Local ComfyUI photobooth with session-based likeness preservation. Reference photos, generated images and manifests stay on this PC; no identity model is trained.

## What it does

- Upload/select a local primary face reference.
- Generate a fast 3x3 prompt-quality preview in 3:4 or 4:3.
- Run a user-selected number of high-resolution individual images.
- Run selected concepts as a batch.
- Adjust FaceID identity strength from prompt freedom to likeness-first.
- Keep every job's prompt, seed and settings in `OUTPUT/.../shoot_manifest.json`.

## One-time identity setup

The project uses `ComfyUI_IPAdapter_plus` with **FaceID Plus V2 for SDXL**. Install its Python dependencies into the ComfyUI virtual environment:

```powershell
$env:COMFY_BASE_DIR = "$env:USERPROFILE\Documents\ComfyUI"
& "$env:COMFY_BASE_DIR\.venv\Scripts\python.exe" -m pip install insightface onnxruntime-gpu
```

Download these files to the listed local folders (they are intentionally git-ignored):

| File | Destination |
| --- | --- |
| A realistic SDXL checkpoint (for example Juggernaut XL) | `%COMFY_BASE_DIR%\models\checkpoints` |
| `ip-adapter-faceid-plusv2_sdxl.bin` | `...\models\ipadapter` |
| `ip-adapter-faceid-plusv2_sdxl_lora.safetensors` | `...\models\loras` |

The custom node is installed at `%COMFY_BASE_DIR%\custom_nodes\ComfyUI_IPAdapter_plus`. On first FaceID use, InsightFace will download its face-analysis model into ComfyUI's local models folder. Restart ComfyUI after installing components.

## Run

The launcher defaults `COMFY_BASE_DIR` to `%USERPROFILE%\Documents\ComfyUI` and `COMFY_MAIN` to the normal ComfyUI Desktop installation. Set either environment variable before launch if your installation lives elsewhere.

Start in the desired resource mode:

```bat
start_photostudio.bat quiet
start_photostudio.bat balanced
start_photostudio.bat turbo
```

Quiet reserves 6 GB for other applications; Balanced reserves 3 GB; Turbo reserves 0.5 GB. The scripts run both ComfyUI and Streamlit below normal CPU priority. Use `stop_photostudio.bat` to stop the local services.

## Notes

- The preview is deliberately a grid of independent images, not an inaccurately labelled fixed-size collage.
- `Release ComfyUI VRAM now` calls ComfyUI's `/free` endpoint. It requests model unloading; Windows or other GPU applications can still retain their own VRAM.
- `app.py` is the legacy UI. The launcher uses `photostudio_app.py`.
