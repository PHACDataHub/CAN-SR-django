from django.urls import reverse

import pytest
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from my_app.model_factories import CitationDatasetFactory, CitationFactory


@pytest.mark.parametrize(
    "route",
    [
        "l1_citations_list",
        "l2_citations_list",
        "parameter_extraction_citations_list",
    ],
    ids=["l1", "l2", "parameter-extraction"],
)
def test_citation_pagination_visual(
    route,
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    settings,
):
    settings.ENABLE_HTMX_POLLING = False
    dataset = CitationDatasetFactory()
    for order in range(1, 32):
        CitationFactory(
            dataset=dataset,
            order=order,
            abstract="A study of community health outcomes.",
        )

    force_login(admin_user)
    url = live_server.url + reverse(route, args=[dataset.review_id])
    driver.get(url)

    def pagination_at(page, total):
        WebDriverWait(
            driver, 5, ignored_exceptions=(StaleElementReferenceException,)
        ).until(
            lambda browser: browser.find_element(By.ID, "page_x_of_y").text
            == f"Page {page} of {total}"
        )
        return driver.find_element(
            By.CSS_SELECTOR, 'nav[aria-label="Citation pagination"]'
        )

    def capture(state, page, total, labels):
        pagination = pagination_at(page, total)
        groups = pagination.find_elements(By.CLASS_NAME, "btn-group")
        assert len(groups) == bool(labels)
        buttons = pagination.find_elements(By.TAG_NAME, "button")
        assert [button.text for button in buttons] == labels
        assert all(
            button.is_displayed() and button.is_enabled() for button in buttons
        )
        if groups:
            assert groups[0].find_elements(By.TAG_NAME, "button") == buttons
        page_count = pagination.find_element(By.ID, "page_x_of_y")
        ActionChains(driver).move_to_element(page_count).perform()
        snapshot = save_screenshot(
            driver, f"{route}-pagination-{state}", element=pagination
        )
        assert snapshot.is_file()

    def click(page, label):
        pagination_at(page, 4).find_element(
            By.XPATH, f".//button[normalize-space()='{label}']"
        ).click()

    capture("first", 1, 4, ["Next", "Last"])
    click(1, "Next")
    capture("middle", 2, 4, ["First", "Previous", "Next", "Last"])
    click(2, "Last")
    capture("last", 4, 4, ["First", "Previous"])
    click(4, "Previous")
    click(3, "First")
    pagination_at(1, 4)

    dataset.rows.exclude(order=1).delete()
    driver.get(url)
    capture("single-page", 1, 1, [])
