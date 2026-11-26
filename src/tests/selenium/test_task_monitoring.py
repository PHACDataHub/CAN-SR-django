from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

import pytest
from django_tasks_db.compat import TaskResultStatus
from django_tasks_db.models import DBTaskResult, get_date_max

from my_app.views.task_monitoring import TaskListView
from tests.selenium.visual_comparison_utils import set_viewport

SCREENING = "my_app.tasks.l1_screening.process_l1_screening_task"
SHORT_SCREENING = "l1_screening.process_l1_screening_task"
EXTRACTION = (
    "my_app.tasks.parameter_extraction.process_parameter_extraction_task"
)
WORKFLOW = "my_app.tasks.phase2_workflow.check_citation_workflow"


@pytest.fixture
def task_rows():
    now = timezone.now()
    created = DBTaskResult.objects.bulk_create(
        [
            DBTaskResult(
                task_path=path,
                status=status,
                started_at=started,
                finished_at=finished,
                backend_name="default",
                run_after=get_date_max(),
                args_kwargs={"args": [42], "kwargs": {"review_id": 7}},
            )
            for path, status, started, finished in [
                (SCREENING, TaskResultStatus.READY, None, None),
                (
                    EXTRACTION,
                    TaskResultStatus.RUNNING,
                    now - timedelta(seconds=8),
                    None,
                ),
                (
                    WORKFLOW,
                    TaskResultStatus.FAILED,
                    now - timedelta(seconds=35),
                    now - timedelta(seconds=20),
                ),
            ]
        ]
    )
    DBTaskResult.objects.filter(pk__in=[task.pk for task in created]).update(
        enqueued_at=now - timedelta(seconds=45)
    )


def test_admin_filters_background_tasks(
    live_server, driver, admin_user, force_login, save_screenshot, task_rows
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import Select, WebDriverWait

    wait = WebDriverWait(driver, 10)
    force_login(admin_user)
    driver.get(live_server.url + reverse("review_list"))
    driver.find_element(By.ID, "navbarDropdown").click()
    wait.until(
        ec.element_to_be_clickable((By.LINK_TEXT, "Background tasks"))
    ).click()

    rows = (By.CSS_SELECTOR, "#content tbody tr")
    assert len(wait.until(ec.visibility_of_all_elements_located(rows))) == 3
    assert save_screenshot(driver, "task-monitoring-admin-list").is_file()

    task_input = (By.CSS_SELECTOR, "#content input[role='combobox']")
    wait.until(ec.element_to_be_clickable(task_input)).send_keys("screening")
    option = (
        By.XPATH,
        f"//*[@role='listbox']//*[@role='option'][normalize-space(.)='{SHORT_SCREENING}']",
    )
    wait.until(ec.visibility_of_element_located(option))
    assert save_screenshot(
        driver, "task-monitoring-name-autocomplete", preserve_focus=True
    ).is_file()
    wait.until(ec.element_to_be_clickable(option)).click()
    wait.until(
        ec.presence_of_element_located(
            (By.CSS_SELECTOR, f"input[name='task_name'][value='{SCREENING}']")
        )
    )

    Select(driver.find_element(By.NAME, "status")).select_by_value(
        TaskResultStatus.READY
    )
    driver.find_element(
        By.CSS_SELECTOR, "#content button[type='submit']"
    ).click()
    filtered = wait.until(ec.visibility_of_all_elements_located(rows))
    assert len(filtered) == 1
    assert filtered[0].find_element(By.TAG_NAME, "th").text == SHORT_SCREENING
    assert save_screenshot(driver, "task-monitoring-admin-filtered").is_file()

    filtered[0].find_element(By.TAG_NAME, "a").click()
    wait.until(
        ec.url_contains("/phac_admin/django_tasks_database/dbtaskresult/")
    )
    assert "review_id" in driver.find_element(By.ID, "content").text


def test_signed_in_user_sees_task_summary(
    live_server, driver, vanilla_user, force_login, save_screenshot, task_rows
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    wait = WebDriverWait(driver, 10)
    force_login(vanilla_user)
    driver.get(live_server.url + reverse("review_list"))
    driver.find_element(By.ID, "navbarDropdown").click()
    menu = wait.until(
        ec.visibility_of_element_located((By.CSS_SELECTOR, ".dropdown-menu"))
    )
    assert not menu.find_elements(By.LINK_TEXT, "Background tasks")
    menu.find_element(By.LINK_TEXT, "Task summary").click()

    totals = wait.until(
        ec.visibility_of_all_elements_located(
            (By.CSS_SELECTOR, "#content tfoot td")
        )
    )
    assert [cell.text for cell in totals] == ["1", "1", "0", "1"]
    content = driver.find_element(By.ID, "content").text
    assert "review_id" not in content
    assert SHORT_SCREENING in content
    assert SCREENING not in content
    assert save_screenshot(driver, "task-monitoring-summary").is_file()

    driver.get(live_server.url + reverse("task_list"))
    assert "Forbidden" in driver.title


def test_admin_pages_through_filtered_tasks(
    live_server,
    driver,
    admin_user,
    force_login,
    save_screenshot,
    task_rows,
    monkeypatch,
):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait

    monkeypatch.setattr(TaskListView, "paginate_by", 1)
    wait = WebDriverWait(driver, 10)
    force_login(admin_user)
    yesterday = timezone.localdate() - timedelta(days=1)
    queued_after = f"{yesterday.isoformat()}T00:00:01"
    url = reverse(
        "task_list",
        query={"sort": "task_path", "queued_after": queued_after},
    )
    row = (By.CSS_SELECTOR, "#content tbody tr")
    pagination = (By.CSS_SELECTOR, "nav[aria-label='Task pages']")

    driver.execute_cdp_cmd(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": 1280,
            "height": 1000,
            "deviceScaleFactor": 1,
            "mobile": False,
        },
    )
    try:
        driver.get(live_server.url + url)
        assert (
            wait.until(ec.visibility_of_element_located(row))
            .find_element(By.TAG_NAME, "th")
            .text
            == SHORT_SCREENING
        )
        controls = driver.find_element(*pagination)
        assert "Page 1 of 3" in controls.text
        assert save_screenshot(driver, "task-monitoring-page-1").is_file()

        controls.find_element(By.LINK_TEXT, "Next").click()
        assert (
            wait.until(ec.visibility_of_element_located(row))
            .find_element(By.TAG_NAME, "th")
            .text
            == "parameter_extraction.process_parameter_extraction_task"
        )
        controls = driver.find_element(*pagination)
        assert "Page 2 of 3" in controls.text
        assert (
            driver.find_element(By.NAME, "queued_after").get_property("value")
            == queued_after
        )
        assert save_screenshot(driver, "task-monitoring-page-2").is_file()

        controls.find_element(By.LINK_TEXT, "Previous").click()
        assert (
            wait.until(ec.visibility_of_element_located(row))
            .find_element(By.TAG_NAME, "th")
            .text
            == SHORT_SCREENING
        )
    finally:
        set_viewport(driver)
