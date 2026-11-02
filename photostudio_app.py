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
from pose_director import PoseConfig, get_available_vibes
from scripts import concept_settings, manage_services
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
        "gallery_images": [None] * 9, "gallery_is_preview": False,
        "primary_reference": None, "last_output": None, "messages": [],
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


def stop_photostudio_and_comfy() -> None:
    try:
        manage_services.stop_tracked_services(SERVICE_DIR)
    except Exception:
        logging.getLogger(__name__).exception("Could not stop the launcher-owned services")


st.set_page_config(page_title="Virtual AI Photostudio", page_icon="📸", layout="wide")
st.markdown("""<style>.stApp{background:#111;color:#eee}h1{color:#d7b46a;letter-spacing:3px}.section{border-left:3px solid #d7b46a;padding-left:9px;margin:18px 0 8px;font-weight:700}</style>""", unsafe_allow_html=True)
init_state()
try:
    saved_concepts = concept_settings.load_concepts()
    concepts_loaded = True
except (OSError, ValueError) as exc:
    saved_concepts = concept_settings.default_concepts()
    concepts_loaded = False
    st.error(f"Could not load local concept settings: {exc}")

title_col, stop_col = st.columns([5, 1])
with title_col:
    st.markdown("<h1 style='text-align:center'>📸 VIRTUAL AI PHOTOSTUDIO</h1>", unsafe_allow_html=True)
with stop_col:
    stop_clicked = st.button(
        "⏹ Stop Photostudio + ComfyUI",
        disabled=not any((SERVICE_DIR / f"{service}.json").is_file() for service in ("photostudio", "comfy")),
        use_container_width=True,
        help="Stops only services started by this launcher. A ComfyUI instance already running independently is left alone.",
    )
    st.caption("Stops launcher-owned services")
if stop_clicked:
    st.info("Stopping launcher-owned Photostudio and ComfyUI services.")
    threading.Timer(1.0, stop_photostudio_and_comfy).start()
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
                               help="Upload one or more local photos, then click a thumbnail to choose the primary likeness reference.")
    refs = available_references(uploads)
    if refs:
        reference_paths = [str(path) for path in refs]
        if st.session_state.primary_reference not in reference_paths:
            st.session_state.primary_reference = reference_paths[0]
        st.caption("Click a photo to select it as the primary likeness reference.")
        reference_columns = st.columns(4)
        for index, path in enumerate(refs):
            path_text = str(path)
            with reference_columns[index % len(reference_columns)]:
                st.image(path_text, use_container_width=True)
                selected = path_text == st.session_state.primary_reference
                if st.button(
                    "✓ Primary" if selected else "Use as primary",
                    key=f"reference_{hashlib.sha1(path_text.encode()).hexdigest()[:12]}",
                    disabled=selected,
                    use_container_width=True,
                ):
                    st.session_state.primary_reference = path_text
                    st.rerun()
        reference = Path(st.session_state.primary_reference)
    else:
        reference = None
        st.info("Upload a clear, front-facing reference photo to enable generation.")

    st.markdown("<div class='section'>2 · Concepts and direction</div>", unsafe_allow_html=True)
    concept_configs = {}
    with st.expander("Rename concepts and edit their prompts"):
        st.caption("Custom names and prompts are saved locally and kept when Photostudio restarts.")
        for concept_id, saved in saved_concepts.items():
            name = st.text_input("Concept name", saved["name"], key=f"concept_name_{concept_id}")
            prompt = st.text_area("Prompt", saved["prompt"], height=92, key=f"concept_prompt_{concept_id}")
            concept_configs[concept_id] = {"name": name.strip(), "prompt": prompt}
    if not concept_configs:
        concept_configs = saved_concepts
    concept_names = [value["name"] for value in concept_configs.values()]
    concepts_valid = concepts_loaded and all(concept_names) and len({name.casefold() for name in concept_names}) == len(concept_names)
    if concepts_loaded and not concepts_valid:
        st.error("Concept names must be non-empty and unique. Update the names before generating.")
    if concepts_valid and concept_configs != saved_concepts:
        try:
            concept_settings.save_concepts(concept_configs)
            st.caption("Concept names and prompts are saved locally.")
        except OSError as exc:
            concepts_valid = False
            st.error(f"Could not save your concept settings: {exc}")

    concept_ids = list(concept_configs)
    active_concept = st.selectbox(
        "Preview / full-shoot concept", concept_ids, format_func=lambda key: concept_configs[key]["name"]
    )
    batch_concepts = st.multiselect(
        "Batch Concepts", concept_ids, default=[active_concept],
        format_func=lambda key: concept_configs[key]["name"],
    )
    vibe = st.selectbox("Vibe", get_available_vibes())
    chaos = st.slider(
        "Pose freedom", 0.0, 1.0, 0.5, 0.05,
        help="Lower values favor familiar, straightforward framing and poses. Higher values allow more varied camera angles and actions.",
    )
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
    ready = bool(comfy_ok and not missing_identity and checkpoint and reference and concepts_valid)
    preview_clicked = st.button("⚡ Generate 3×3 prompt preview", disabled=not ready, use_container_width=True)
    full_clicked = st.button("📷 Run Full Photoshoot", disabled=not ready, use_container_width=True)
    batch_clicked = st.button("🗂 Run selected Batch Concepts", disabled=not ready or not batch_concepts, use_container_width=True)
    unload_clicked = st.button("Release ComfyUI VRAM now", disabled=not comfy_ok, use_container_width=True)
    st.caption("Leave the page alone while a job runs: changing a setting restarts the script and interrupts it.")
    auto_unload = st.checkbox("Auto-release ComfyUI VRAM after each job", value=True,
                              help="Frees GPU memory after every job. Turn it off for faster consecutive re-rolls.")

