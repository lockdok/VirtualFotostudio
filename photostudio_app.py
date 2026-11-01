"""Local, reference-guided Virtual AI Photostudio.

Reference photos are never sent to a cloud service: they are retained under
``Reference/`` and copied to the local ComfyUI input folder only for a job.
All generation logic lives in ``shoot_runner.py``; this file draws the UI.
"""

from __future__ import annotations

import base64
import html
import hashlib
import logging
import os
import sys
import threading
import uuid
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import comfy_bridge
from pose_director import CONCEPT_TEMPLATES, PoseConfig, get_available_vibes
from scripts import manage_services
from shoot_runner import ASPECTS, HIRES_SCALE, SDXL_NATIVE, reroll_tile, run_series, slug
from workflow_builder import upscaled_size

WORKSPACE = Path(__file__).parent
OUTPUT_DIR = WORKSPACE / "OUTPUT"
REFERENCE_DIR = WORKSPACE / "Reference"
SERVICE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "VirtualFotostudio" / "services"
OUTPUT_DIR.mkdir(exist_ok=True)
REFERENCE_DIR.mkdir(exist_ok=True)

PRESETS = {
    "Quiet background": {"steps": 16, "preview": 768, "note": "Restart in Quiet mode to reserve GPU memory for other apps."},
    "Balanced": {"steps": 22, "preview": 768, "note": "Recommended for 1024px-class full photos."},
    "Turbo": {"steps": 28, "preview": 1024, "note": "Uses most of the GPU; reserve it for focused generation."},
}


def init_state() -> None:
    for key, value in {
        "client_id": str(uuid.uuid4()), "tiles": [None] * 9, "preview": None,
        "last_output": None, "messages": [],
    }.items():
        st.session_state.setdefault(key, value)


def notify(level: str, text: str) -> None:
    """Remember a message so it survives the rerun that follows every job."""
    st.session_state.messages.append((level, text))


def save_uploads(uploaded_files) -> None:
    """Store uploads in Reference/ without ever replacing a different photo.

    Identical content is skipped; a different photo with the same name gets a
    short content hash appended.
    """
    for item in uploaded_files or []:
        data = item.getvalue()
        extension = Path(item.name).suffix.lower() or ".jpg"
        base = slug(Path(item.name).stem, default="reference")
        target = REFERENCE_DIR / f"{base}{extension}"
        if target.exists():
            if target.read_bytes() == data:
                continue
            suffix = hashlib.sha1(data).hexdigest()[:8]
            target = REFERENCE_DIR / f"{base}_{suffix}{extension}"
            counter = 2
            while target.exists() and target.read_bytes() != data:
                target = REFERENCE_DIR / f"{base}_{suffix}_{counter}{extension}"
                counter += 1
            if target.exists():
                continue
        target.write_bytes(data)


def available_references(uploaded_files) -> list[Path]:
    save_uploads(uploaded_files)
    files = [*REFERENCE_DIR.glob("*.jpg"), *REFERENCE_DIR.glob("*.jpeg"), *REFERENCE_DIR.glob("*.png"), *REFERENCE_DIR.glob("*.webp")]
    return sorted(files, key=lambda item: item.name.lower())


def upload_reference(reference: Path) -> str:
    """Copy the chosen reference into ComfyUI's input folder under an ASCII name."""
    digest = hashlib.sha1(reference.read_bytes()).hexdigest()[:12]
    upload_name = f"ref_{digest}{reference.suffix.lower() or '.jpg'}"
    result = comfy_bridge.upload_image(str(reference), subfolder="photostudio", upload_name=upload_name)
    return f"{result.get('subfolder', '') + '/' if result.get('subfolder') else ''}{result['name']}"


def show_clickable_preview(slot, data: bytes, caption: str) -> None:
    image = base64.b64encode(data).decode("ascii")
    safe_caption = html.escape(caption, quote=True)
    slot.markdown(
        f'<a href="data:image/png;base64,{image}" target="_blank" rel="noopener noreferrer" '
        f'aria-label="Open {safe_caption} at full size">'
        f'<img src="data:image/png;base64,{image}" alt="{safe_caption}" '
        'style="display:block;width:100%;height:auto;border-radius:8px"></a>'
        f'<div style="text-align:center;margin-top:4px">{safe_caption}</div>',
        unsafe_allow_html=True,
    )


def stop_photostudio() -> None:
    try:
        manage_services.stop_service("photostudio", SERVICE_DIR)
    except Exception:
        logging.getLogger(__name__).exception("Could not stop the Photostudio service")


st.set_page_config(page_title="Virtual AI Photostudio", page_icon="📸", layout="wide")
st.markdown("""<style>.stApp{background:#111;color:#eee}h1{color:#d7b46a;letter-spacing:3px}.section{border-left:3px solid #d7b46a;padding-left:9px;margin:18px 0 8px;font-weight:700}</style>""", unsafe_allow_html=True)
init_state()
st.markdown("<h1 style='text-align:center'>📸 VIRTUAL AI PHOTOSTUDIO</h1>", unsafe_allow_html=True)
st.caption("Local ComfyUI generation · session-based reference photos · no identity training")

