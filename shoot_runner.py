"""Generation engine for Virtual AI Photostudio (no Streamlit dependency).

``photostudio_app.py`` only draws the UI and passes callbacks; everything that
talks to ComfyUI, writes files or keeps the manifest lives here so it can be
tested on its own.
"""

from __future__ import annotations

import json
import os
import random
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import comfy_bridge
from pose_director import NEGATIVE_PROMPT, PoseConfig, generate_all_pose_prompts, generate_pose_prompt
from workflow_builder import build_faceid_workflow, upscaled_size

ASPECTS = {"Portrait 3:4": (3, 4), "Landscape 4:3": (4, 3)}


def slug(value: str, default: str = "photoshoot") -> str:
    """Filesystem-safe name that keeps Unicode letters, so "фото" stays "фото"."""
    return re.sub(r"[^\w-]+", "_", value).strip("_") or default


# First-pass sizes SDXL was trained on (about 1 MP); full shoots start here.
SDXL_NATIVE = {"Portrait 3:4": (896, 1152), "Landscape 4:3": (1152, 896)}
HIRES_SCALE = 1.5     # detail pass: 896x1152 -> 1344x1728
HIRES_DENOISE = 0.4


def _round8(value: float) -> int:
    return max(8, round(value / 8) * 8)


def dimensions(aspect: str, short_edge: int) -> tuple[int, int]:
    """Size for ``aspect`` with the given short edge, snapped to multiples of 8 (a latent requirement)."""
    short_edge = _round8(short_edge)
    long_edge = _round8(short_edge * 4 / 3)
    return (short_edge, long_edge) if ASPECTS[aspect] == (3, 4) else (long_edge, short_edge)


def unique_folder(parent: Path, name: str) -> Path:
    """Create ``parent/name`` (adding _2, _3... if it exists) so a manifest is never overwritten."""
    folder, suffix = parent / name, 1
    while True:
        try:
            folder.mkdir(parents=True)
            return folder
        except FileExistsError:
            suffix += 1
            folder = parent / f"{name}_{suffix}"


def _unique_image_path(folder: Path, index: int, seed: int) -> Path:
    base = f"{index + 1:02d}_{seed}"
    candidate = folder / f"{base}.png"
    suffix = 2
    while candidate.exists():
        candidate = folder / f"{base}_{suffix}.png"
        suffix += 1
    return candidate


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
                                         delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(data)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@dataclass
class ShootRecord:
    """Everything needed to describe a shoot and to re-roll one of its images."""
    folder: Path
    concept: str
    concept_text: Optional[str]
    pose_config: PoseConfig
    session_seed: int
    reference_name: str
    checkpoint: str
    identity_strength: float
    width: int
    height: int
    steps: int
    settings: dict
    images: dict[int, dict] = field(default_factory=dict)       # tile index -> manifest entry
    superseded: list[dict] = field(default_factory=list)        # entries replaced by re-rolls
    failures: list[dict] = field(default_factory=list)
    status: str = "in_progress"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    hires_scale: float = 0.0                                    # 0 = single pass

    @property
    def output_size(self) -> tuple[int, int]:
        """Final pixel size of the saved images (after the optional detail pass)."""
        if self.hires_scale > 1.0:
            return upscaled_size(self.width, self.height, self.hires_scale)
        return self.width, self.height


