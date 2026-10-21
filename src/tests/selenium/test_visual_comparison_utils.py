from selenium.webdriver.common.by import By

from tests.selenium.visual_comparison_utils import (
    VIEWPORT_SIZE,
    _capture_screenshot,
    scroll_into_view,
)


def test_capture_preserves_viewport_and_scrolls_nested_content(
    driver, live_server, monkeypatch
):
    driver.get(live_server.url + "/health/live")
    driver.execute_script(
        """
        document.body.innerHTML = `
            <div style="height: 900px"></div>
            <div id="sidebar" style="height: 400px; overflow-y: auto; width: 300px">
                <div style="height: 1100px"></div>
                <div id="target" style="width: 280px; height: 80px; background: rgb(12, 34, 56)"></div>
                <details><summary>More information</summary><p>Details</p></details>
            </div>
            <div style="height: 900px"></div>`;
        """
    )
    target = driver.find_element(By.ID, "target")
    capture_png = driver.get_screenshot_as_png
    moved = False

    def capture_during_layout_change():
        nonlocal moved
        if not moved:
            driver.execute_script(
                "arguments[0].style.transform = 'translateY(100px)'", target
            )
            moved = True
        return capture_png()

    monkeypatch.setattr(
        driver, "get_screenshot_as_png", capture_during_layout_change
    )
    for _ in range(2):
        assert driver.execute_script(
            "return [window.innerWidth, window.innerHeight]"
        ) == list(VIEWPORT_SIZE)
        screenshot = _capture_screenshot(driver, target)
        assert screenshot.size == (280, 80)
        assert screenshot.getpixel((140, 40)) == (12, 34, 56)
        assert driver.execute_script(
            "return [window.innerWidth, window.innerHeight]"
        ) == list(VIEWPORT_SIZE)
        assert driver.execute_script(
            "return document.getElementById('sidebar').scrollTop > 0"
        )
    summary = driver.find_element(By.CSS_SELECTOR, "summary")
    scroll_into_view(driver, summary)
    summary.click()
    assert driver.find_element(By.CSS_SELECTOR, "details").get_attribute(
        "open"
    )
