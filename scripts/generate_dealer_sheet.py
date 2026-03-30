"""Generate a baseline blonde tuxedo dealer sprite sheet (112x224, 7x7)."""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image
except Exception as exc:  # pragma: no cover
    raise SystemExit("Pillow is required: pip install Pillow") from exc

FRAME_W = 16
FRAME_H = 32
COLS = 7
ROWS = 7

TRANSPARENT = (0, 0, 0, 0)
HAIR = (240, 208, 96, 255)
HAIR_DARK = (210, 175, 70, 255)
SKIN = (245, 208, 169, 255)
EYE = (40, 40, 60, 255)
TUX = (26, 26, 46, 255)
SHIRT = (238, 238, 255, 255)
TIE = (204, 34, 51, 255)
PANTS = (22, 22, 40, 255)
SHOES = (16, 16, 28, 255)


def _draw_base_frame(img: Image.Image, frame_x: int, frame_y: int, frame_idx: int, state_idx: int) -> None:
    px = img.load()
    ox = frame_x * FRAME_W
    oy = frame_y * FRAME_H

    bob = 1 if frame_idx % 2 else 0
    if state_idx == 5:
        bob = -1 if frame_idx % 2 == 0 else 0  # success rises slightly
    if state_idx == 6:
        bob = 0  # error stays flat

    def put(x: int, y: int, c):
        yy = y + bob
        if 0 <= x < FRAME_W and 0 <= yy < FRAME_H:
            px[ox + x, oy + yy] = c

    # Hair
    for x in range(5, 11):
        put(x, 0, HAIR)
    for x in range(4, 12):
        put(x, 1, HAIR)
    for x in range(3, 13):
        put(x, 2, HAIR)
    put(4, 3, HAIR_DARK)
    put(11, 3, HAIR_DARK)

    # Face
    for y in range(4, 9):
        for x in range(4, 12):
            put(x, y, SKIN)
    put(5, 5, EYE)
    put(10, 5, EYE)

    # Torso tux
    for y in range(10, 20):
        for x in range(3, 13):
            put(x, y, TUX)

    # Shirt + tie
    for y in range(10, 18):
        put(7, y, SHIRT)
        put(8, y, SHIRT)
    for y in range(11, 18):
        put(7, y, TIE if state_idx != 6 else (180, 20, 30, 255))

    # Legs
    for y in range(20, 28):
        for x in range(3, 7):
            put(x, y, PANTS)
        for x in range(9, 13):
            put(x, y, PANTS)

    # Shoes
    for x in range(3, 7):
        put(x, 28, SHOES)
        put(x, 29, SHOES)
    for x in range(9, 13):
        put(x, 28, SHOES)
        put(x, 29, SHOES)

    # Walk sway
    if state_idx == 1 and frame_idx % 2 == 1:
        for y in range(20, 28):
            put(3, y, TRANSPARENT)
            put(12, y, TRANSPARENT)
            put(2, y, PANTS)
            put(13, y, PANTS)


def generate() -> Image.Image:
    sheet = Image.new("RGBA", (FRAME_W * COLS, FRAME_H * ROWS), TRANSPARENT)
    for row in range(ROWS):
        for col in range(COLS):
            _draw_base_frame(sheet, col, row, col, row)
    return sheet


def main() -> int:
    out = Path("ui/assets/sprites/dealers/ov_dealer_female_tux_blonde_v1.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img = generate()
    img.save(out)
    print(f"saved: {out} ({img.width}x{img.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

