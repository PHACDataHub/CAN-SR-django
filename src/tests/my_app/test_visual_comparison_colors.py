"""Color comparison preserves state checks across different text wrapping."""

from PIL import Image, ImageDraw

from tests.selenium.visual_comparison_utils import _same_colors


def _review_image(width, height, background, text, *, two_lines=False):
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 12, width - 20, 17), fill=text)
    if two_lines:
        draw.rectangle((10, 29, width - 40, 34), fill=text)
    return image


def test_color_comparison_ignores_text_wrapping_and_image_height():
    background = (209, 231, 221)
    text = (15, 81, 50)
    one_line = _review_image(280, 78, background, text)
    two_lines = _review_image(240, 102, background, text, two_lines=True)

    assert _same_colors(one_line, two_lines)


def test_color_comparison_still_detects_a_changed_review_state():
    agrees = _review_image(280, 78, (209, 231, 221), (15, 81, 50))
    disagrees = _review_image(280, 102, (248, 215, 218), (132, 32, 41))
    missing_text = Image.new("RGB", (280, 78), (209, 231, 221))

    assert not _same_colors(agrees, disagrees)
    assert not _same_colors(agrees, missing_text)
