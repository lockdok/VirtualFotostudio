"""
ComfyUI API Bridge
Handles all communication with the local ComfyUI headless instance.
Supports: image upload, prompt queuing, WebSocket progress monitoring, and output retrieval.
"""

import json
import os
import time
import uuid
import urllib.request
import urllib.parse
import mimetypes
import threading
from pathlib import Path
from typing import Optional, Callable


COMFY_HOST = "127.0.0.1"
COMFY_PORT = 8188
COMFY_BASE_URL = f"http://{COMFY_HOST}:{COMFY_PORT}"
COMFY_WS_URL = f"ws://{COMFY_HOST}:{COMFY_PORT}/ws"


def is_comfy_running() -> bool:
    """Check if ComfyUI is up and accepting connections."""
    try:
        with urllib.request.urlopen(f"{COMFY_BASE_URL}/system_stats", timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def get_system_stats() -> dict:
    """Return ComfyUI system stats including VRAM and GPU info."""
    try:
        with urllib.request.urlopen(f"{COMFY_BASE_URL}/system_stats", timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def get_available_checkpoints() -> list[str]:
    """Scan ComfyUI's models/checkpoints folder and return available model names."""
    try:
        with urllib.request.urlopen(f"{COMFY_BASE_URL}/object_info/CheckpointLoaderSimple", timeout=5) as r:
            data = json.loads(r.read())
            models = data["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
            return models
    except Exception:
        # Fallback: scan filesystem
        comfy_base = Path(os.environ.get("COMFY_BASE_DIR", Path.home() / "Documents" / "ComfyUI"))
        ckpt_dir = comfy_base / "models" / "checkpoints"
        if ckpt_dir.exists():
            return [f.name for f in ckpt_dir.iterdir() if f.suffix in (".safetensors", ".ckpt")]
        return []


def upload_image(image_path: str, subfolder: str = "", upload_name: Optional[str] = None) -> dict:
    """Upload a reference image to ComfyUI's input folder.

    ``upload_name`` lets the caller send an ASCII-safe filename even when the
    local file has a non-Latin name.
    """
    filename = upload_name or os.path.basename(image_path)
    with open(image_path, "rb") as f:
        image_data = f.read()
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return _upload_image_bytes(image_data, filename, content_type, subfolder)


def upload_image_bytes(image_data: bytes, filename: str, content_type: str = "image/jpeg", subfolder: str = "") -> dict:
    """Upload an in-memory Streamlit image to ComfyUI's local input folder."""
    return _upload_image_bytes(image_data, filename, content_type, subfolder)


def _upload_image_bytes(image_data: bytes, filename: str, content_type: str, subfolder: str = "") -> dict:
    """Shared multipart implementation for local and in-memory reference files."""
    url = f"{COMFY_BASE_URL}/upload/image"

    boundary = "----PythonFormBoundary" + uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + image_data + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue'
        + (
            f"\r\n--{boundary}\r\n"
            f'Content-Disposition: form-data; name="subfolder"\r\n\r\n{subfolder}'
            if subfolder else ""
        )
        + f"\r\n--{boundary}--\r\n"
    ).encode()

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def unload_models() -> bool:
    """Ask ComfyUI to release loaded models and cached GPU memory."""
    payload = json.dumps({"unload_models": True, "free_memory": True}).encode()
    req = urllib.request.Request(
        f"{COMFY_BASE_URL}/free",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


FACEID_ADAPTER_FILE = "ip-adapter-faceid-plusv2_sdxl.bin"
FACEID_LORA_FILE = "ip-adapter-faceid-plusv2_sdxl_lora.safetensors"
PLUS_FACE_ADAPTER_FILE = "ip-adapter-plus-face_sdxl_vit-h.safetensors"
CLIP_VISION_HINT = "vit-h-14-laion2b"  # matched case-insensitively against clip_vision filenames
REQUIRED_IDENTITY_NODES = {
    "IPAdapterModelLoader",
    "IPAdapterUnifiedLoader",
    "IPAdapterAdvanced",
    "IPAdapterUnifiedLoaderFaceID",
    "IPAdapterFaceID",
    "LoraLoader",
    "CLIPVisionLoader",
}


def _node_choices(nodes: dict, node: str, field: str) -> Optional[list[str]]:
    """Return the file choices ComfyUI lists for a loader input, or None if unknown."""
    try:
        choices = nodes[node]["input"]["required"][field][0]
    except (KeyError, IndexError, TypeError):
        return None
    return choices if isinstance(choices, list) else None


def _has_file(choices: Optional[list[str]], wanted: str) -> bool:
    """True if ``wanted`` is listed (also inside subfolders). Unknown lists never block."""
    if choices is None:
        return True
    wanted = wanted.lower()
    return any(Path(c.replace("\\", "/")).name.lower() == wanted for c in choices)


def get_missing_identity_requirements() -> list[str]:
    """Return identity-workflow nodes and model files the running server lacks.

    Checks the FaceID custom nodes first; if they are present it also verifies
    the adapter, LoRA and CLIP Vision files so the UI reports a missing download
    up front instead of failing partway through a job.
    """
    try:
        with urllib.request.urlopen(f"{COMFY_BASE_URL}/object_info", timeout=10) as r:
            nodes = json.loads(r.read())
    except Exception:
        return ["ComfyUI is offline"]

    missing = sorted(REQUIRED_IDENTITY_NODES.difference(nodes))
    if missing:
        return missing

    adapter_choices = _node_choices(nodes, "IPAdapterModelLoader", "ipadapter_file")
    if not _has_file(adapter_choices, FACEID_ADAPTER_FILE):
        missing.append(f"model file {FACEID_ADAPTER_FILE} (models/ipadapter)")
    if not _has_file(adapter_choices, PLUS_FACE_ADAPTER_FILE):
        missing.append(f"model file {PLUS_FACE_ADAPTER_FILE} (models/ipadapter)")
    if not _has_file(_node_choices(nodes, "LoraLoader", "lora_name"), FACEID_LORA_FILE):
        missing.append(f"model file {FACEID_LORA_FILE} (models/loras)")
    clip_choices = _node_choices(nodes, "CLIPVisionLoader", "clip_name")
    if clip_choices is not None and not any(CLIP_VISION_HINT in c.lower() for c in clip_choices):
        missing.append("CLIP Vision ViT-H model (models/clip_vision)")
    return missing


def queue_prompt(workflow: dict, client_id: str) -> str:
    """Submit a workflow to ComfyUI and return the prompt_id."""
    payload = json.dumps({"prompt": workflow, "client_id": client_id}).encode()
    req = urllib.request.Request(
        f"{COMFY_BASE_URL}/prompt",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["prompt_id"]


def get_history(prompt_id: str) -> dict:
    """Fetch completed generation results from ComfyUI history."""
    with urllib.request.urlopen(f"{COMFY_BASE_URL}/history/{prompt_id}", timeout=10) as r:
        return json.loads(r.read())


def get_image(filename: str, subfolder: str, folder_type: str) -> bytes:
    """Download a generated image from ComfyUI output."""
    params = urllib.parse.urlencode({
        "filename": filename,
        "subfolder": subfolder,
        "type": folder_type,
    })
    with urllib.request.urlopen(f"{COMFY_BASE_URL}/view?{params}", timeout=30) as r:
        return r.read()


def _extract_error(status: dict) -> str:
    """Pull a readable message out of a failed ComfyUI history ``status`` block."""
    for kind, payload in status.get("messages", []):
        if kind == "execution_error":
            node = payload.get("node_type") or payload.get("node_id") or "unknown node"
            return f"{node}: {payload.get('exception_message', 'execution error').strip()}"
    return "ComfyUI reported an execution error (see its console for details)."


def _start_progress_listener(client_id: str, prompt_id: str, progress_callback):
    """Best-effort websocket listener used only for progress bars.

    Completion is never decided here, so a missed or late connection can no
    longer hang a job; at worst the progress bar stays still.
    """
    if progress_callback is None:
        return None
    try:
        import websocket  # websocket-client
    except ImportError:
        return None

    def on_message(ws, message):
        if isinstance(message, bytes):
            return
        try:
            data = json.loads(message)
        except ValueError:
            return
        if data.get("type") != "progress":
            return
        payload = data.get("data", {})
        if payload.get("prompt_id") not in (None, prompt_id):
            return
        value, max_val = payload.get("value", 0), max(payload.get("max", 1), 1)
        progress_callback(int(value / max_val * 100), f"Step {value}/{max_val}")

    ws = websocket.WebSocketApp(f"{COMFY_WS_URL}?clientId={client_id}", on_message=on_message)
    threading.Thread(target=ws.run_forever, daemon=True).start()
    return ws


def wait_for_completion(
    prompt_id: str,
    client_id: str,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    timeout_seconds: int = 600,
    poll_interval: float = 0.5,
) -> list[bytes]:
    """Wait for a queued prompt and return its generated images as bytes.

    Completion is detected by polling ``/history/<prompt_id>``, which works even
    if the job finished before any websocket connected.  Raises ``RuntimeError``
    with ComfyUI's own message if the workflow fails and ``TimeoutError`` if it
    does not finish in ``timeout_seconds``.
    """
    ws = _start_progress_listener(client_id, prompt_id, progress_callback)
    deadline = time.time() + timeout_seconds
    try:
        while time.time() < deadline:
            entry = get_history(prompt_id).get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(_extract_error(status))
                outputs = entry.get("outputs", {})
                if outputs or status.get("completed"):
                    images = []
                    for node_output in outputs.values():
                        for img in node_output.get("images", []):
                            images.append(get_image(img["filename"], img.get("subfolder", ""), img["type"]))
                    return images
            time.sleep(poll_interval)
        raise TimeoutError(f"ComfyUI did not finish prompt {prompt_id} within {timeout_seconds}s.")
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
