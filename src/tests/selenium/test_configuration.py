from django.urls import reverse

from proj.models import User


def test_database_isolation_one():
    User.objects.create_user(username="selenium-user")


def test_database_isolation_two():
    User.objects.create_user(username="selenium-user")


def test_browser_login_and_scripts(
    live_server, driver, vanilla_user, force_login
):
    force_login(vanilla_user)

    driver.get(live_server.url + reverse("review_list"))

    assert driver.current_url.endswith(reverse("review_list"))
    assert "login" not in driver.title.lower()
    assert driver.execute_script("return typeof window.htmx") == "object"


def test_login_error_can_be_dismissed(live_server, driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    driver.get(live_server.url + "/health/live")
    driver.delete_all_cookies()
    driver.get(live_server.url + reverse("login"))

    driver.find_element(By.NAME, "username").send_keys("unknown-user")
    driver.find_element(By.NAME, "password").send_keys("wrong-password")
    driver.find_element(By.CSS_SELECTOR, "input[type=submit]").click()

    alert = WebDriverWait(driver, 5).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, ".alert-danger"))
    )
    alert.find_element(By.CSS_SELECTOR, "[data-bs-dismiss=alert]").click()

    WebDriverWait(driver, 5).until(
        EC.invisibility_of_element_located((By.CSS_SELECTOR, ".alert-danger"))
    )
