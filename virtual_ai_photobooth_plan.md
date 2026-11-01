> **Historical design plan.** The original 3072x3072 collage was replaced by independent images; see the implementation update at the end and `README.md` / `photostudio_walkthrough.md` for current behaviour.

# Implementation Plan: Local Web AI Photobooth (with Resource Controller)

A single-page local web application (`http://localhost:7860`) with **semicontrollable 3x3 pose generation**, 1-click **Start/Stop** scripts, and a dedicated **RAM & VRAM Resource Controller** for smooth background multitasking.

---

## 🎛️ RAM & VRAM Resource Controller (Background Mode)

To ensure the photobooth runs quietly in the background without causing stutters or consuming all GPU memory while you work in parallel:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ ⚙️ PERFORMANCE & RESOURCE CONTROLLER                                   │
├────────────────────────────────────────────────────────────────────────┤
│ • Preset Mode:    (●) Quiet Background   ( ) Balanced   ( ) Turbo      │
│                                                                        │
│ • VRAM Allocation Cap:  [━━━●━━━━━━━] 6.0 GB (of 12 GB)               │
│   (Guarantees at least 6 GB of VRAM stays free for your other apps)    │
│                                                                        │
│ • CPU Priority:   [ Below Normal (Multitask Safe) ▼ ]                  │
│                                                                        │
│ • Auto-Unload VRAM on Idle: [x] Enabled                                │
│   (Frees GPU VRAM back to 0 MB whenever no photos are being generated) │
└────────────────────────────────────────────────────────────────────────┘
```

### How the Resource Limits are Enforced:
1. **Hard VRAM Cap (`torch.cuda.set_per_process_memory_fraction` & `--reserve-vram`):**
   * Physically prevents PyTorch / ComfyUI from allocating more than your chosen limit (e.g. 50–60% of the 12GB RTX 4070 Ti).
   * Leaves the remaining VRAM completely untouched for your browser, games, video editors, or other tasks.
2. **CPU Scheduling Priority (`Below Normal`):**
   * Windows gives 100% CPU priority to your active work and foreground windows. The photobooth only consumes idle background CPU cycles.
3. **Auto-Unload on Idle:**
   * When generation finishes, model weights are paged out of VRAM, returning GPU memory usage to near zero.

---

## 1-Click Launch & Shutdown Controls

```text
📁 G:\VSCode\VirtualFotostudio\
├── 🟢 start_photostudio.bat  (Starts background service & opens browser)
└── 🔴 stop_photostudio.bat   (Kills processes & frees 100% VRAM)
```

---

## Semicontrollable 3x3 Pose System (Control + Randomness)

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 🎭 POSE DIRECTION CONTROLS                                             │
├────────────────────────────────────────────────────────────────────────┤
│ • Vibe / Energy:     [ Casual & Candid ▼ ]                             │
│ • Pose Freedom:      [━━━●━━━━━━━] 50% Chaos                           │
│ • Pose Guidance:     [ "interacting with coffee cup, laughing..." ]    │
└────────────────────────────────────────────────────────────────────────┘
```

* **3x3 Grid (9 Poses):** 3072 × 3072 px high-res composite (~9.4 MP).
* **Per-Tile "🔄 Re-roll":** Click Re-roll on any single shot to generate a new spontaneous pose in ~7–10 seconds without re-rendering the whole collage.

---

## Web Interface Layout (`http://localhost:7860`)

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   📸 VIRTUAL AI PHOTOSTUDIO                            │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Reference Photos:  [ Drag & drop face/body reference photos here ]   │
├────────────────────────────────────────────────────────────────────────┤
│ 2-5. Concepts:                                                         │
│    [ Concept 1: Botanical ]    [ Concept 2: Vogue Studio ]             │
│    [ Concept 3: Evening Gala ] [ Concept 4: Film Cafe ]                │
├────────────────────────────────────────────────────────────────────────┤
│ 6. Semicontrollable Pose Director (Vibe, Chaos, Guidance)              │
├────────────────────────────────────────────────────────────────────────┤
│ 7. Resource Controller (Quiet Background Mode / VRAM Cap)              │
├────────────────────────────────────────────────────────────────────────┤
│ [ ⚡ Generate 3x3 Preview (3072x3072) ]   [ 🚀 Run Full Photoshoot ]   │
├────────────────────────────────────────────────────────────────────────┤
│ 🖼️ 3x3 Preview Grid:                                                   │
│   [Shot 1 🔄] [Shot 2 🔄] [Shot 3 🔄]                                   │
│   [Shot 4 🔄] [Shot 5 🔄] [Shot 6 🔄]    [ Download 3072x3072 Collage ]│
│   [Shot 7 🔄] [Shot 8 🔄] [Shot 9 🔄]                                   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Proposed Files

* **`start_photostudio.bat`**: 1-click launcher with background process priority.
* **`stop_photostudio.bat`**: 1-click terminator releasing memory and ports.
* **`app.py`**: Web UI with Resource Control sliders and live 3x3 preview grid.
* **`comfy_bridge.py`**: API connector enforcing memory limits and model loading.
* **`pose_director.py`**: Semicontrollable pose generator.
* **`compositor.py`**: 3072×3072 collage builder with per-tile updating.

---

## Verification Plan

1. **Test Resource Limiting:**
   * Select **"Quiet Background Mode" (6 GB VRAM cap)**.
   * Run a generation test while monitoring `nvidia-smi` to verify GPU memory does not exceed the 6 GB threshold.
   * Verify Windows Task Manager shows CPU priority is set to `Below Normal`.
2. **Test Semicontrollable Generation:**
   * Generate a 3x3 preview and verify the 3072×3072 collage renders properly in the browser.
3. **Test Single-Tile Re-roll:**
   * Re-roll an individual tile and verify only that tile refreshes.
4. **Test Clean Stop:**
   * Run `stop_photostudio.bat` and verify all processes close and VRAM is 100% freed.

---

## Implementation Update — 2026-11-01

The original fixed-size collage and text-only workflow have been superseded by
the identity-first design implemented in `photostudio_app.py`:

* Session reference photos are retained locally and sent only to local ComfyUI.
* The generation graph uses IP-Adapter FaceID Plus V2 for SDXL; it does not
  train a new model.
* Prompt-quality preview creates nine independent images, in 3:4 or 4:3, and
  Full Photoshoot creates a user-selected number of individual high-resolution
  files. Batch Concepts uses a checkbox selection.
* Identity Strength adjusts FaceID conditioning; it is deliberately presented
  as a likeness/style tradeoff rather than a guaranteed similarity score.
* Generated jobs retain a `shoot_manifest.json` recording prompts, seeds and
  settings. Setup and model requirements are documented in `README.md`.

Before the first generation, install the local FaceID dependencies and models
listed in `README.md`, then restart ComfyUI. The app reports missing FaceID
nodes and will keep generation disabled until the local engine is ready.
