# Virtual AI Photostudio

Local ComfyUI photobooth with session-based likeness preservation. Reference photos, generated images and manifests stay on this PC; no identity model is trained.

## What it does

- Upload/select a local primary face reference.
- Browse all saved reference photos as thumbnails and choose the primary reference by selecting a thumbnail.
- Rename built-in concepts and edit their prompts; customizations persist locally across restarts.
- Generate a fast 3x3 prompt-quality preview in 3:4 or 4:3.
- Click any preview thumbnail to open the full-size image in a new browser tab.
- See each successfully generated image appear in the gallery while preview, full, or batch generation is running.
- Run a user-selected number of high-resolution individual images. Full photos render at SDXL's native size (896×1152 or 1152×896) and, with *Detail pass* on (default), are enlarged 1.5× and refined by a second sampler pass to 1344×1728 / 1728×1344.
- Run selected concepts as a batch.
- Re-roll any single preview image (new seed and a new pose) without redoing the other eight.
- Adjust FaceID identity strength from prompt freedom to likeness-first.
- Keep every job's prompt, seed and settings in `OUTPUT/.../shoot_manifest.json`.

## One-time identity setup

The project uses `ComfyUI_IPAdapter_plus` with **FaceID Plus V2 for SDXL**.

1. Install [ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) at `%COMFY_BASE_DIR%\custom_nodes\ComfyUI_IPAdapter_plus`.
2. Install its Python dependencies into the ComfyUI virtual environment:

```powershell
$env:COMFY_BASE_DIR = "$env:USERPROFILE\Documents\ComfyUI"
& "$env:COMFY_BASE_DIR\.venv\Scripts\python.exe" -m pip install insightface onnxruntime-gpu
```

3. **One-click option:** double-click `download_models.bat` in the project folder. It uses ComfyUI's Python environment, installs the downloader dependency if needed, and downloads the default checkpoint plus all required identity models. The default set needs about 12.3 GB of free disk space. You can also pass downloader options from Command Prompt, for example `download_models.bat --what identity`.

   Or download the model files directly with the helper script:

```powershell
& "$env:COMFY_BASE_DIR\.venv\Scripts\python.exe" scripts\download_models.py
```

This places the files below (they are intentionally git-ignored). Use `--what identity` to skip the checkpoint, or `--what checkpoint --model sdxl-base` for a different one. The script checks exact file sizes and replaces incomplete files; use `--force` to redownload valid files. You can also download them by hand:

### Models used by the workflow