def write_manifest(record: ShootRecord) -> None:
    payload = {
        "created_at": record.created_at,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "status": record.status,
        "settings": record.settings,
        "images": [record.images[i] for i in sorted(record.images)],
    }
    if record.superseded:
        payload["superseded"] = record.superseded
    if record.failures:
        payload["failures"] = record.failures
    manifest_path = record.folder / "shoot_manifest.json"
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=record.folder,
                                         prefix=".shoot_manifest.", suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, indent=2)
        os.replace(temporary_path, manifest_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def render_image(*, prompt: str, seed: int, record: ShootRecord, client_id: str,
                 on_progress: Optional[Callable[[int, str], None]] = None) -> bytes:
    """Run one ComfyUI job and return the PNG bytes. Raises on any failure."""
    workflow = build_faceid_workflow(
        positive_prompt=prompt, negative_prompt=NEGATIVE_PROMPT, checkpoint_name=record.checkpoint,
        reference_image=record.reference_name, width=record.width, height=record.height,
        steps=record.steps, seed=seed, identity_strength=record.identity_strength,
        output_prefix=f"photostudio/{slug(record.concept)}",
        hires_scale=record.hires_scale, hires_denoise=HIRES_DENOISE,
    )
    prompt_id = comfy_bridge.queue_prompt(workflow, client_id)

    progress_cb = on_progress
    if on_progress is not None and record.hires_scale > 1.0:
        # ComfyUI reports each sampler separately (0-100 twice); merge them into one 0-100 bar.
        state = {"passes_done": 0, "last": -1}

        def progress_cb(pct: int, message: str) -> None:
            if pct < state["last"] and state["passes_done"] < 1:
                state["passes_done"] = 1
            state["last"] = pct
            label = ("detail pass, " if state["passes_done"] else "base pass, ") + message
            on_progress((state["passes_done"] * 100 + pct) // 2, label)

    images = comfy_bridge.wait_for_completion(prompt_id, client_id, progress_cb)
    if not images:
        raise RuntimeError("ComfyUI returned no image. Check the ComfyUI console for the workflow error.")
    return images[0]


def run_series(*, output_dir: Path, concept: str, concept_prompt: Optional[str], reference_name: str,
               checkpoint: str, pose_config: PoseConfig, identity_strength: float, aspect: str,
               short_edge: int = 768, count: int = 9, steps: int = 20, preview: bool = True, client_id: str = "",
               base_size: Optional[tuple[int, int]] = None, hires_scale: float = 0.0,
               on_status: Callable[[str], None] = lambda msg: None,
               on_progress: Callable[[float, str], None] = lambda frac, text: None,
               on_image: Callable[[int, bytes, dict], None] = lambda index, data, entry: None,
               on_error: Callable[[str], None] = lambda msg: None) -> ShootRecord:
    """Generate ``count`` images for one concept and keep a manifest of the shoot.

    ``base_size`` overrides the size derived from ``aspect``/``short_edge``;
    ``hires_scale`` > 1 adds the detail pass (see ``build_faceid_workflow``).
    """
    width, height = base_size or dimensions(aspect, short_edge)
    session_seed = pose_config.seed if pose_config.seed >= 0 else random.randint(0, 2**31 - 1)
    prompts = generate_all_pose_prompts(concept, pose_config, n_tiles=count,
                                        concept_text=concept_prompt, session_seed=session_seed)
    folder = unique_folder(output_dir, f"{datetime.now():%Y%m%d_%H%M%S}_{slug(concept)}")
    record = ShootRecord(
        folder=folder, concept=concept, concept_text=concept_prompt, pose_config=pose_config,
        session_seed=session_seed, reference_name=reference_name, checkpoint=checkpoint,
        identity_strength=identity_strength, width=width, height=height, steps=steps,
        hires_scale=hires_scale,
        settings={"concept": concept, "reference": reference_name, "identity_strength": identity_strength,
                  "aspect": aspect, "steps": steps, "checkpoint": checkpoint, "preview": preview,
                  "session_seed": session_seed, "image_count": count, "base_size": [width, height],
                  "hires_scale": hires_scale or None, "hires_denoise": HIRES_DENOISE if hires_scale else None},
    )
    out_w, out_h = record.output_size
    record.settings["output_size"] = [out_w, out_h]

    write_manifest(record)
    for number, (prompt, seed) in enumerate(prompts, start=1):
        on_status(f"Generating {concept}: image {number}/{count}")
        try:
            data = render_image(
                prompt=prompt, seed=seed, record=record, client_id=client_id,
                on_progress=lambda pct, msg, n=number: on_progress((n - 1 + pct / 100) / count, f"{concept}: {msg}"),
            )
        except Exception as exc:
            message = f"Image {number} failed: {exc}"
            record.failures.append({"index": number - 1, "seed": seed, "error": str(exc)})
            write_manifest(record)
            on_error(message)
            continue
        image_path = _unique_image_path(folder, number - 1, seed)
        _write_bytes_atomic(image_path, data)
        filename = image_path.name
        entry = {"file": filename, "seed": seed, "prompt": prompt, "width": out_w, "height": out_h}
        record.images[number - 1] = entry
        write_manifest(record)
        on_image(number - 1, data, entry)

    record.status = "completed" if not record.failures else (
        "completed_with_errors" if record.images else "failed"
    )
    write_manifest(record)
    return record


def reroll_tile(record: ShootRecord, index: int, *, client_id: str,
                on_progress: Optional[Callable[[int, str], None]] = None) -> tuple[bytes, dict]:
    """Replace one image of a shoot with a fresh seed *and* a different pose/framing.

    The new file is saved next to the others, the manifest is rewritten, and the
    replaced image stays on disk (listed under ``superseded`` in the manifest).
    """
    if index not in record.images:
        raise ValueError(f"Image {index + 1} has not been generated and cannot be re-rolled.")
    previous = record.images.get(index, {}).get("prompt")
    prompt = ""
    seed = -1
    for _ in range(20):
        # A fresh session seed also reshuffles the camera framing, not just the action.
        prompt, seed = generate_pose_prompt(
            index, record.concept, record.pose_config, seed_override=random.randint(0, 2**31 - 1),
            concept_text=record.concept_text, session_seed=random.randint(0, 2**31 - 1),
        )
        if prompt != previous:
            break
    else:
        message = "Could not produce a different pose after 20 attempts."
        record.failures.append({"index": index, "stage": "reroll", "error": message})
        record.status = "completed_with_errors"
        write_manifest(record)
        raise RuntimeError(message)
    try:
        data = render_image(prompt=prompt, seed=seed, record=record, client_id=client_id, on_progress=on_progress)
    except Exception as exc:
        record.failures.append({"index": index, "seed": seed, "stage": "reroll", "error": str(exc)})
        record.status = "completed_with_errors"
        write_manifest(record)
        raise
    image_path = _unique_image_path(record.folder, index, seed)
    _write_bytes_atomic(image_path, data)
    filename = image_path.name
    if index in record.images:
        record.superseded.append(record.images[index])
    out_w, out_h = record.output_size
    entry = {"file": filename, "seed": seed, "prompt": prompt, "width": out_w,
             "height": out_h, "rerolled": True}
    record.images[index] = entry
    write_manifest(record)
    return data, entry
