import numpy as np
import pytest
import zxingcpp
from PIL import Image, ImageFilter

from healthcheck import barcode as bc


def render(content: str, fmt, scale: int = 3) -> Image.Image:
    code = zxingcpp.create_barcode(content, fmt)
    return Image.fromarray(np.array(zxingcpp.write_barcode_to_image(code, scale=scale)))


def on_photo(code_img: Image.Image, size=(1600, 1200), at=(900, 700), angle=0) -> Image.Image:
    """Paste a barcode into a larger noisy frame, like a package on a table."""
    rng = np.random.default_rng(7)
    frame = Image.fromarray(rng.integers(90, 170, (size[1], size[0]), dtype=np.uint8)).filter(ImageFilter.GaussianBlur(6))
    if angle:
        code_img = code_img.rotate(angle, Image.BICUBIC, expand=True, fillcolor=255)
    frame.paste(code_img, at)
    return frame


# ---- normalisation -------------------------------------------------------

def test_check_digit():
    assert bc.check_digit("01234567890") == "5"
    assert bc.has_valid_check_digit("012345678905")
    assert not bc.has_valid_check_digit("012345678906")
    assert bc.has_valid_check_digit("4006381333931")  # EAN-13


@pytest.mark.parametrize("text", ["012345678905", "0012345678905", "0 12345 67890 5", "01234567890", "00012345678905"])
def test_same_product_any_spelling(text):
    code = bc.parse(text)
    assert code.gtin == "00012345678905"
    assert code.upc == "012345678905"
    assert code.checksum_ok


def test_variants_cover_database_spellings():
    v = bc.parse("708953651019").variants()
    assert {"708953651019", "0708953651019", "00708953651019", "70895365101"} <= set(v)


def test_bad_check_digit_is_flagged_not_dropped():
    code = bc.parse("012345678906")
    assert code.is_gtin and not code.checksum_ok
    assert "digit" in code.note


def test_upce_expansion():
    assert bc.expand_upce("01234565") == "012345000065"
    assert bc.parse("01234565", "UPC-E").upc == "012345000065"
    assert bc.expand_upce("01234569") is None  # wrong check digit


def test_non_product_codes_are_kept_but_marked():
    code = bc.parse("https://example.com/p/1", "QR Code")
    assert not code.is_gtin and code.note


def test_wrong_length_is_explained():
    code = bc.parse("12345")
    assert not code.is_gtin and "length" in code.note


def test_gs1_datamatrix_gives_gtin_lot_expiry_and_ndc():
    code = bc.parse("(01)00300450449109(17)270630(10)AB12")
    assert code.gtin == "00300450449109"
    assert code.lot == "AB12" and code.expiry == "2027-06-30"
    assert "0045-0449-10" in code.ndc_candidates()
    raw = bc.parse("0100300450449109172706301" + "0AB12", "Data Matrix")
    assert raw.gtin == "00300450449109" and raw.lot == "AB12"


def test_drug_upc_ndc_candidates():
    code = bc.parse("341520745404"[:11])  # check digit computed
    assert code.ndc_candidates() == ["4152-0745-40", "41520-745-40", "41520-7454-0"]
    assert bc.parse("012345678905").ndc_candidates() == []


def test_digits_in_text_handles_recall_notice_formatting():
    v = bc.parse("012345678905").variants()
    assert bc.digits_in_text(v, "UPC 0 12345 67890 5, lot 22A")
    assert bc.digits_in_text(v, "UPCs 850043378020 012345678905 850043378037")
    assert bc.digits_in_text(v, "GTIN 00012345678905")
    assert not bc.digits_in_text(v, "Lot 1234567890 best by 2026")
    assert not bc.digits_in_text(v, "UPC 012345678912")


# ---- image decoding ------------------------------------------------------

def test_clean_barcode_decodes_on_first_stage():
    result = bc.decode_image(render("012345678905", zxingcpp.BarcodeFormat.UPCA))
    assert result.best.barcode.upc == "012345678905"
    assert result.best.stage == "original"


def test_small_barcode_in_large_frame():
    photo = on_photo(render("012345678905", zxingcpp.BarcodeFormat.UPCA, scale=1))
    assert bc.decode_image(photo).best.barcode.upc == "012345678905"


def test_tilted_barcode():
    photo = on_photo(render("4006381333931", zxingcpp.BarcodeFormat.EAN13, scale=2), angle=25)
    assert bc.decode_image(photo).best.barcode.gtin == "04006381333931"


def test_low_contrast_barcode():
    img = render("012345678905", zxingcpp.BarcodeFormat.UPCA)
    faded = Image.fromarray((np.array(img) * 0.12 + 120).astype(np.uint8))
    assert bc.decode_image(faded).best.barcode.upc == "012345678905"


def test_two_products_in_one_photo():
    frame = on_photo(render("012345678905", zxingcpp.BarcodeFormat.UPCA, scale=2), at=(100, 100))
    frame.paste(render("4006381333931", zxingcpp.BarcodeFormat.EAN13, scale=2), (900, 800))
    found = {d.barcode.gtin for d in bc.decode_image(frame, exhaustive=True).detections}
    assert found == {"00012345678905", "04006381333931"}


def test_no_barcode_gives_actionable_hint():
    dark = Image.new("L", (800, 600), 20)
    result = bc.decode_image(dark)
    assert not result.detections and "dark" in result.hint
    assert len(result.stages_tried) > 10  # everything was attempted
