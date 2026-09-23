from django.urls import reverse


def test_login_page_visual(live_server, driver, assert_screenshot_matches):
    driver.get(live_server.url + "/health/live")
    driver.delete_all_cookies()
    driver.get(live_server.url + reverse("login"))

    assert "Log in" in driver.title
    assert driver.find_element(
        "css selector", "#login-container form"
    ).is_displayed()
    assert_screenshot_matches(driver, baseline_name="login-page")
