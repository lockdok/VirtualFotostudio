"""
Collage Compositor
Assembles individual pose images into a high-resolution 3x3 contact sheet collage (3072×3072 px).
Supports live tile updates (re-roll) without full re-render.
"""

import os
from io import BytesIO
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

# Collage grid configuration
TILE_SIZE = 1024         # Width and height of each individual shot
GRID_COLS = 3
GRID_ROWS = 3
TILE_GAP = 12            # Gap between tiles in pixels
BORDER = 24              # Outer border
HEADER_HEIGHT = 72       # Space for concept title at the top

BACKGROUND_COLOR = (18, 18, 18)       # Near-black editorial background
BORDER_COLOR = (30, 30, 30)
ACCENT_COLOR = (220, 180, 120)        # Warm gold for typography
TEXT_COLOR = (240, 240, 240)


def _canvas_size() -> tuple[int, int]:
    total_w = BORDER * 2 + GRID_COLS * TILE_SIZE + (GRID_COLS - 1) * TILE_GAP
    total_h = BORDER * 2 + HEADER_HEIGHT + GRID_ROWS * TILE_SIZE + (GRID_ROWS - 1) * TILE_GAP
    return total_w, total_h


def _tile_position(index: int) -> tuple[int, int]:
    """Return the top-left (x, y) pixel position of tile at grid index."""
    col = index % GRID_COLS
    row = index // GRID_COLS
    x = BORDER + col * (TILE_SIZE + TILE_GAP)
    y = BORDER + HEADER_HEIGHT + row * (TILE_SIZE + TILE_GAP)
    return x, y


def create_empty_canvas(concept_name: str) -> Image.Image:
    """Create the background canvas with editorial typography."""
    w, h = _canvas_size()
    canvas = Image.new("RGB", (w, h), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(canvas)

    # Decorative top border line
    draw.rectangle([BORDER, BORDER + 4, w - BORDER, BORDER + 6], fill=ACCENT_COLOR)

    # Concept title
    try:
        font_title = ImageFont.truetype("arial.ttf", 30)
        font_sub = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = font_title

    title_text = concept_name.upper()
    draw.text((BORDER, BORDER + 16), title_text, fill=ACCENT_COLOR, font=font_title)
    draw.text((BORDER, BORDER + 50), "VIRTUAL AI PHOTOSTUDIO", fill=TEXT_COLOR, font=font_sub)

    # Decorative bottom border line
    draw.rectangle([BORDER, BORDER + HEADER_HEIGHT - 6, w - BORDER, BORDER + HEADER_HEIGHT - 4], fill=(50, 50, 50))

    # Draw empty tile placeholders
    for i in range(GRID_COLS * GRID_ROWS):
        x, y = _tile_position(i)
        draw.rectangle([x, y, x + TILE_SIZE - 1, y + TILE_SIZE - 1], fill=(30, 30, 30))
        draw.rectangle([x, y, x + TILE_SIZE - 1, y + TILE_SIZE - 1], outline=(50, 50, 50), width=1)
        draw.text((x + TILE_SIZE // 2 - 20, y + TILE_SIZE // 2 - 10), f"#{i + 1}", fill=(80, 80, 80), font=font_sub)

    return canvas


def composite_tile(canvas: Image.Image, tile_index: int, image_bytes: bytes) -> Image.Image:
    """
    Place a single rendered tile onto the collage canvas at the correct grid position.
    Returns the updated canvas (mutates in place too for efficiency).
    """
    x, y = _tile_position(tile_index)

    # Load and resize the tile
    tile = Image.open(BytesIO(image_bytes)).convert("RGB")
    tile = tile.resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS)

    canvas.paste(tile, (x, y))

    # Add subtle tile border
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([x, y, x + TILE_SIZE - 1, y + TILE_SIZE - 1], outline=(60, 60, 60), width=1)

    # Tile number overlay (bottom-left corner)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = ImageFont.load_default()
    draw.rectangle([x + 4, y + TILE_SIZE - 26, x + 34, y + TILE_SIZE - 4], fill=(0, 0, 0, 180))
    draw.text((x + 8, y + TILE_SIZE - 24), f"#{tile_index + 1}", fill=ACCENT_COLOR, font=font)

    return canvas


def save_collage(canvas: Image.Image, output_path: str, quality: int = 95) -> str:
    """Save the final collage to disk as a high-quality JPEG or PNG."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    ext = Path(output_path).suffix.lower()
    if ext == ".jpg" or ext == ".jpeg":
        canvas.save(output_path, "JPEG", quality=quality, optimize=True)
    else:
        canvas.save(output_path, "PNG", optimize=True)
    return output_path


def canvas_to_bytes(canvas: Image.Image, format: str = "PNG") -> bytes:
    """Convert canvas to bytes for display in the web UI without saving to disk."""
    buf = BytesIO()
    canvas.save(buf, format=format)
    buf.seek(0)
    return buf.getvalue()


def collage_dimensions() -> tuple[int, int]:
    return _canvas_size()

