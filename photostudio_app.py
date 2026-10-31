"""Local, reference-guided Virtual AI Photostudio.

Reference photos are never sent to a cloud service: they are retained under
``Reference/`` and copied to the local ComfyUI input folder only for a job.
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
import comfy_bridge
from pose_director import CONCEPT_TEMPLATES, NEGATIVE_PROMPT, PoseConfig, generate_all_pose_prompts, get_available_vibes
from workflow_builder import build_faceid_workflow

WORKSPACE = Path(__file__).parent
OUTPUT_DIR = WORKSPACE / "OUTPUT"
REFERENCE_DIR = WORKSPACE / "Reference"
OUTPUT_DIR.mkdir(exist_ok=True)
REFERENCE_DIR.mkdir(exist_ok=True)

PRESETS = {
    "Quiet background": {"steps": 16, "preview": 768, "note": "Restart in Quiet mode to reserve GPU memory for other apps."},
    "Balanced": {"steps": 22, "preview": 768, "note": "Recommended for 1024px-class full photos."},
    "Turbo": {"steps": 28, "preview": 1024, "note": "Uses most of the GPU; reserve it for focused generation."},
}
ASPECTS = {"Portrait 3:4": (3, 4), "Landscape 4:3": (4, 3)}


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "photoshoot"


def dimensions(aspect: str, short_edge: int) -> tuple[int, int]:
    if ASPECTS[aspect] == (3, 4):
        return short_edge, short_edge * 4 // 3
    return short_edge * 4 // 3, short_edge


def init_state() -> None:
    for key, value in {
        "client_id": str(uuid.uuid4()), "tiles": [None] * 9,
        "tile_prompts": [None] * 9, "is_generating": False, "last_output": None,
    }.items():
        st.session_state.setdefault(key, value)


def save_uploads(uploaded_files) -> None:
    for item in uploaded_files or []:
        extension = Path(item.name).suffix.lower() or ".jpg"
        (REFERENCE_DIR / f"{slug(Path(item.name).stem)}{extension}").write_bytes(item.getvalue())


def available_references(uploaded_files) -> list[Path]:
    save_uploads(uploaded_files)
    files = [*REFERENCE_DIR.glob("*.jpg"), *REFERENCE_DIR.glob("*.jpeg"), *REFERENCE_DIR.glob("*.png"), *REFERENCE_DIR.glob("*.webp")]
    return sorted(files, key=lambda item: item.name.lower())


def upload_reference(reference: Path) -> str:
    result = comfy_bridge.upload_image(str(reference), subfolder="photostudio")
    return f"{result.get('subfolder', '') + '/' if result.get('subfolder') else ''}{result['name']}"


def write_manifest(folder: Path, settings: dict, images: list[dict]) -> None:
    payload = {"created_at": datetime.now().isoformat(timespec="seconds"), "settings": settings, "images": images}
    (folder / "shoot_manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def generate_images(*, concept: str, concept_prompt: str, reference_name: str, checkpoint: str,
                    pose_config: PoseConfig, identity_strength: float, aspect: str, short_edge: int,
                    count: int, steps: int, preview: bool, progress, status) -> list[dict]:
    """Run one local ComfyUI job series and retain image/prompt metadata."""
    width, height = dimensions(aspect, short_edge)
    prompts = generate_all_pose_prompts(concept, pose_config, n_tiles=count)
    folder = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{slug(concept)}"
    folder.mkdir(parents=True, exist_ok=True)
    completed: list[dict] = []

    for number, (prompt, seed) in enumerate(prompts, start=1):
        if concept_prompt:
            prompt = prompt.replace(CONCEPT_TEMPLATES.get(concept, ""), concept_prompt)
        status.info(f"Generating {concept}: image {number}/{count}")
        workflow = build_faceid_workflow(
            positive_prompt=prompt, negative_prompt=NEGATIVE_PROMPT, checkpoint_name=checkpoint,
            reference_image=reference_name, width=width, height=height, steps=steps, seed=seed,
            identity_strength=identity_strength, output_prefix=f"photostudio/{slug(concept)}",
        )

        def on_progress(percent: int, message: str) -> None:
            progress.progress((number - 1 + percent / 100) / count, text=f"{concept}: {message}")

        try:
            prompt_id = comfy_bridge.queue_prompt(workflow, st.session_state.client_id)
            images = comfy_bridge.wait_for_completion(prompt_id, st.session_state.client_id, on_progress)
        except Exception as exc:
            status.error(f"Image {number} failed: {exc}")
            continue
        if not images:
            status.error(f"Image {number} returned no image. Check the ComfyUI console for the workflow error.")
            continue
        filename = f"{number:02d}_{seed}.png"
        (folder / filename).write_bytes(images[0])
        completed.append({"file": filename, "seed": seed, "prompt": prompt, "width": width, "height": height})
        if preview and number <= 9:
            st.session_state.tiles[number - 1] = images[0]
            st.session_state.tile_prompts[number - 1] = prompt
        st.session_state.last_output = images[0]

    write_manifest(folder, {
        "concept": concept, "reference": reference_name, "identity_strength": identity_strength,
        "aspect": aspect, "steps": steps, "checkpoint": checkpoint, "preview": preview,
    }, completed)
    return completed


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
    uploads = st.file_uploader("Add 1–3 clear face photos", type=["jpg", "jpeg", "png", "webp"], accept_multiple_files=True)
    refs = available_references(uploads)
    if refs:
        reference = st.selectbox("Primary likeness reference", refs, format_func=lambda item: item.name)
        st.image(str(reference), width=150, caption="Retained locally in Reference/")
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

    st.markdown("<div class='section'>4 · Generate</div>", unsafe_allow_html=True)
    ready = bool(comfy_ok and not missing_identity and checkpoint and reference)
    preview_clicked = st.button("⚡ Generate 3×3 prompt preview", disabled=not ready, use_container_width=True)
    full_clicked = st.button("📷 Run Full Photoshoot", disabled=not ready, use_container_width=True)
    batch_clicked = st.button("🗂 Run selected Batch Concepts", disabled=not ready or not batch_concepts, use_container_width=True)
    unload_clicked = st.button("Release ComfyUI VRAM now", disabled=not comfy_ok, use_container_width=True)

with right:
    st.markdown("<div class='section'>Prompt-quality preview</div>", unsafe_allow_html=True)
    progress, generation_status = st.empty(), st.empty()
    tile_columns = st.columns(3)
    for index in range(9):
        with tile_columns[index % 3]:
            if st.session_state.tiles[index]:
                st.image(st.session_state.tiles[index], caption=f"Preview {index + 1}", use_container_width=True)
    if st.session_state.last_output:
        st.download_button("Download most recent image", st.session_state.last_output, "photostudio_latest.png", "image/png", use_container_width=True)

auto_unload = st.checkbox("Auto-release ComfyUI VRAM after each job", value=True)
if unload_clicked:
    st.success("ComfyUI confirmed the model-unload request.") if comfy_bridge.unload_models() else st.warning("ComfyUI did not confirm unloading. Check its server log.")

def run_job(concepts: list[str], count: int, preview: bool) -> None:
    st.session_state.is_generating = True
    try:
        uploaded_name = upload_reference(reference)
        config = PoseConfig(vibe=vibe, chaos=chaos, custom_guidance=guidance, seed=int(seed))
        for concept in concepts:
            generate_images(concept=concept, concept_prompt=prompts[concept], reference_name=uploaded_name,
                checkpoint=checkpoint, pose_config=config, identity_strength=identity_strength, aspect=aspect,
                short_edge=PRESETS[preset]["preview"] if preview else 1152, count=count,
                steps=PRESETS[preset]["steps"] if preview else max(PRESETS[preset]["steps"], 26),
                preview=preview, progress=progress, status=generation_status)
        generation_status.success("Generation complete. Files and shoot_manifest.json were retained in OUTPUT/.")
    except Exception as exc:
        generation_status.error(f"Could not start this job: {exc}")
    finally:
        if auto_unload:
            comfy_bridge.unload_models()
        st.session_state.is_generating = False
        progress.empty()

if preview_clicked and not st.session_state.is_generating:
    st.session_state.tiles = [None] * 9
    run_job([active_concept], 9, True)
elif full_clicked and not st.session_state.is_generating:
    run_job([active_concept], int(full_count), False)
elif batch_clicked and not st.session_state.is_generating:
    run_job(batch_concepts, int(full_count), False)

st.caption("Reference photos and generated files are retained locally. Each output folder contains its prompts, seeds and settings in shoot_manifest.json.")
