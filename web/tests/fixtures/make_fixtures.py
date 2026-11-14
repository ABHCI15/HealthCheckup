"""Generate realistic barcode test photos and verify the app's decoder reads them.

Run from the project root:  venv/bin/python web/tests/fixtures/make_fixtures.py
"""
import sys
from pathlib import Path

import numpy as np
import zxingcpp
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from healthcheck.barcode import decode_image  # noqa: E402


def barcode_image(code: str, scale: int) -> Image.Image:
    img = zxingcpp.write_barcode_to_image(
        zxingcpp.create_barcode(code, zxingcpp.BarcodeFormat.UPCA), scale=scale
    )
    return Image.fromarray(np.array(img)).convert("L")


def textured(size, base, spread, seed) -> Image.Image:
    """Wood/table-like background: low-frequency blotches, grain streaks and sensor noise."""
    rng = np.random.default_rng(seed)
    w, h = size
    coarse = rng.normal(0, 1, (h // 40 + 1, w // 40 + 1))
    coarse = np.array(Image.fromarray(coarse.astype(np.float32)).resize((w, h), Image.BICUBIC))
    grain = np.repeat(rng.normal(0, 1, (h, w // 16 + 1)), 16, axis=1)[:, :w]
    fine = rng.normal(0, 1, (h, w))
    lum = base + spread * (0.6 * coarse + 0.3 * grain + 0.25 * fine)
    tint = np.array([1.0, 0.86, 0.68])
    rgb = np.clip(lum[..., None] * tint, 0, 255).astype(np.uint8)
    return Image.fromarray(rgb, "RGB")


def label(code: str, scale: int, pad: int) -> Image.Image:
    bc = barcode_image(code, scale)
    card = Image.new("L", (bc.width + 2 * pad, bc.height + 2 * pad), 245)
    card.paste(bc, (pad, pad))
    return card.convert("RGB")


def paste_rotated(bg: Image.Image, card: Image.Image, angle: float, center) -> None:
    rgba = card.convert("RGBA").rotate(angle, expand=True, resample=Image.BICUBIC)
    x = center[0] - rgba.width // 2
    y = center[1] - rgba.height // 2
    bg.paste(rgba, (x, y), rgba)


def make_juice(path: Path, level: int) -> None:
    """level 0 = harshest; higher levels are milder."""
    angle = 8
    blur = [1.6, 1.1, 0.7, 0.3][level]
    quality = [55, 65, 78, 90][level]
    bg = textured((1600, 1200), 120, 28, seed=1)
    # the "package": a lighter carton lying on the table
    pack = textured((760, 620), 215, 10, seed=2).convert("RGB")
    paste_rotated(bg, pack, angle, (800, 600))
    paste_rotated(bg, label("025000051753", 3, 24), angle, (860, 660))
    bg = bg.filter(ImageFilter.GaussianBlur(blur))
    bg.save(path, "JPEG", quality=quality)


def make_fan(path: Path, level: int) -> None:
    scale = [1, 2, 2, 3][level]
    contrast = [0.45, 0.45, 0.65, 0.8][level]
    bg = textured((2000, 1500), 150, 14, seed=3)
    card = label("840059614922", scale, 12 * scale)
    bg.paste(card, (1180, 880))
    arr = np.asarray(bg).astype(np.float32)
    arr = 128 + (arr - 128) * contrast  # lowered contrast
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").save(path, "PNG")


def make_dark(path: Path) -> None:
    bg = textured((1600, 1200), 28, 8, seed=4)
    bg = bg.filter(ImageFilter.GaussianBlur(2))
    bg.save(path, "JPEG", quality=70)


def decoded(path: Path):
    result = decode_image(Image.open(path))
    return result


def build(name: str, maker, expected: str) -> bool:
    path = HERE / name
    for level in range(4):
        maker(path, level)
        result = decoded(path)
        best = result.best
        if best is not None and best.barcode.upc == expected:
            print(f"OK   {name}: read {best.barcode.upc} at stage '{best.stage}' "
                  f"(degradation level {level}, {len(result.stages_tried)} stage(s) tried)")
            return True
        got = best.barcode.upc if best else None
        print(f"..   {name}: level {level} not decodable (got {got}); making it milder")
    print(f"FAIL {name}: could not produce a decodable fixture")
    return False


def main() -> int:
    ok = build("grapefruit-juice.jpg", make_juice, "025000051753")
    ok &= build("recalled-fan.png", make_fan, "840059614922")

    dark = HERE / "no-barcode.jpg"
    make_dark(dark)
    result = decoded(dark)
    if result.best is None:
        print(f"OK   no-barcode.jpg: nothing found after {len(result.stages_tried)} stage(s); "
              f"hint: {result.hint!r}")
    else:
        print(f"FAIL no-barcode.jpg: unexpectedly read {result.best.barcode.upc}")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