requested_gallery_size = 9
if full_clicked:
    requested_gallery_size = int(full_count)
elif batch_clicked:
    requested_gallery_size = int(full_count) * len(batch_concepts)
if preview_clicked or full_clicked or batch_clicked:
    gallery_size = requested_gallery_size
    st.session_state.gallery_images = [None] * gallery_size
    st.session_state.gallery_is_preview = preview_clicked
    if preview_clicked:
        st.session_state.tiles, st.session_state.preview = [None] * 9, None
    gallery_images = st.session_state.gallery_images
else:
    gallery_images = st.session_state.gallery_images
    gallery_size = max(9, len(gallery_images))
gallery_images.extend([None] * (gallery_size - len(gallery_images)))

with right:
    st.markdown("<div class='section'>Generated photos</div>", unsafe_allow_html=True)
    progress, generation_status, messages_slot = st.empty(), st.empty(), st.empty()
    if st.session_state.messages:
        with messages_slot.container():
            for level, text in st.session_state.messages:
                getattr(st, level)(text)

    record = st.session_state.preview
    gallery_columns = st.columns(3)
    gallery_slots = []
    reroll_index = None
    for index in range(gallery_size):
        with gallery_columns[index % 3]:
            slot = st.empty()
            gallery_slots.append(slot)
            image_record = gallery_images[index]
            if image_record:
                if "data" in image_record:
                    show_clickable_preview(slot, image_record["data"], image_record["caption"])
                elif Path(image_record["path"]).is_file():
                    slot.image(image_record["path"], caption=image_record["caption"], use_container_width=True)
                else:
                    slot.warning("Saved image is no longer available.")
            if st.session_state.gallery_is_preview and index < 9 and st.session_state.tiles[index]:
                entry = record.images.get(index) if record else None
                caption = f"Preview {index + 1}" + (f" · seed {entry['seed']}" if entry else "")
                if st.button("🔄 Re-roll", key=f"reroll_{index}", disabled=not (ready and record), use_container_width=True,
                             help="New seed and a new pose for this image only."):
                    reroll_index = index
    if st.session_state.last_output:
        st.download_button("Download most recent image", st.session_state.last_output, "photostudio_latest.png", "image/png", use_container_width=True)

if unload_clicked:
    st.success("ComfyUI confirmed the model-unload request.") if comfy_bridge.unload_models() else st.warning("ComfyUI did not confirm unloading. Check its server log.")

def start_job() -> None:
    st.session_state.messages = []
    messages_slot.empty()


def finish_job() -> None:
    if auto_unload and not comfy_bridge.unload_models():
        notify("warning", "ComfyUI did not confirm VRAM release. Check its server log.")
    progress.empty()


def run_job(concepts: list[str], count: int, preview: bool) -> None:
    total_images = len(concepts) * count
    st.session_state.gallery_images = [None] * total_images
    st.session_state.gallery_is_preview = preview
    if preview:
        st.session_state.tiles = [None] * 9
    start_job()
    try:
        uploaded_name = upload_reference(reference)
        config = PoseConfig(vibe=vibe, chaos=chaos, custom_guidance=guidance, seed=int(seed))

        def on_error(message: str) -> None:
            generation_status.error(message)
            notify("error", message)

        for concept_number, concept_id in enumerate(concepts):
            concept_name = concept_configs[concept_id]["name"]
            concept_prompt = concept_configs[concept_id]["prompt"]
            image_offset = concept_number * count

            def on_image(index: int, data: bytes, entry: dict, *, offset=image_offset,
                         name=concept_name) -> None:
                gallery_index = offset + index
                caption = (
                    f"Preview {index + 1} · seed {entry['seed']}"
                    if preview else f"{name} · image {index + 1} · seed {entry['seed']}"
                )
                st.session_state.last_output = data
                if preview:
                    st.session_state.gallery_images[gallery_index] = {"data": data, "caption": caption}
                    st.session_state.tiles[index] = data
                    show_clickable_preview(gallery_slots[gallery_index], data, caption)
                else:
                    image_path = Path(entry["path"])
                    st.session_state.gallery_images[gallery_index] = {
                        "path": str(image_path), "caption": caption,
                    }
                    gallery_slots[gallery_index].image(
                        str(image_path), caption=caption, use_container_width=True,
                    )

            result = run_series(
                output_dir=OUTPUT_DIR, concept=concept_name, concept_prompt=concept_prompt, reference_name=uploaded_name,
                checkpoint=checkpoint, pose_config=config, identity_strength=identity_strength, aspect=aspect,
                short_edge=PRESETS[preset]["preview"], count=count,
                base_size=None if preview else SDXL_NATIVE[aspect],
                hires_scale=HIRES_SCALE if (detail_pass and not preview) else 0.0,
                steps=PRESETS[preset]["steps"] if preview else max(PRESETS[preset]["steps"], 26),
                preview=preview, client_id=st.session_state.client_id,
                on_status=lambda text: generation_status.info(f"{concept_name}: {text}"),
                on_progress=lambda frac, text, offset=concept_number: progress.progress(
                    min(max((offset + frac) / len(concepts), 0.0), 1.0), text=text
                ),
                on_image=on_image, on_error=on_error,
            )
            if preview:
                st.session_state.preview = result
            done = len(result.images)
            notify("success" if done == count else "warning",
                   f"{concept_name}: {done}/{count} images saved to OUTPUT/{result.folder.name} (with shoot_manifest.json).")
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
        caption = f"Preview {index + 1} · seed {entry['seed']}"
        st.session_state.gallery_images[index] = {"data": data, "caption": caption}
        show_clickable_preview(gallery_slots[index], data, caption)
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
