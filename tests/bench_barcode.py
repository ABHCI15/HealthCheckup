"""Compare a single decode attempt with the staged pipeline on degraded synthetic photos.

Run: python tests/bench_barcode.py

The photos are generated, not taken with a camera, so treat the numbers as a
relative comparison between the two approaches rather than a field accuracy figure.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
import zxingcpp
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from healthcheck import barcode as bc  # noqa: E402

CODES = [
    ("012345678905", zxingcpp.BarcodeFormat.UPCA),
    ("036000291452", zxingcpp.BarcodeFormat.UPCA),
    ("4006381333931", zxingcpp.BarcodeFormat.EAN13),
    ("5901234123457", zxingcpp.BarcodeFormat.EAN13),
    ("96385074", zxingcpp.BarcodeFormat.EAN8),
]


def render(content, fmt, scale):
    return Image.fromarray(np.array(zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(content, fmt), scale=scale)))


def scene(code_img, rng, angle=0.0, size=(1600, 1200)):
    frame = Image.fromarray(rng.integers(100, 190, (size[1], size[0]), dtype=np.uint8)).filter(ImageFilter.GaussianBlur(8))
    if angle:
        code_img = code_img.rotate(angle, Image.BICUBIC, expand=True, fillcolor=255)
    x = int(rng.integers(40, size[0] - code_img.width - 40))
    y = int(rng.integers(40, size[1] - code_img.height - 40))
    frame.paste(code_img, (x, y))
    return frame


def degrade(img, kind, rng):
    a = np.asarray(img).astype(np.float32)
    if kind == "blur":
        return img.filter(ImageFilter.GaussianBlur(1.6))
    if kind == "low contrast":
        return Image.fromarray((a * 0.15 + 110).astype(np.uint8))
    if kind == "dark":
        return Image.fromarray((a * 0.16).astype(np.uint8))
    if kind == "noise":
        return Image.fromarray(np.clip(a + rng.normal(0, 28, a.shape), 0, 255).astype(np.uint8))
    if kind == "glare":
        ramp = np.linspace(0, 150, a.shape[1], dtype=np.float32)[None, :]
        return Image.fromarray(np.clip(a * 0.6 + ramp, 0, 255).astype(np.uint8))
    return img


def cases():
    rng = np.random.default_rng(42)
    for content, fmt in CODES:
        for scale in (1, 2):
            for angle in (0, 12, 25, 40):
                for kind in ("clean", "blur", "low contrast", "dark", "noise", "glare"):
                    photo = degrade(scene(render(content, fmt, scale), rng, angle), kind, rng)
                    yield content, f"{kind}", f"scale {scale}", f"tilt {angle}", photo


def single_pass(img):
    """One decode attempt on the photo as taken, as the original app did."""
    for item in zxingcpp.read_barcodes(img):
        code = bc.parse(item.text, str(item.format))
        if code and code.is_gtin:
            return code
    return None


def main():
    totals, base_ok, pipe_ok, wrong = Counter(), Counter(), Counter(), 0
    stages = Counter()
    for content, kind, scale, tilt, photo in cases():
        expected = bc.parse(content).gtin
        base = single_pass(photo)
        result = bc.decode_image(photo)
        best = result.best.barcode if result.best else None
        for group in ("all", kind, scale, tilt):
            totals[group] += 1
            base_ok[group] += bool(base and base.gtin == expected)
            pipe_ok[group] += bool(best and best.gtin == expected)
        if best and best.is_gtin and best.gtin != expected:
            wrong += 1
        if best and best.gtin == expected:
            stages[result.best.stage] += 1

    print(f"{'condition':<16}{'photos':>8}{'single pass':>14}{'pipeline':>12}")
    for group in totals:
        n = totals[group]
        print(f"{group:<16}{n:>8}{base_ok[group] / n:>13.0%}{pipe_ok[group] / n:>12.0%}")
    print(f"\nwrong codes returned by pipeline: {wrong}")
    print("stage that found the code:", dict(stages.most_common()))


if __name__ == "__main__":
    main()
