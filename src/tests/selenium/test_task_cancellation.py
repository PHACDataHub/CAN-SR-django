from django.urls import reverse

from my_app.model_factories import ReviewFactory, ReviewUserLinkFactory
from my_app.models import CancellationGeneration


def test_review_member_can_cancel_review_tasks(
    live_server, driver, vanilla_user, force_login, save_screenshot
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    review = ReviewFactory(
        title="Air quality and respiratory health",
        description="Review of public health evidence on outdoor air quality.",
    )
    ReviewUserLinkFactory(review=review, user=vanilla_user)
    detail_url = live_server.url + reverse("review_detail", args=[review.pk])
    cancel_url = reverse("cancel_review_tasks", args=[review.pk])
    cancel_link = (By.CSS_SELECTOR, f"#content a[href='{cancel_url}']")
    wait = WebDriverWait(driver, 10)

    force_login(vanilla_user)
    driver.get(detail_url)
    link = wait.until(ec.element_to_be_clickable(cancel_link))
    assert link.text == "Cancel tasks for this review"
    assert save_screenshot(driver, "task-cancellation-review-action").is_file()
    link.click()

    assert wait.until(
        ec.visibility_of_element_located((By.TAG_NAME, "h1"))
    ).text == ("Cancel tasks for this review")
    assert save_screenshot(
        driver, "task-cancellation-review-confirmation"
    ).is_file()
    driver.find_element(By.LINK_TEXT, "Go back").click()
    wait.until(ec.url_to_be(detail_url))
    assert not CancellationGeneration.objects.exists()

    driver.find_element(*cancel_link).click()
    driver.find_element(
        By.CSS_SELECTOR, "#content button[type='submit']"
    ).click()
    wait.until(ec.url_to_be(detail_url))
    success = wait.until(
        ec.visibility_of_element_located((By.CSS_SELECTOR, ".alert-success"))
    )
    assert "Task cancellation requested for this review." in success.text
    assert CancellationGeneration.objects.get().review_id == review.pk
    assert save_screenshot(
        driver, "task-cancellation-review-success"
    ).is_file()


def test_admin_can_cancel_tasks_across_reviews(
    live_server, driver, admin_user, force_login, save_screenshot
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    ReviewFactory(title="Air quality and respiratory health", description="")
    ReviewFactory(title="Public health surveillance", description="")
    review_list_url = live_server.url + reverse("review_list")
    cancel_url = reverse("cancel_all_tasks")
    wait = WebDriverWait(driver, 10)

    force_login(admin_user)
    driver.get(review_list_url)
    driver.find_element(By.ID, "navbarDropdown").click()
    link = wait.until(
        ec.element_to_be_clickable(
            (By.CSS_SELECTOR, f".dropdown-menu a[href='{cancel_url}']")
        )
    )
    assert link.text == "Cancel tasks across all reviews"
    assert driver.execute_script(
        "return arguments[0].getBoundingClientRect().right <= window.innerWidth",
        link,
    )
    assert save_screenshot(driver, "task-cancellation-admin-menu").is_file()
    link.click()

    assert wait.until(
        ec.visibility_of_element_located((By.TAG_NAME, "h1"))
    ).text == ("Cancel tasks across all reviews")
    assert not CancellationGeneration.objects.exists()
    assert save_screenshot(
        driver, "task-cancellation-global-confirmation"
    ).is_file()
    driver.find_element(
        By.CSS_SELECTOR, "#content button[type='submit']"
    ).click()
    wait.until(ec.url_to_be(review_list_url))
    success = wait.until(
        ec.visibility_of_element_located((By.CSS_SELECTOR, ".alert-success"))
    )
    assert "Task cancellation requested across all reviews." in success.text
    assert CancellationGeneration.objects.get().review_id is None
    assert save_screenshot(
        driver, "task-cancellation-global-success"
    ).is_file()


def test_user_without_permissions_cannot_open_cancellation_pages(
    live_server, driver, vanilla_user, force_login, save_screenshot
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    global_url = reverse("cancel_all_tasks")
    review = ReviewFactory()
    wait = WebDriverWait(driver, 10)

    force_login(vanilla_user)
    driver.get(live_server.url + reverse("review_list"))
    driver.find_element(By.ID, "navbarDropdown").click()
    menu = wait.until(
        ec.visibility_of_element_located((By.CSS_SELECTOR, ".dropdown-menu"))
    )
    assert not menu.find_elements(By.CSS_SELECTOR, f"a[href='{global_url}']")
    assert save_screenshot(driver, "task-cancellation-member-menu").is_file()

    for scope, url in (
        ("global", global_url),
        ("review", reverse("cancel_review_tasks", args=[review.pk])),
    ):
        driver.get(live_server.url + url)
        assert "Forbidden" in driver.title
        assert save_screenshot(
            driver, f"task-cancellation-{scope}-forbidden"
        ).is_file()
    assert not CancellationGeneration.objects.exists()