comfy_ok = comfy_bridge.is_comfy_running()
stats = comfy_bridge.get_system_stats() if comfy_ok else {}
devices = stats.get("devices", [])
missing_identity = comfy_bridge.get_missing_identity_requirements() if comfy_ok else ["ComfyUI is offline"]
status_cols = st.columns(3)
status_cols[0].metric("ComfyUI", "Connected" if comfy_ok else "Offline")
if devices:
    total, free = devices[0].get("vram_total", 0) / 1024**3, devices[0].get("vram_free", 0) / 1024**3
    status_cols[1].metric("VRAM", f"{total - free:.1f} / {total:.0f} GB")
else:
    status_cols[1].metric("VRAM", "—")
checkpoints = comfy_bridge.get_available_checkpoints() if comfy_ok else []
status_cols[2].metric("Checkpoints", len(checkpoints))
if missing_identity:
    st.warning("Identity workflow not ready: " + ", ".join(missing_identity) + ". Install the components listed in README.md, then restart ComfyUI.")

left, right = st.columns([1, 1.25], gap="large")
with left:
    st.markdown("<div class='section'>1 · Session reference photos</div>", unsafe_allow_html=True)
    uploads = st.file_uploader("Add reference photos", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True,
                               help="Choose one primary likeness reference below. Other uploaded photos are saved locally but are not used in generation.")
    refs = available_references(uploads)
    if refs:
        reference = st.selectbox("Primary likeness reference", refs, format_func=lambda item: item.name)
        st.image(str(reference), width=150, caption="Retained locally in Reference/")
        st.caption("Only the selected primary photo currently guides likeness.")
    else:
        reference = None
        st.info("Upload a clear, front-facing reference photo to enable generation.")

    st.markdown("<div class='section'>2 · Concepts and direction</div>", unsafe_allow_html=True)
    concept_names = list(CONCEPT_TEMPLATES)
    prompts = {name: st.text_area(name, CONCEPT_TEMPLATES[name], height=92, key=f"prompt_{name}") for name in concept_names}
    active_concept = st.selectbox("Preview / full-shoot concept", concept_names)
    batch_concepts = st.multiselect("Batch Concepts", concept_names, default=[active_concept])
    vibe = st.selectbox("Vibe", get_available_vibes())
    chaos = st.slider("Pose freedom", 0.0, 1.0, 0.5, 0.05)
    guidance = st.text_input("Pose guidance", placeholder="e.g. walking, laughing, hands in pockets")
    seed = st.number_input("Seed (-1 = random)", min_value=-1, value=-1, step=1)

    st.markdown("<div class='section'>3 · Quality and likeness</div>", unsafe_allow_html=True)
    aspect = st.radio("Aspect ratio", list(ASPECTS), horizontal=True)
    identity_strength = st.slider("Identity strength", 0.25, 1.25, 0.85, 0.05, help="Higher preserves more facial likeness; lower gives styling more freedom.")
    preset = st.radio("Performance mode", list(PRESETS), horizontal=True)
    st.caption(PRESETS[preset]["note"])
    checkpoint = st.selectbox("SDXL checkpoint", checkpoints, disabled=not checkpoints) if checkpoints else None
    full_count = st.number_input("Full Photoshoot images", min_value=1, max_value=50, value=8, step=1)
    base_w, base_h = SDXL_NATIVE[aspect]
    detail_pass = st.checkbox(
        "Detail pass for full photos", value=True,
        help="Renders at SDXL's native size, then enlarges and refines the image with a second pass. "
             "Sharper and cleaner than rendering large in one go, but each image takes longer and needs more VRAM.")
    if detail_pass:
        out_w, out_h = upscaled_size(base_w, base_h, HIRES_SCALE)
        st.caption(f"Full photos: {base_w}×{base_h} base, refined to {out_w}×{out_h}. "
                   "Use Balanced or Turbo mode; Quiet mode (6 GB reserved) may be slow or run out of memory at this size.")
    else:
        st.caption(f"Full photos: {base_w}×{base_h} (single pass).")

    st.markdown("<div class='section'>4 · Generate</div>", unsafe_allow_html=True)
    ready = bool(comfy_ok and not missing_identity and checkpoint and reference)
    preview_clicked = st.button("⚡ Generate 3×3 prompt preview", disabled=not ready, use_container_width=True)
    full_clicked = st.button("📷 Run Full Photoshoot", disabled=not ready, use_container_width=True)
    batch_clicked = st.button("🗂 Run selected Batch Concepts", disabled=not ready or not batch_concepts, use_container_width=True)
    unload_clicked = st.button("Release ComfyUI VRAM now", disabled=not comfy_ok, use_container_width=True)
    stop_clicked = st.button(
        "⏹ Stop Photostudio",
        disabled=not (SERVICE_DIR / "photostudio.json").is_file(),
        use_container_width=True,
        help="Stops this Photostudio server only. ComfyUI will keep running.",
    )
    st.caption("Stop Photostudio here without closing ComfyUI.")
    st.caption("Leave the page alone while a job runs: changing a setting restarts the script and interrupts it.")
    auto_unload = st.checkbox("Auto-release ComfyUI VRAM after each job", value=True,
                              help="Frees GPU memory after every job. Turn it off for faster consecutive re-rolls.")

