"""
Semicontrollable Pose Director
Generates diverse, naturally varied pose prompts for each tile of the 3x3 grid.
Balances creative control (Vibe/Energy + custom guidance) with photographic randomness (Chaos slider + seed).
"""

import random
from dataclasses import dataclass
from typing import Optional


# ─── Vibe Pools ────────────────────────────────────────────────────────────────

VIBE_POOLS = {
    "Candid & Natural": {
        "actions": [
            "laughing naturally", "looking away into the distance", "gently fixing hair",
            "glancing down softly", "caught mid-laugh", "adjusting jacket collar",
            "in a fleeting candid moment", "smiling quietly", "brushing hair off face",
            "looking up unexpectedly", "arms wrapped loosely around the body",
        ],
        "energy": "candid, natural, unposed, spontaneous, authentic, genuine",
    },
    "Editorial High-Fashion": {
        "actions": [
            "striking a powerful editorial pose", "intense direct gaze at the camera",
            "strong angular body language", "confident hand on hip", "sharp profile look",
            "bold sculptural arm pose", "powerful asymmetric stance",
            "dramatic chin-down gaze", "defined silhouette pose", "fierce high-fashion model stance",
            "poised and commanding",
        ],
        "energy": "editorial, high-fashion, Vogue, powerful, confident, sculptural, dramatic",
    },
    "Playful & Expressive": {
        "actions": [
            "playful wink", "twirling mid-step, clothing in motion", "tongue-out fun expression",
            "jumping mid-air", "blowing hair off face", "peeking from behind shoulder",
            "covering mouth while laughing", "expressive hand gesture",
            "playfully pointing at camera", "looking mischievous",
            "hands framing face in playful way",
        ],
        "energy": "playful, expressive, fun, energetic, joyful, carefree, lively",
    },
    "Moody & Cinematic": {
        "actions": [
            "pensively staring into middle distance", "looking down with introspective gaze",
            "hands clasped thoughtfully", "leaning against a surface quietly",
            "profile shot in deep shadow and light", "melancholic far-away gaze",
            "fingers lightly touching lips", "eyes closed in serene moment",
            "dramatic over-the-shoulder look", "brooding cinematic gaze",
            "hand pressed gently against glass or wall",
        ],
        "energy": "moody, cinematic, introspective, atmospheric, dramatic, evocative",
    },
}

# ─── Camera Framing Pool ───────────────────────────────────────────────────────

CAMERA_FRAMINGS = [
    "extreme close-up beauty portrait, eyes and lips filling the frame",
    "close-up face portrait, shoulders visible",
    "medium close-up, waist-up shot",
    "3/4 portrait, slight left angle",
    "3/4 portrait, slight right angle",
    "full-length standing portrait",
    "low angle shot from below looking up",
    "high angle shot from above looking down",
    "over-the-shoulder back view, looking back at camera",
    "dramatic Dutch angle portrait",
    "environmental medium shot showing location context",
]

# ─── Core Concept Prompt Templates ─────────────────────────────────────────────

CONCEPT_TEMPLATES = {
    "Golden Hour Botanical": (
        "in a sun-drenched botanical greenhouse, tropical plants and monstera leaves surrounding the subject, "
        "golden hour warm sunlight, soft natural lens flares, wearing an elegant flowing cream linen slip dress, "
        "vibrant green and warm gold colour palette"
    ),
    "Classic Vogue Studio": (
        "in a high-end minimalist photography studio, deep charcoal grey seamless backdrop, "
        "professional softbox and Rembrandt studio lighting, dramatic sharp shadows and highlights, "
        "wearing a tailored oversized black satin blazer and sleek black top, "
        "Vogue editorial magazine photography"
    ),
    "Evening Gala / Red Carpet": (
        "at a grand luxury ballroom gala with gilded chandeliers and soft golden bokeh, "
        "marble grand staircase in the background, wearing an emerald green silk open-back floor-length evening gown, "
        "glamorous atmosphere"
    ),
    "Vintage Film Cafe": (
        "in a cozy Parisian street cafe with warm interior lighting and rain-streaked windows, "
        "wooden tables and warm ambient glow, wearing a chic camel wool trench coat and cream knit scarf, "
        "authentic 35mm film grain, warm nostalgic colour grading, "
        "Kodak Portra 400 film aesthetic"
    ),
}

# ─── Shared Subject Description ────────────────────────────────────────────────

# Identity is supplied by the session reference through FaceID/IP-Adapter.  Do
# not hard-code a person's age, gender, hair or facial features into prompts.
SUBJECT_DESCRIPTION = "the person from the likeness reference photo"