| Model | Download | Destination under `%COMFY_BASE_DIR%\models` | Approx. size |
| --- | --- | --- | ---: |
| Juggernaut XL v9 SDXL checkpoint (default) | [Download](https://huggingface.co/RunDiffusion/Juggernaut-XL-v9/resolve/main/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors?download=true) | `checkpoints\Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors` | 7.1 GB |
| Official SDXL Base 1.0 checkpoint (alternative) | [Download](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors?download=true) | `checkpoints\sd_xl_base_1.0.safetensors` | 6.9 GB |
| IP-Adapter FaceID Plus V2 for SDXL | [Download](https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sdxl.bin?download=true) | `ipadapter\ip-adapter-faceid-plusv2_sdxl.bin` | 1.5 GB |
| FaceID Plus V2 LoRA for SDXL | [Download](https://huggingface.co/h94/IP-Adapter-FaceID/resolve/main/ip-adapter-faceid-plusv2_sdxl_lora.safetensors?download=true) | `loras\ip-adapter-faceid-plusv2_sdxl_lora.safetensors` | 372 MB |
| IP-Adapter Plus Face for SDXL (secondary image guidance) | [Download](https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors?download=true) | `ipadapter\ip-adapter-plus-face_sdxl_vit-h.safetensors` | 848 MB |
| CLIP Vision ViT-H encoder | [Download](https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors?download=true) | `clip_vision\CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors` | 2.5 GB |
| InsightFace `antelopev2` face-analysis models | [Upstream model release](https://github.com/deepinsight/insightface/releases/download/v0.7/antelopev2.zip) | Managed by `ComfyUI_IPAdapter_plus` on first use | Downloaded automatically |

The workflow requires one checkpoint plus the FaceID adapter, FaceID LoRA, Plus Face adapter, and CLIP Vision encoder. Downloading the default checkpoint and all identity models uses about 12.3 GB. The InsightFace models are fetched by the custom node separately. Check upstream model licenses and terms before commercial use; gated repositories may require accepting their terms or configuring Hugging Face access.

On first FaceID use, InsightFace downloads its face-analysis model into ComfyUI's local models folder. **Restart ComfyUI after installing components.** The app lists any missing node or model file in a warning banner and keeps generation disabled until they are present.

## Run

The launcher defaults `COMFY_BASE_DIR` to `%USERPROFILE%\Documents\ComfyUI` and `COMFY_MAIN` to the normal ComfyUI Desktop installation. Set either environment variable before launch if your installation lives elsewhere.

Start in the desired resource mode:

```bat
start_photostudio.bat quiet
start_photostudio.bat balanced
start_photostudio.bat turbo
```

Quiet reserves 6 GB for other applications; Balanced reserves 3 GB; Turbo reserves 0.5 GB. The launcher tracks services it starts under `%LOCALAPPDATA%\VirtualFotostudio`, runs them below normal CPU priority without opening extra console windows, and logs them under `%LOCALAPPDATA%\VirtualFotostudio\logs`. The web UI listens on `127.0.0.1` only, so it is not reachable from other devices on your network. The launcher waits for ComfyUI to answer (up to 2 minutes) before opening the browser.

Use **Stop Photostudio + ComfyUI** at the top of the web UI to stop both services started by this launcher. It stops ComfyUI first and Photostudio last so the page can shut down cleanly. If ComfyUI was already running independently before Photostudio started, it is left running. `stop_photostudio.bat` provides the same safe shutdown. Unrelated processes on ports 7860 or 8188 are left untouched.

## Notes

- The detail pass makes each full photo take noticeably longer and needs more VRAM than a single pass. Use Balanced or Turbo mode for it; untick *Detail pass* for faster 896×1152 images.
- The preview is deliberately a grid of independent images, not an inaccurately labelled fixed-size collage.
- Click a preview image to open its full-size PNG in a new browser tab.
- Uploaded and previously saved reference photos appear in a thumbnail gallery; click **Use as primary** to change which photo guides likeness.
- Concept names and prompt edits are stored in `%LOCALAPPDATA%\VirtualFotostudio\concepts.json`, not in the project folder or Git.
- The **Pose freedom** help icon explains that lower values favor familiar framing, while higher values allow more varied angles and actions.
- During full and batch photoshoots, each successful image appears in the gallery as soon as it is saved.
- `Reference/` and `OUTPUT/` are local, Git-ignored data folders created as needed. They contain private reference photos and generated results; deleting them removes that local data.
- `Release ComfyUI VRAM now` calls ComfyUI's `/free` endpoint. It requests model unloading; Windows or other GPU applications can still retain their own VRAM.
- If a workflow fails (for example a missing model or no face found in the reference), the app now shows ComfyUI's own error message immediately instead of waiting for a timeout.
- Reference photos with non-Latin names (for example Cyrillic) are kept as-is; two different photos with the same name are both kept.
- Only the selected primary reference photo currently guides likeness. Other uploaded photos are retained locally and can be selected as the primary reference.
- Concept text is subject-neutral: identity comes only from the reference photo. Wardrobe in the default concepts (dresses, gowns, blazers) is just editable text in the UI.
- The UI is `photostudio_app.py`; `app.py` remains a compatibility entry point to that same UI. Generation logic is in `shoot_runner.py`. See `photostudio_walkthrough.md` for a tour of the page.
