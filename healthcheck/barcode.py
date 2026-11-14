"""Barcode detection and normalisation.

Two jobs:

1. ``decode_image`` finds barcodes in a photo. A single decode attempt fails on
   most real phone photos (glare, blur, a small code in a big frame, a tilted
   package), so it runs a ladder of progressively more expensive image
   treatments and stops at the first one that yields a valid code.
2. ``parse`` turns whatever was read or typed into one canonical ``Barcode``,
   so "012345678905", "0012345678905" and "0 12345 67890 5" all match the same
   recall record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterator

from PIL import Image, ImageFilter, ImageOps

try:
    import zxingcpp
except ImportError:  # pragma: no cover - reported to the user by the UI
    zxingcpp = None

try:  # Optional second decoder; needs the system zbar library.
    from pyzbar import pyzbar
except Exception:  # pragma: no cover - ImportError or missing shared library
    pyzbar = None

MAX_SIDE = 2200  # Larger photos are downscaled first; decoding cost grows with area.
MIN_SIDE_FOR_UPSCALE = 1100
RETAIL_FORMATS = {"EAN-13", "UPC-A", "UPC-E", "EAN-8", "ITF-14", "ITF"}


# --------------------------------------------------------------------------
# Check digits and normalisation
# --------------------------------------------------------------------------

def check_digit(body: str) -> str:
    """GS1 mod-10 check digit for a digit string that excludes the check digit."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def has_valid_check_digit(code: str) -> bool:
    return code.isdigit() and len(code) in (8, 12, 13, 14) and check_digit(code[:-1]) == code[-1]


def expand_upce(code: str) -> str | None:
    """Expand a UPC-E code (6, 7 or 8 digits) to its 12-digit UPC-A form."""
    if not code.isdigit() or len(code) not in (6, 7, 8):
        return None
    if len(code) == 6:
        system, body, given = "0", code, None
    elif len(code) == 7:
        system, body, given = code[0], code[1:], None
    else:
        system, body, given = code[0], code[1:7], code[7]
    if system not in "01":
        return None
    d = body
    if d[5] in "012":
        middle = d[0:2] + d[5] + "0000" + d[2:5]
    elif d[5] == "3":
        middle = d[0:3] + "00000" + d[3:5]
    elif d[5] == "4":
        middle = d[0:4] + "00000" + d[4]
    else:
        middle = d[0:5] + "0000" + d[5]
    upca = system + middle
    upca += check_digit(upca)
    if given is not None and given != upca[-1]:
        return None
    return upca


@dataclass(frozen=True)
class Barcode:
    """A product code in canonical form."""

    gtin: str  # 14 digits, zero padded; empty for non-GTIN codes
    raw: str  # what the decoder or the user supplied
    symbology: str = ""
    checksum_ok: bool = True
    lot: str = ""
    expiry: str = ""  # YYYY-MM-DD when a GS1 code carried one
    note: str = ""

    @property
    def is_gtin(self) -> bool:
        return bool(self.gtin)

    @property
    def upc(self) -> str:
        """12-digit UPC-A when the code fits in one, otherwise the shortest GTIN form."""
        if not self.gtin:
            return self.raw
        if self.gtin.startswith("00"):
            return self.gtin[2:]
        if self.gtin.startswith("0"):
            return self.gtin[1:]
        return self.gtin

    @property
    def display(self) -> str:
        return self.upc

    def variants(self) -> list[str]:
        """Every digit-string spelling of this code that a database might hold."""
        if not self.gtin:
            return [self.raw] if self.raw else []
        out = [self.gtin]
        if self.gtin.startswith("0"):
            out.append(self.gtin[1:])  # EAN-13
        if self.gtin.startswith("00"):
            out.append(self.gtin[2:])  # UPC-A
            out.append(self.gtin[2:-1])  # UPC-A printed without its check digit
            out.append(self.gtin[3:-1])  # 10-digit core (manufacturer + item)
        seen: list[str] = []
        for v in out:
            if v and v not in seen:
                seen.append(v)
        return seen

    def ndc_candidates(self) -> list[str]:
        """Possible hyphenated NDCs when this is a US drug code.

        Drug UPCs are "3" + the 10-digit NDC + check digit. The NDC's three
        segments are not marked in the barcode, so all three legal layouts
        (4-4-2, 5-3-2, 5-4-1) are returned for the caller to try.
        """
        if not self.gtin.startswith("003"):
            return []
        ndc = self.gtin[3:13]
        return [
            f"{ndc[:4]}-{ndc[4:8]}-{ndc[8:]}",
            f"{ndc[:5]}-{ndc[5:8]}-{ndc[8:]}",
            f"{ndc[:5]}-{ndc[5:9]}-{ndc[9:]}",
        ]


