"""
Virtual AI Photostudio - Main Web Application
A clean, single-page Streamlit web interface at http://localhost:7860

Features:
  1. Reference Photos upload
  2-5. Four Concept Prompts (pre-filled, fully editable)
  6. Semicontrollable Pose Director (Vibe, Chaos, Custom Keywords)
  7. Resource Controller (VRAM Cap, CPU Priority, Auto-Unload)
  ⚡ Generate 3x3 Preview Collage (3072x3072)
  🔄 Per-tile Re-roll
  🚀 Run Full Photoshoot (save individual high-res shots)
"""

import os
import sys
import uuid
import time
import shutil
import threading
import subprocess
from io import BytesIO
from pathlib import Path

import streamlit as st
from PIL import Image

# ── Add project directory to path ────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

import comfy_bridge
from pose_director import (
    PoseConfig, generate_all_pose_prompts, get_available_vibes,
    CONCEPT_TEMPLATES, NEGATIVE_PROMPT,
)
from compositor import create_empty_canvas, composite_tile, save_collage, canvas_to_bytes
from workflow_builder import build_txt2img_workflow

# ── Workspace directories ─────────────────────────────────────────────────────
WORKSPACE = Path(__file__).parent
OUTPUT_DIR = WORKSPACE / "OUTPUT"
REFERENCE_DIR = WORKSPACE / "Reference"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Virtual AI Photostudio",
    page_icon="📸",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS Styling ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Dark editorial theme */
    .stApp { background-color: #111111; color: #f0f0f0; }
    .stTextArea textarea { background-color: #1a1a1a; color: #f0f0f0; border: 1px solid #333; }
    .stButton button {
        width: 100%; font-size: 16px; font-weight: bold;
        padding: 12px; border-radius: 6px; border: none;
    }
    .generate-btn button { background-color: #c8a050; color: #111; }
    .fullshoot-btn button { background-color: #2a7a2a; color: #fff; }
    .stop-btn button { background-color: #7a2a2a; color: #fff; }
    .reroll-btn button { background-color: #1a3a5a; color: #fff; font-size: 12px; padding: 4px; }
    h1 { color: #c8a050; letter-spacing: 4px; }
    h2, h3 { color: #ddd; }
    .section-header {
        border-left: 3px solid #c8a050;
        padding-left: 10px;
        margin: 16px 0 8px 0;
        font-weight: bold;
        color: #ddd;
    }
    .status-ok { color: #4caf50; font-weight: bold; }
    .status-err { color: #f44336; font-weight: bold; }
    .status-warn { color: #ff9800; font-weight: bold; }
    .tile-container { position: relative; }
</style>
""", unsafe_allow_html=True)


# ── Session State Initialisation ──────────────────────────────────────────────
def init_state():
    defaults = {
        "tiles": [None] * 9,          # bytes for each tile image
        "tile_seeds": [-1] * 9,        # seed used for each tile (for re-roll tracking)
        "canvas": None,                # current full collage PIL Image
        "generating": False,
        "client_id": str(uuid.uuid4()),
        "active_concept": "Golden Hour Botanical",
        "active_reference": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


# ── Helper: ComfyUI Status ────────────────────────────────────────────────────
def get_comfy_status():
    if comfy_bridge.is_comfy_running():
        stats = comfy_bridge.get_system_stats()
        devices = stats.get("devices", [{}])
        if devices:
            vram_total = devices[0].get("vram_total", 0) / (1024**3)
            vram_free = devices[0].get("vram_free", 0) / (1024**3)
            vram_used = vram_total - vram_free
            return True, vram_total, vram_used
    return False, 0, 0


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("<h1 style='text-align:center; margin-bottom:4px;'>📸 VIRTUAL AI PHOTOSTUDIO</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center; color:#888; letter-spacing:2px; margin-top:0;'>Agentic · ComfyUI · RTX 4070 Ti</p>", unsafe_allow_html=True)

# ComfyUI status bar
comfy_ok, vram_total, vram_used = get_comfy_status()
col_s1, col_s2, col_s3 = st.columns([1, 1, 1])
with col_s1:
    if comfy_ok:
        st.markdown(f"<span class='status-ok'>● ComfyUI Connected</span>", unsafe_allow_html=True)
    else:
        st.markdown("<span class='status-err'>● ComfyUI Offline — Start ComfyUI first</span>", unsafe_allow_html=True)
with col_s2:
    if comfy_ok and vram_total > 0:
        st.markdown(f"<span class='status-ok'>🎮 VRAM: {vram_used:.1f} / {vram_total:.0f} GB</span>", unsafe_allow_html=True)
with col_s3:
    checkpoints = comfy_bridge.get_available_checkpoints() if comfy_ok else []
    if checkpoints:
        st.markdown(f"<span class='status-ok'>🧩 {len(checkpoints)} checkpoint(s) available</span>", unsafe_allow_html=True)
    elif comfy_ok:
        st.markdown("<span class='status-warn'>⚠ No checkpoints found — please download a model</span>", unsafe_allow_html=True)

st.divider()

# ── Main Layout: Left Controls | Right Preview ────────────────────────────────
col_controls, col_preview = st.columns([1, 1.4], gap="large")

with col_controls:

    # ─── 1. Reference Photos ─────────────────────────────────────────────────
    st.markdown("<div class='section-header'>1 · Reference Photos</div>", unsafe_allow_html=True)

    # Show pre-loaded reference photos from Reference/ folder
    ref_files = list(REFERENCE_DIR.glob("*.jpg")) + list(REFERENCE_DIR.glob("*.png")) if REFERENCE_DIR.exists() else []
    uploaded_files = st.file_uploader(
        "Upload new reference photos (or use pre-loaded ones below)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    if uploaded_files:
        all_refs = uploaded_files
        st.caption(f"✓ {len(uploaded_files)} uploaded reference photo(s)")
    elif ref_files:
        all_refs = ref_files
        st.caption(f"✓ Using {len(ref_files)} pre-loaded reference photo(s) from Reference/ folder")
        # Show thumbnails
        thumb_cols = st.columns(min(len(ref_files), 4))
        for i, ref in enumerate(ref_files[:4]):
            with thumb_cols[i]:
                st.image(str(ref), width=80)
    else:
        all_refs = []
        st.warning("No reference photos found. Please upload reference images.")

    st.divider()

    # ─── 2-5. Concept Prompts ────────────────────────────────────────────────
    st.markdown("<div class='section-header'>2–5 · Photoshoot Concept Prompts</div>", unsafe_allow_html=True)

    concept_names = list(CONCEPT_TEMPLATES.keys())
    concept_prompts = {}
    active_tab = st.tabs(concept_names)

    for tab, name in zip(active_tab, concept_names):
        with tab:
            concept_prompts[name] = st.text_area(
                label=name,
                value=CONCEPT_TEMPLATES[name],
                height=100,
                key=f"concept_{name}",
                label_visibility="collapsed",
            )

    # Concept selector for generation
    active_concept = st.selectbox("Active concept to generate:", concept_names, key="concept_select")
    st.session_state.active_concept = active_concept

    st.divider()

    # ─── 6. Semicontrollable Pose Director ───────────────────────────────────
    st.markdown("<div class='section-header'>6 · Pose Director</div>", unsafe_allow_html=True)

    vibe = st.selectbox("Vibe / Energy:", get_available_vibes(), index=0, key="vibe")
    chaos = st.slider("Pose Freedom (Chaos):", 0.0, 1.0, 0.5, step=0.05,
                       help="Low = structured studio poses | High = unscripted candid moments")
    custom_guidance = st.text_input(
        "Custom Pose Keywords (optional):",
        placeholder="e.g. laughing, hands in pockets, looking over shoulder...",
        key="custom_guidance",
    )
    base_seed = st.number_input("Seed (-1 = random):", value=-1, min_value=-1, step=1, key="seed")

    st.divider()

    # ─── 7. Resource Controller ──────────────────────────────────────────────
    st.markdown("<div class='section-header'>7 · Resource Controller</div>", unsafe_allow_html=True)

    preset = st.radio(
        "Performance Preset:",
        ["🌙 Quiet Background", "⚖️ Balanced", "⚡ Turbo"],
        horizontal=True,
        index=0,
        key="perf_preset",
    )

    vram_cap_map = {"🌙 Quiet Background": 5.0, "⚖️ Balanced": 8.0, "⚡ Turbo": 11.5}
    vram_cap_default = vram_cap_map[preset]

    vram_cap = st.slider(
        f"VRAM Cap (of {vram_total:.0f if vram_total > 0 else 12} GB):",
        min_value=2.0,
        max_value=max(vram_total if vram_total > 0 else 12.0, 4.0),
        value=vram_cap_default,
        step=0.5,
        help="Caps GPU VRAM to leave the rest free for your other apps.",
        key="vram_cap",
    )

    auto_unload = st.checkbox("Auto-unload VRAM on idle", value=True, key="auto_unload")
    quality_steps = st.slider("Generation Steps:", 10, 40, 20, help="More steps = better quality, slower generation")

    st.divider()

    # ─── Checkpoint Selection ─────────────────────────────────────────────────
    st.markdown("<div class='section-header'>Model Checkpoint</div>", unsafe_allow_html=True)
    if checkpoints:
        selected_ckpt = st.selectbox("Base model:", checkpoints, key="checkpoint")
    else:
        selected_ckpt = None
        st.warning(
            "No checkpoints found! Download a model (e.g. Juggernaut XL) "
            "to `%USERPROFILE%/Documents/ComfyUI/models/checkpoints/`"
        )

    # ─── Action Buttons ───────────────────────────────────────────────────────
    st.markdown("")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='generate-btn'>", unsafe_allow_html=True)
        gen_preview = st.button("⚡ Generate 3×3 Preview", disabled=(not comfy_ok or not selected_ckpt), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        st.markdown("<div class='fullshoot-btn'>", unsafe_allow_html=True)
        run_full = st.button("🚀 Run Full Photoshoot", disabled=(not comfy_ok or not selected_ckpt), use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)


# ── Right Panel: Preview Grid ─────────────────────────────────────────────────
with col_preview:
    st.markdown("<div class='section-header'>Preview Gallery</div>", unsafe_allow_html=True)

    progress_bar = st.empty()
    status_text = st.empty()

    # 3×3 collage display
    collage_display = st.empty()

    # Tile grid with per-tile Re-roll buttons
    st.markdown("**Individual Tiles (click 🔄 to re-roll a single pose):**")
    tile_cols = st.columns(3)
    tile_displays = []
    reroll_buttons = []
    for i in range(9):
        col = tile_cols[i % 3]
        with col:
            td = st.empty()
            rb = st.button(f"🔄 #{i+1}", key=f"reroll_{i}", use_container_width=True)
            tile_displays.append(td)
            reroll_buttons.append(rb)
            if st.session_state.tiles[i] is not None:
                td.image(st.session_state.tiles[i], use_container_width=True)

    # Show existing collage if available
    if st.session_state.canvas is not None:
        collage_display.image(
            canvas_to_bytes(st.session_state.canvas),
            caption=f"3×3 Collage — {st.session_state.active_concept}",
            use_container_width=True,
        )

    # Download button
    if st.session_state.canvas is not None:
        collage_bytes = canvas_to_bytes(st.session_state.canvas, format="PNG")
        st.download_button(
            "⬇️ Download 3072×3072 Collage",
            data=collage_bytes,
            file_name=f"photostudio_{st.session_state.active_concept.replace(' ', '_')}_collage.png",
            mime="image/png",
            use_container_width=True,
        )


# ── Generation Logic ──────────────────────────────────────────────────────────
def run_generation(
    concept_name: str,
    concept_prompt_override: str,
    pose_config: PoseConfig,
    checkpoint: str,
    steps: int,
    vram_cap_gb: float,
    tile_index_override: int = -1,  # -1 = generate all 9
    save_individual_shots: bool = False,
):
    """Core generation function."""
    from comfy_bridge import queue_prompt, wait_for_completion
    from workflow_builder import build_txt2img_workflow
    from compositor import create_empty_canvas, composite_tile

    client_id = st.session_state.client_id

    # Build pose prompts
    prompts = generate_all_pose_prompts(concept_name, pose_config, n_tiles=9)

    # Override concept description in prompt if user edited it
    if concept_prompt_override:
        prompts = [
            (p.replace(CONCEPT_TEMPLATES.get(concept_name, ""), concept_prompt_override), s)
            for (p, s) in prompts
        ]

    indices_to_generate = [tile_index_override] if tile_index_override >= 0 else list(range(9))

    # Initialise canvas if full generation
    if tile_index_override < 0:
        st.session_state.canvas = create_empty_canvas(concept_name)
        st.session_state.tiles = [None] * 9

    if save_individual_shots:
        concept_folder = OUTPUT_DIR / concept_name.replace(" ", "_")
        concept_folder.mkdir(exist_ok=True)

    for step_num, idx in enumerate(indices_to_generate, start=1):
        pos_prompt, seed = prompts[idx]
        status_text.text(f"⏳ Generating tile #{idx + 1} of 9 ({step_num}/{len(indices_to_generate)})...")

        def on_progress(pct, msg):
            progress_bar.progress(pct / 100, text=f"Tile #{idx + 1}: {msg}")

        workflow = build_txt2img_workflow(
            positive_prompt=pos_prompt,
            negative_prompt=NEGATIVE_PROMPT,
            checkpoint_name=checkpoint,
            width=1024,
            height=1024,
            steps=steps,
            cfg=7.0,
            seed=seed,
        )

        try:
            prompt_id = queue_prompt(workflow, client_id)
            images = wait_for_completion(prompt_id, client_id, progress_callback=on_progress)

            if images:
                img_bytes = images[0]
                st.session_state.tiles[idx] = img_bytes
                st.session_state.tile_seeds[idx] = seed

                # Save individual shot if requested
                if save_individual_shots:
                    shot_path = concept_folder / f"shot_{idx + 1:02d}.png"
                    with open(shot_path, "wb") as f:
                        f.write(img_bytes)

                # Update canvas
                if st.session_state.canvas is None:
                    st.session_state.canvas = create_empty_canvas(concept_name)
                st.session_state.canvas = composite_tile(st.session_state.canvas, idx, img_bytes)

                # Update UI
                tile_displays[idx].image(img_bytes, use_container_width=True)
                collage_display.image(
                    canvas_to_bytes(st.session_state.canvas),
                    caption=f"3×3 Collage — {concept_name}",
                    use_container_width=True,
                )

        except Exception as e:
            status_text.error(f"Tile #{idx + 1} failed: {e}")

    # Save collage to disk
    if st.session_state.canvas:
        out_path = str(OUTPUT_DIR / f"{concept_name.replace(' ', '_')}_3x3_collage.png")
        save_collage(st.session_state.canvas, out_path)
        status_text.success(f"✓ Collage saved to OUTPUT/{Path(out_path).name}")

    progress_bar.empty()
    st.session_state.generating = False


# ── Trigger Generation ────────────────────────────────────────────────────────
if gen_preview and not st.session_state.generating:
    st.session_state.generating = True
    pose_config = PoseConfig(
        vibe=vibe,
        chaos=chaos,
        custom_guidance=custom_guidance,
        seed=int(base_seed),
    )
    run_generation(
        concept_name=active_concept,
        concept_prompt_override=concept_prompts.get(active_concept, ""),
        pose_config=pose_config,
        checkpoint=selected_ckpt,
        steps=quality_steps,
        vram_cap_gb=vram_cap,
        save_individual_shots=False,
    )

if run_full and not st.session_state.generating:
    st.session_state.generating = True
    pose_config = PoseConfig(
        vibe=vibe,
        chaos=chaos,
        custom_guidance=custom_guidance,
        seed=int(base_seed),
    )
    run_generation(
        concept_name=active_concept,
        concept_prompt_override=concept_prompts.get(active_concept, ""),
        pose_config=pose_config,
        checkpoint=selected_ckpt,
        steps=quality_steps,
        vram_cap_gb=vram_cap,
        save_individual_shots=True,
    )

# ── Per-Tile Re-roll ──────────────────────────────────────────────────────────
for i, rb in enumerate(reroll_buttons):
    if rb and not st.session_state.generating and selected_ckpt and comfy_ok:
        st.session_state.generating = True
        pose_config = PoseConfig(
            vibe=vibe,
            chaos=chaos,
            custom_guidance=custom_guidance,
            seed=-1,  # force new random seed for re-roll
        )
        run_generation(
            concept_name=active_concept,
            concept_prompt_override=concept_prompts.get(active_concept, ""),
            pose_config=pose_config,
            checkpoint=selected_ckpt,
            steps=quality_steps,
            vram_cap_gb=vram_cap,
            tile_index_override=i,
            save_individual_shots=False,
        )