with right:
    st.markdown("<div class='section'>Prompt-quality preview</div>", unsafe_allow_html=True)
    progress, generation_status, messages_slot = st.empty(), st.empty(), st.empty()
    if st.session_state.messages:
        with messages_slot.container():
            for level, text in st.session_state.messages:
                getattr(st, level)(text)

    record = st.session_state.preview
    tile_columns = st.columns(3)
    tile_slots = []
    reroll_index = None
    for index in range(9):
        with tile_columns[index % 3]:
            slot = st.empty()
            tile_slots.append(slot)
            if st.session_state.tiles[index]:
                entry = record.images.get(index) if record else None
                caption = f"Preview {index + 1}" + (f" · seed {entry['seed']}" if entry else "")
                show_clickable_preview(slot, st.session_state.tiles[index], caption)
                if st.button("🔄 Re-roll", key=f"reroll_{index}", disabled=not (ready and record), use_container_width=True,
                             help="New seed and a new pose for this image only."):
                    reroll_index = index
    if st.session_state.last_output:
        st.download_button("Download most recent image", st.session_state.last_output, "photostudio_latest.png", "image/png", use_container_width=True)

if unload_clicked:
    st.success("ComfyUI confirmed the model-unload request.") if comfy_bridge.unload_models() else st.warning("ComfyUI did not confirm unloading. Check its server log.")

if stop_clicked:
    st.success("Photostudio is shutting down. ComfyUI will remain running.")
    threading.Timer(1.5, stop_photostudio).start()


def start_job() -> None:
    st.session_state.messages = []
    messages_slot.empty()


def finish_job() -> None:
    if auto_unload and not comfy_bridge.unload_models():
        notify("warning", "ComfyUI did not confirm VRAM release. Check its server log.")
    progress.empty()


def run_job(concepts: list[str], count: int, preview: bool) -> None:
    start_job()
    try:
        uploaded_name = upload_reference(reference)
        config = PoseConfig(vibe=vibe, chaos=chaos, custom_guidance=guidance, seed=int(seed))

        def on_image(index: int, data: bytes, entry: dict) -> None:
            st.session_state.last_output = data
            if preview:
                st.session_state.tiles[index] = data
                show_clickable_preview(tile_slots[index], data, f"Preview {index + 1} · seed {entry['seed']}")

        def on_error(message: str) -> None:
            generation_status.error(message)
            notify("error", message)

        for concept in concepts:
            result = run_series(
                output_dir=OUTPUT_DIR, concept=concept, concept_prompt=prompts[concept], reference_name=uploaded_name,
                checkpoint=checkpoint, pose_config=config, identity_strength=identity_strength, aspect=aspect,
                short_edge=PRESETS[preset]["preview"], count=count,
                base_size=None if preview else SDXL_NATIVE[aspect],
                hires_scale=HIRES_SCALE if (detail_pass and not preview) else 0.0,
                steps=PRESETS[preset]["steps"] if preview else max(PRESETS[preset]["steps"], 26),
                preview=preview, client_id=st.session_state.client_id,
                on_status=generation_status.info,
                on_progress=lambda frac, text: progress.progress(min(max(frac, 0.0), 1.0), text=text),
                on_image=on_image, on_error=on_error,
            )
            if preview:
                st.session_state.preview = result
            done = len(result.images)
            notify("success" if done == count else "warning",
                   f"{concept}: {done}/{count} images saved to OUTPUT/{result.folder.name} (with shoot_manifest.json).")
    except Exception as exc:
        notify("error", f"Could not start this job: {exc}")
    finally:
        finish_job()
    st.rerun()


def run_reroll(index: int) -> None:
    start_job()
    try:
        generation_status.info(f"Re-rolling preview {index + 1}…")
        data, entry = reroll_tile(
            st.session_state.preview, index, client_id=st.session_state.client_id,
            on_progress=lambda pct, text: progress.progress(min(max(pct / 100, 0.0), 1.0), text=f"Re-roll {index + 1}: {text}"),
        )
        st.session_state.tiles[index] = data
        st.session_state.last_output = data
        notify("success", f"Preview {index + 1} re-rolled (seed {entry['seed']}). The previous image stays in the output folder.")
    except Exception as exc:
        notify("error", f"Re-roll failed: {exc}")
    finally:
        finish_job()
    st.rerun()


if preview_clicked:
    st.session_state.tiles, st.session_state.preview = [None] * 9, None
    run_job([active_concept], 9, True)
elif full_clicked:
    run_job([active_concept], int(full_count), False)
elif batch_clicked:
    run_job(batch_concepts, int(full_count), False)
elif reroll_index is not None:
    run_reroll(reroll_index)

st.caption("Reference photos and generated files are retained locally. Each output folder contains its prompts, seeds and settings in shoot_manifest.json.")
