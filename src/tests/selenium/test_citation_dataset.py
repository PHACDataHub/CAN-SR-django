from django.urls import reverse

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from my_app.model_factories import (
    CitationDatasetColumnFactory,
    CitationDatasetFactory,
    CitationFactory,
)

MODAL = (By.ID, "delete-citation-modal")


@pytest.fixture
def citation_dataset(admin_user, force_login):
    dataset = CitationDatasetFactory(review__title="Community health review")
    column = CitationDatasetColumnFactory(
        dataset=dataset, name="Publication year"
    )
    citation = CitationFactory(
        dataset=dataset,
        title="Community health outreach in rural areas",
        abstract="A study of access to community health services in rural areas.",
        doi="10.1234/community-health",
        data={column.name: "2023"},
    )
    force_login(admin_user)
    return dataset, column, citation


def test_add_and_edit_citation(
    live_server, driver, citation_dataset, save_screenshot
):
    dataset, column, original = citation_dataset
    dataset_url = live_server.url + reverse(
        "citation_dataset_detail", args=[dataset.review_id]
    )
    wait = WebDriverWait(driver, 10)
    year_field = f"columns-{column.pk}-value"

    driver.get(dataset_url)
    assert save_screenshot(driver, "citation-dataset-table").is_file()
    driver.find_element(By.LINK_TEXT, "Manually add citation").click()
    add_url = driver.current_url
    assert (
        driver.find_element(By.TAG_NAME, "h1").text == "Manually add citation"
    )
    driver.find_element(By.NAME, "title").send_keys("Mobile health clinics")
    driver.find_element(By.NAME, "abstract").send_keys(
        "An evaluation of mobile clinics in underserved communities."
    )
    driver.find_element(By.NAME, "doi").send_keys("10.1234/mobile-clinics")
    driver.find_element(By.NAME, year_field).send_keys("2024")
    assert save_screenshot(driver, "citation-add-form").is_file()
    driver.find_element(
        By.XPATH, "//button[normalize-space()='Save citation']"
    ).click()

    wait.until(ec.url_changes(add_url))
    citation = dataset.rows.get(title="Mobile health clinics")
    detail_url = live_server.url + reverse(
        "citation_detail", args=[dataset.review_id, citation.pk]
    )
    wait.until(ec.url_to_be(detail_url))
    assert citation.order == original.order + 1
    assert citation.data == {column.name: "2024"}

    driver.get(dataset_url)
    driver.find_element(
        By.LINK_TEXT, f"#{citation.pk} {citation.title}"
    ).click()
    wait.until(ec.url_to_be(detail_url))
    details = driver.find_element(By.TAG_NAME, "dl").text
    assert f"#{citation.pk} {citation.title}" in details
    assert citation.abstract in details
    assert citation.doi in details
    assert "2024" in details
    assert save_screenshot(driver, "citation-detail").is_file()

    driver.find_element(By.LINK_TEXT, "Edit citation").click()
    assert (
        driver.find_element(By.TAG_NAME, "h1").text
        == f"Edit citation #{citation.pk}"
    )
    year = driver.find_element(By.NAME, year_field)
    assert year.get_property("value") == "2024"
    assert save_screenshot(driver, "citation-edit-form").is_file()
    year.clear()
    year.send_keys("2025")
    driver.find_element(
        By.XPATH, "//button[normalize-space()='Save citation']"
    ).click()
    wait.until(ec.url_to_be(detail_url))
    citation.refresh_from_db()
    assert citation.data == {column.name: "2025"}
    assert "2025" in driver.find_element(By.TAG_NAME, "dl").text


def test_delete_citation_requires_confirmation(
    live_server, driver, citation_dataset, save_screenshot
):
    dataset, _, citation = citation_dataset
    dataset_url = live_server.url + reverse(
        "citation_dataset_detail", args=[dataset.review_id]
    )
    driver.get(dataset_url)
    driver.find_element(
        By.LINK_TEXT, f"#{citation.pk} {citation.title}"
    ).click()

    wait = WebDriverWait(driver, 10)
    delete_url = reverse(
        "delete_citation", args=[dataset.review_id, citation.pk]
    )
    delete_button = (By.CSS_SELECTOR, f"button[hx-get='{delete_url}']")
    confirm_button = (
        By.CSS_SELECTOR,
        "#delete-citation-modal button[type='submit']",
    )
    wait.until(ec.element_to_be_clickable(delete_button)).click()
    modal = wait.until(ec.visibility_of_element_located(MODAL))
    assert f"#{citation.pk} {citation.title}" in modal.text
    assert save_screenshot(driver, "citation-delete-confirmation").is_file()

    modal.find_element(
        By.CSS_SELECTOR, ".modal-footer [data-modal-close]"
    ).click()
    wait.until(ec.invisibility_of_element_located(MODAL))
    assert dataset.rows.filter(pk=citation.pk).exists()

    wait.until(ec.element_to_be_clickable(delete_button)).click()
    wait.until(ec.element_to_be_clickable(confirm_button)).click()
    checkbox = driver.find_element(
        By.CSS_SELECTOR, "#delete-citation-modal [name='confirm']:invalid"
    )
    assert checkbox.is_displayed()
    assert dataset.rows.filter(pk=citation.pk).exists()

    checkbox.click()
    wait.until(ec.element_to_be_clickable(confirm_button)).click()
    wait.until(ec.url_to_be(dataset_url))
    assert "Citation deleted." in driver.find_element(By.TAG_NAME, "body").text
    assert not driver.find_elements(
        By.LINK_TEXT, f"#{citation.pk} {citation.title}"
    )
    assert not dataset.rows.filter(pk=citation.pk).exists()
    assert save_screenshot(driver, "citation-deleted").is_file()