_GS1_FIXED = {"00": 18, "01": 14, "02": 14, "11": 6, "12": 6, "13": 6, "15": 6, "16": 6, "17": 6, "20": 2}
_GS1_VARIABLE = {"10": 20, "21": 20, "22": 20, "240": 30, "241": 30, "30": 8, "37": 8}


def parse_gs1(text: str) -> dict[str, str]:
    """Parse GS1 element strings such as ``(01)00300450449109(17)270630(10)AB12``.

    Accepts the bracketed human-readable form and the raw form in which
    variable-length fields end with a group separator.
    """
    text = text.strip()
    for prefix in ("]d2", "]C1", "]e0", "]Q3"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if "(" in text:
        return {ai: value.strip() for ai, value in re.findall(r"\((\d{2,4})\)([^(]*)", text)}
    out: dict[str, str] = {}
    i = 0
    while i < len(text):
        if text[i] == "\x1d":
            i += 1
            continue
        for width in (2, 3, 4):
            ai = text[i:i + width]
            if ai in _GS1_FIXED:
                size = _GS1_FIXED[ai]
                out[ai] = text[i + width:i + width + size]
                i += width + size
                break
            if ai in _GS1_VARIABLE:
                end = text.find("\x1d", i + width)
                end = len(text) if end == -1 else end
                end = min(end, i + width + _GS1_VARIABLE[ai])
                out[ai] = text[i + width:end]
                i = end
                break
        else:
            return out  # Unknown field: keep what was parsed so far.
    return out


def _gs1_date(yymmdd: str) -> str:
    if not re.fullmatch(r"\d{6}", yymmdd):
        return ""
    day = yymmdd[4:] if yymmdd[4:] != "00" else "01"
    return f"20{yymmdd[:2]}-{yymmdd[2:4]}-{day}"


def parse(text: str, symbology: str = "") -> Barcode | None:
    """Normalise decoder output or typed input. Returns None if nothing usable."""
    raw = (text or "").strip()
    if not raw:
        return None

    looks_gs1 = raw.startswith(("(01)", "]d2", "]C1", "]e0", "]Q3")) or (
        symbology in {"Data Matrix", "DataMatrix", "QR Code", "Code 128", "DataBar"}
        and re.match(r"01\d{14}", raw) is not None
    )
    if looks_gs1:
        fields = parse_gs1(raw)
        gtin = fields.get("01", "")
        if len(gtin) == 14 and gtin.isdigit():
            return Barcode(
                gtin=gtin,
                raw=raw,
                symbology=symbology or "GS1",
                checksum_ok=has_valid_check_digit(gtin),
                lot=fields.get("10", ""),
                expiry=_gs1_date(fields.get("17", "")),
            )

    digits = re.sub(r"[\s\-.]", "", raw)
    if not digits.isdigit():
        # Not a product number (a URL in a QR code, a serial number, ...).
        return Barcode(gtin="", raw=raw, symbology=symbology, note="Not a product barcode")

    note = ""
    if symbology == "UPC-E" or (len(digits) in (6, 7) and not symbology):
        expanded = expand_upce(digits)
        if expanded:
            digits, note = expanded, "Expanded from UPC-E"
    elif len(digits) == 8 and not symbology:
        # Typed 8 digits: EAN-8 if the check digit works, otherwise try UPC-E.
        if not has_valid_check_digit(digits):
            expanded = expand_upce(digits)
            if expanded:
                digits, note = expanded, "Expanded from UPC-E"
    elif len(digits) == 11:
        digits, note = digits + check_digit(digits), "Check digit added"

    if len(digits) not in (8, 12, 13, 14):
        return Barcode(
            gtin="", raw=digits, symbology=symbology, checksum_ok=False,
            note=f"{len(digits)} digits is not a standard barcode length (8, 12, 13 or 14)",
        )
    ok = has_valid_check_digit(digits)
    return Barcode(
        gtin=digits.zfill(14),
        raw=raw,
        symbology=symbology,
        checksum_ok=ok,
        note=note if ok else "Check digit does not match; one digit may be wrong",
    )


def digits_in_text(code_variants: list[str], text: str) -> str | None:
    """Return the variant found in free text, ignoring spaces and hyphens inside numbers.

    Recall notices print UPCs as "0 12345 67890 5" or "12345-67890" as often as
    not, so runs of digits are compared with their separators removed. Only
    variants of 11 or more digits are used; shorter cores collide with lot
    numbers and dates.
    """
    text = text or ""
    runs = {re.sub(r"\D", "", m) for m in re.findall(r"\d[\d \-]{6,22}\d", text)}
    runs |= set(re.findall(r"\d{11,14}", text))  # Several codes listed with single spaces between them.
    for variant in code_variants:
        if len(variant) < 11:
            continue
        for run in runs:
            if run == variant or (len(run) > len(variant) and run.lstrip("0") == variant.lstrip("0")):
                return variant
    return None


# --------------------------------------------------------------------------
# Image decoding
# --------------------------------------------------------------------------

@dataclass
class Detection:
    barcode: Barcode
    stage: str  # which treatment found it
    box: tuple[int, int, int, int] | None = None  # left, top, right, bottom in the prepared image
    decoder: str = "zxing"


@dataclass
class DecodeResult:
    detections: list[Detection] = field(default_factory=list)
    stages_tried: list[str] = field(default_factory=list)
    image_size: tuple[int, int] = (0, 0)
    hint: str = ""

    @property
    def best(self) -> Detection | None:
        return self.detections[0] if self.detections else None


def _prepare(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)  # Phone photos carry their rotation in EXIF.
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    longest = max(image.size)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    return image


def _stages(image: Image.Image) -> Iterator[tuple[str, Callable[[], Image.Image], dict]]:
    """Image treatments in order of cost. Each yields (name, image factory, decoder options)."""
    gray = image.convert("L")
    yield "original", lambda: image, {}
    yield "contrast stretch", lambda: ImageOps.autocontrast(gray, cutoff=2), {}
    yield "sharpen", lambda: gray.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=2)), {}
    if zxingcpp is not None:
        # A global threshold copes with soft gradients that defeat local averaging.
        yield "global threshold", lambda: gray, {"binarizer": zxingcpp.Binarizer.GlobalHistogram}
    yield "denoise", lambda: ImageOps.autocontrast(gray.filter(ImageFilter.MedianFilter(3)), cutoff=1), {}
    yield "equalise", lambda: ImageOps.equalize(gray), {}

    if max(image.size) < MIN_SIDE_FOR_UPSCALE:
        def upscaled() -> Image.Image:
            big = gray.resize((gray.width * 2, gray.height * 2), Image.LANCZOS)
            return big.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=2))
        yield "upscale 2x", upscaled, {}

    # The decoder handles 90 degree turns itself but not a package held at an angle.
    for angle in (15, -15, 30, -30, 45):
        yield (
            f"rotate {angle}",
            lambda a=angle: ImageOps.autocontrast(gray, cutoff=1).rotate(a, Image.BICUBIC, expand=True, fillcolor=255),
            {},
        )

    # A small code in a wide shot: zoom into overlapping regions and enlarge them.
    w, h = gray.size
    regions = {
        "centre crop": (0.2, 0.2, 0.8, 0.8),
        "top-left crop": (0.0, 0.0, 0.6, 0.6),
        "top-right crop": (0.4, 0.0, 1.0, 0.6),
        "bottom-left crop": (0.0, 0.4, 0.6, 1.0),
        "bottom-right crop": (0.4, 0.4, 1.0, 1.0),
    }
    for name, (x0, y0, x1, y1) in regions.items():
        def crop(b=(x0, y0, x1, y1)) -> Image.Image:
            part = gray.crop((round(b[0] * w), round(b[1] * h), round(b[2] * w), round(b[3] * h)))
            if max(part.size) < 1600:
                part = part.resize((part.width * 2, part.height * 2), Image.LANCZOS)
            return ImageOps.autocontrast(part, cutoff=1)
        yield name, crop, {}

    # Under- and over-exposed shots.
    for label, gamma in (("brighten", 0.5), ("darken", 1.8)):
        table = [round(255 * (i / 255) ** gamma) for i in range(256)]
        yield label, lambda t=table: gray.point(t), {}


