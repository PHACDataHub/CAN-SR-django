import os
import re
from io import BytesIO
from pathlib import Path
from shutil import copyfile

BASELINE_DIR = Path(__file__).parent / "baselines"
RESULT_DIR = Path(__file__).resolve().parents[3] / "test-results" / "visual"
CHANNEL_TOLERANCE = 20
VIEWPORT_SIZE = (1280, 800)


def _prepare_page(driver):
    from selenium.webdriver.support.ui import WebDriverWait

    width, height = VIEWPORT_SIZE
    driver.set_window_size(width, height)
    driver.execute_cdp_cmd(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": height,
            "deviceScaleFactor": 1,
            "mobile": False,
        },
    )
    WebDriverWait(driver, 10).until(
        lambda browser: browser.execute_script(
            "return document.readyState === 'complete' "
            "&& document.fonts.status === 'loaded' "
            "&& Array.from(document.images).every(image => image.complete)"
        )
    )
    driver.execute_script(
        """
        document.activeElement.blur();
        window.scrollTo(0, 0);
        const style = document.createElement('style');
        style.textContent = `*, *::before, *::after {
            animation: none !important;
            transition: none !important;
            caret-color: transparent !important;
        } html, body { scroll-behavior: auto !important; }`;
        document.head.appendChild(style);
        """
    )


def _difference(expected, actual):
    from PIL import Image, ImageChops, ImageOps

    width = max(expected.width, actual.width)
    height = max(expected.height, actual.height)
    expected_canvas = Image.new("RGB", (width, height), "white")
    actual_canvas = Image.new("RGB", (width, height), "white")
    expected_canvas.paste(expected)
    actual_canvas.paste(actual)

    red, green, blue = ImageChops.difference(
        expected_canvas, actual_canvas
    ).split()
    mask = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(
        lambda value: 255 if value > CHANNEL_TOLERANCE else 0
    )
    if expected.width != actual.width:
        mask.paste(255, (min(expected.width, actual.width), 0, width, height))
    if expected.height != actual.height:
        mask.paste(
            255, (0, min(expected.height, actual.height), width, height)
        )

    changed_pixels = mask.histogram()[255]
    fraction = changed_pixels / (width * height)
    diff = ImageOps.grayscale(expected_canvas).convert("RGB")
    diff.paste(Image.new("RGB", (width, height), "red"), mask=mask)
    return fraction, diff


def _color_signature(image):
    pixels = image.width * image.height
    colors = image.getcolors(pixels)
    background = max(colors, key=lambda item: item[0])[1]
    text_colors = [
        color
        for count, color in colors
        if count >= max(10, pixels * 0.005) and sum(color) / 3 < 225
    ]
    if not text_colors:
        return None
    text = min(text_colors, key=sum)
    return background, text


def _same_colors(expected, actual, tolerance=8):
    expected_signature = _color_signature(expected)
    actual_signature = _color_signature(actual)
    if expected_signature is None or actual_signature is None:
        return False
    return all(
        abs(expected_channel - actual_channel) <= tolerance
        for expected_color, actual_color in zip(
            expected_signature, actual_signature
        )
        for expected_channel, actual_channel in zip(
            expected_color, actual_color
        )
    )


def compare_screenshot(
    driver,
    baseline_name,
    threshold=0.005,
    update_baseline=False,
    element=None,
    comparison="pixels",
):
    from PIL import Image

    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", baseline_name):
        raise ValueError(
            "baseline_name must contain only letters, digits, - or _"
        )
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    if comparison not in {"pixels", "colors"}:
        raise ValueError("comparison must be 'pixels' or 'colors'")
    if update_baseline and os.environ.get("CI"):
        raise RuntimeError("Visual baselines cannot be updated in CI")

    baseline_path = BASELINE_DIR / f"{baseline_name}.png"
    result_path = RESULT_DIR / baseline_name
    for name in ("expected.png", "actual.png", "diff.png"):
        (result_path / name).unlink(missing_ok=True)

    try:
        _prepare_page(driver)
        if element is not None:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});",
                element,
            )
            bounds = driver.execute_script(
                """const rect = arguments[0].getBoundingClientRect();
                return [rect.left, rect.top, rect.right, rect.bottom];""",
                element,
            )
            viewport = Image.open(
                BytesIO(driver.get_screenshot_as_png())
            ).convert("RGB")
            if (
                bounds[0] < 0
                or bounds[1] < 0
                or bounds[2] > viewport.width
                or bounds[3] > viewport.height
            ):
                raise AssertionError(
                    f"Snapshot element is outside the viewport: {bounds}"
                )
            actual = viewport.crop(tuple(round(edge) for edge in bounds))
        else:
            actual = Image.open(
                BytesIO(driver.get_screenshot_as_png())
            ).convert("RGB")
    finally:
        driver.execute_cdp_cmd("Emulation.clearDeviceMetricsOverride", {})

    if update_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        actual.save(baseline_path)
        return

    if not baseline_path.exists():
        result_path.mkdir(parents=True, exist_ok=True)
        actual.save(result_path / "actual.png")
        raise AssertionError(
            f"Missing visual baseline {baseline_path}. "
            "Run with --update-visual-baselines to create it."
        )

    with Image.open(baseline_path) as image:
        expected = image.convert("RGB")
    if comparison == "colors" and _same_colors(expected, actual):
        return
    difference, diff = _difference(expected, actual)
    if (
        comparison == "pixels"
        and difference <= threshold
        and expected.size == actual.size
    ):
        return

    result_path.mkdir(parents=True, exist_ok=True)
    copyfile(baseline_path, result_path / "expected.png")
    actual.save(result_path / "actual.png")
    diff.save(result_path / "diff.png")
    dimensions = ""
    if expected.size != actual.size:
        dimensions = (
            f"; dimensions {expected.size} expected, {actual.size} actual"
        )
    if comparison == "colors":
        raise AssertionError(
            f"Visual colors differ for {baseline_name}{dimensions}. "
            f"See {result_path}."
        )
    raise AssertionError(
        f"Visual difference for {baseline_name}: {difference:.2%} "
        f"(threshold {threshold:.2%}){dimensions}. "
        f"See {result_path}."
    )
