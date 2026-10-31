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
import websocket
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
        req = urllib.request.urlopen(f"{COMFY_BASE_URL}/system_stats", timeout=3)
        return req.status == 200
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


def upload_image(image_path: str, subfolder: str = "") -> dict:
    """Upload a reference image to ComfyUI's input folder."""
    import urllib.request
    from io import BytesIO

    url = f"{COMFY_BASE_URL}/upload/image"
    filename = os.path.basename(image_path)

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
        f"\r\n--{boundary}--\r\n"
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


def get_missing_identity_requirements() -> list[str]:
    """Return identity workflow nodes absent from the currently running server."""
    try:
        with urllib.request.urlopen(f"{COMFY_BASE_URL}/object_info", timeout=10) as r:
            nodes = json.loads(r.read())
    except Exception:
        return ["ComfyUI is offline"]
    required = {"IPAdapterUnifiedLoaderFaceID", "IPAdapterFaceID"}
    return sorted(required.difference(nodes))


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


def wait_for_completion(
    prompt_id: str,
    client_id: str,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    timeout_seconds: int = 600
) -> list[bytes]:
    """
    Listen to the ComfyUI WebSocket for progress updates.
    Returns a list of generated image bytes when complete.
    """
    images = []
    done_event = threading.Event()
    start_time = time.time()

    def on_message(ws, message):
        nonlocal images
        if isinstance(message, bytes):
            return  # Skip binary preview frames

        data = json.loads(message)
        msg_type = data.get("type", "")

        if msg_type == "progress" and progress_callback:
            value = data["data"].get("value", 0)
            max_val = data["data"].get("max", 1)
            pct = int((value / max_val) * 100)
            node = data["data"].get("node", "")
            progress_callback(pct, f"Step {value}/{max_val} (node {node})")

        elif msg_type == "executing":
            if data["data"].get("prompt_id") == prompt_id and data["data"].get("node") is None:
                # Generation complete — fetch images
                history = get_history(prompt_id)
                outputs = history.get(prompt_id, {}).get("outputs", {})
                for node_id, node_output in outputs.items():
                    for img in node_output.get("images", []):
                        img_data = get_image(img["filename"], img.get("subfolder", ""), img["type"])
                        images.append(img_data)
                done_event.set()
                ws.close()

        elif msg_type == "error":
            done_event.set()
            ws.close()

    def on_error(ws, error):
        done_event.set()

    def on_open(ws):
        pass

    ws = websocket.WebSocketApp(
        f"{COMFY_WS_URL}?clientId={client_id}",
        on_message=on_message,
        on_error=on_error,
        on_open=on_open,
    )
    thread = threading.Thread(target=ws.run_forever, daemon=True)
    thread.start()

    # Poll until done or timeout
    while not done_event.is_set():
        if time.time() - start_time > timeout_seconds:
            ws.close()
            break
        time.sleep(0.5)

    return images