def _read(image: Image.Image, options: dict) -> list[tuple[str, str, tuple | None, str]]:
    """Run the available decoders. Returns (text, symbology, box, decoder) tuples."""
    found: list[tuple[str, str, tuple | None, str]] = []
    if zxingcpp is not None:
        for item in zxingcpp.read_barcodes(image, **options):
            if not item.valid or not item.text:
                continue
            p = item.position
            xs = [p.top_left.x, p.top_right.x, p.bottom_right.x, p.bottom_left.x]
            ys = [p.top_left.y, p.top_right.y, p.bottom_right.y, p.bottom_left.y]
            found.append((item.text, str(item.format), (min(xs), min(ys), max(xs), max(ys)), "zxing"))
    if not found and pyzbar is not None:
        for item in pyzbar.decode(image):
            text = item.data.decode("utf-8", "replace")
            names = {"EAN13": "EAN-13", "UPCA": "UPC-A", "UPCE": "UPC-E", "EAN8": "EAN-8"}
            r = item.rect
            box = (r.left, r.top, r.left + r.width, r.top + r.height)
            found.append((text, names.get(item.type, item.type), box, "zbar"))
    return found


def decode_image(image: Image.Image, exhaustive: bool = False) -> DecodeResult:
    """Find barcodes in a photo.

    Stops at the first treatment that produces a code with a valid check
    digit. With ``exhaustive`` every treatment runs, which finds more codes
    when several products are in one photo.
    """
    result = DecodeResult()
    if zxingcpp is None and pyzbar is None:
        result.hint = "No barcode decoder is installed. Run: pip install zxing-cpp"
        return result

    prepared = _prepare(image)
    result.image_size = prepared.size
    seen: dict[str, Detection] = {}

    for name, make, options in _stages(prepared):
        result.stages_tried.append(name)
        try:
            treated = make()
            reads = _read(treated, options)
        except Exception:  # A failed treatment must not abort the scan.
            continue
        for text, symbology, box, decoder in reads:
            code = parse(text, symbology)
            if code is None:
                continue
            key = code.gtin or code.raw
            if key in seen:
                continue
            # Boxes are only meaningful when the treated image shares the original geometry.
            same_geometry = treated.size == prepared.size
            seen[key] = Detection(code, name, box if same_geometry else None, decoder)
        if not exhaustive and any(d.barcode.is_gtin and d.barcode.checksum_ok for d in seen.values()):
            break

    def rank(d: Detection) -> tuple:
        product = d.barcode.is_gtin and d.barcode.checksum_ok
        retail = d.barcode.symbology in RETAIL_FORMATS
        area = (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]) if d.box else 0
        return (not product, not retail, -area)

    result.detections = sorted(seen.values(), key=rank)
    if not result.detections:
        result.hint = _hint(prepared)
    return result


def _hint(image: Image.Image) -> str:
    """Tell the user why a photo probably failed, from simple image statistics."""
    gray = image.convert("L")
    small = gray.resize((min(gray.width, 400), max(1, round(gray.height * min(gray.width, 400) / gray.width))))
    histogram = small.histogram()
    total = sum(histogram)
    mean = sum(i * n for i, n in enumerate(histogram)) / total
    edges = small.filter(ImageFilter.FIND_EDGES).histogram()
    edge_mean = sum(i * n for i, n in enumerate(edges)) / sum(edges)
    if mean < 55:
        return "The photo is very dark. Move to better light or turn on the flash."
    if mean > 215:
        return "The photo is washed out. Tilt the package to avoid glare."
    if edge_mean < 6:
        return "The photo looks blurry. Hold steady and let the camera focus on the barcode."
    if max(image.size) < 500:
        return "The photo is low resolution. Move closer so the barcode fills more of the frame."
    return "No barcode found. Fill the frame with the barcode, keep it flat, and avoid glare."