QUALITY_SUFFIX = (
    "photorealistic portrait photography, shot on Canon EOS R5 with 85mm f/1.4 lens, "
    "ultra-sharp focus on face and eyes, cinematic colour grading, "
    "8K resolution, professional retouching, editorial quality"
)

NEGATIVE_PROMPT = (
    "cartoon, anime, illustration, painting, sketch, drawing, 3D render, artificial, "
    "plastic skin, deformed, distorted, extra limbs, bad anatomy, ugly, blurry face, "
    "low quality, low resolution, watermark, text, logo"
)


# ─── Pose Director ─────────────────────────────────────────────────────────────

@dataclass
class PoseConfig:
    """User-facing pose direction controls."""
    vibe: str = "Candid & Natural"          # Dropdown selector
    chaos: float = 0.5                       # 0.0 = structured | 1.0 = unscripted
    custom_guidance: str = ""               # Optional freeform keywords
    seed: int = -1                           # -1 = fully random


def generate_pose_prompt(
    tile_index: int,
    concept_name: str,
    pose_config: PoseConfig,
    seed_override: Optional[int] = None,
    concept_text: Optional[str] = None,
    session_seed: Optional[int] = None,
    concept_description: Optional[str] = None,
) -> tuple[str, int]:
    """
    Generate a unique pose prompt for a single tile.

    ``concept_text`` replaces the built-in template for ``concept_name`` (used for
    the user's edited concept text).  ``session_seed`` fixes the framing order so
    every tile of one shoot draws from the same shuffled list.
    Returns (positive_prompt, seed_used).
    """

    # Determine the seed for this tile
    if seed_override is not None:
        tile_seed = seed_override
    elif pose_config.seed >= 0:
        tile_seed = pose_config.seed + tile_index
    else:
        tile_seed = random.randint(0, 2**31 - 1)

    rng = random.Random(tile_seed)

    vibe_pool = VIBE_POOLS.get(pose_config.vibe, VIBE_POOLS["Candid & Natural"])
    custom_concept = concept_text if concept_text is not None else concept_description
    if custom_concept and custom_concept.strip():
        concept_desc = custom_concept.strip()
    else:
        concept_desc = CONCEPT_TEMPLATES.get(concept_name, "in a beautiful scenic setting")

    # Build framing pool based on chaos level
    if pose_config.chaos < 0.3:
        framing_pool = CAMERA_FRAMINGS[:5]
    else:
        framing_pool = CAMERA_FRAMINGS

    # Distinct framings across tiles: one deterministic shuffle per shoot
    if session_seed is None:
        session_seed = pose_config.seed if pose_config.seed >= 0 else 42
    session_rng = random.Random(session_seed)
    pool_shuffled = framing_pool.copy()
    session_rng.shuffle(pool_shuffled)
    while len(pool_shuffled) <= tile_index:
        extra = framing_pool.copy()
        session_rng.shuffle(extra)
        pool_shuffled += extra
    framing = pool_shuffled[tile_index]
    # Small chaos chance of wild angle override
    if rng.random() < pose_config.chaos * 0.35:
        framing = rng.choice(CAMERA_FRAMINGS)

    # Pick action from vibe pool
    action = rng.choice(vibe_pool["actions"])
    energy = vibe_pool["energy"]

    # Build pose prompt
    custom = f", {pose_config.custom_guidance.strip()}" if pose_config.custom_guidance.strip() else ""

    prompt = (
        f"{framing}, {SUBJECT_DESCRIPTION}, {action}{custom}, "
        f"{concept_desc}, {energy}, {QUALITY_SUFFIX}"
    )

    return prompt, tile_seed


def generate_all_pose_prompts(
    concept_name: str,
    pose_config: PoseConfig,
    n_tiles: int = 9,
    concept_text: Optional[str] = None,
    session_seed: Optional[int] = None,
    concept_description: Optional[str] = None,
) -> list[tuple[str, int]]:
    """
    Generate n_tiles unique pose prompts for a given concept.
    Returns a list of (positive_prompt, seed) tuples.

    With a fixed seed the shoot is reproducible; with seed -1 each shoot gets a
    fresh framing order (previously every random shoot reused the same one).
    """
    if session_seed is None:
        session_seed = pose_config.seed if pose_config.seed >= 0 else random.randint(0, 2**31 - 1)
    if concept_text is None:
        concept_text = concept_description
    return [
        generate_pose_prompt(i, concept_name, pose_config, concept_text=concept_text, session_seed=session_seed)
        for i in range(n_tiles)
    ]


def get_available_vibes() -> list[str]:
    return list(VIBE_POOLS.keys())
