from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from bs4 import BeautifulSoup
from django_tasks_db.compat import TaskResultStatus
from django_tasks_db.models import DBTaskResult, get_date_max
from freezegun import freeze_time


def create_task(
    name, status=TaskResultStatus.READY, finished_minutes_ago=None
):
    started = None
    finished = None
    if finished_minutes_ago is not None:
        finished = timezone.now() - timedelta(minutes=finished_minutes_ago)
        started = finished - timedelta(seconds=12)
    task = DBTaskResult.objects.create(
        task_path=name,
        status=status,
        backend_name="default",
        args_kwargs={"args": ["private argument"], "kwargs": {}},
        run_after=get_date_max(),
        started_at=started,
        finished_at=finished,
    )
    if started:
        DBTaskResult.objects.filter(pk=task.pk).update(
            enqueued_at=started - timedelta(seconds=30)
        )
    return task


@freeze_time("2026-11-26 12:00:00")
def test_task_monitoring_access_and_recent_window(
    admin_client, vanilla_client
):
    create_task("tasks.queued")
    recent = create_task("tasks.recent", TaskResultStatus.FAILED, 5)
    create_task("tasks.older", TaskResultStatus.SUCCESSFUL, 6)
    task_list = reverse("task_list")
    summary = reverse("task_summary")
    autocomplete = reverse("autocomplete:items", args=["TaskNameAutocomplete"])

    assert vanilla_client.get(task_list).status_code == 403
    assert vanilla_client.get(autocomplete).status_code == 403
    assert (
        b"tasks.older"
        in admin_client.get(
            autocomplete, {"field_name": "task_name", "search": "older"}
        ).content
    )
    summary_response = vanilla_client.get(summary)
    assert summary_response.status_code == 200
    assert b"private argument" not in summary_response.content
    assert b"tasks.older" not in summary_response.content
    soup = BeautifulSoup(summary_response.content, "html.parser")
    assert soup.find("a", href=task_list) is None
    assert [cell.get_text() for cell in soup.select("tfoot td")] == [
        "1",
        "0",
        "0",
        "1",
    ]

    response = admin_client.get(task_list)
    assert response.status_code == 200
    assert b"tasks.queued" in response.content
    assert b"tasks.older" not in response.content
    assert b"private argument" in response.content
    admin_url = reverse(
        "admin:django_tasks_database_dbtaskresult_change", args=[recent.pk]
    )
    assert admin_url.encode() in response.content
    assert b"0:00:12" in response.content
    assert b"0:00:30" in response.content

    filtered = admin_client.get(
        task_list,
        {
            "include_history": "on",
            "status": TaskResultStatus.SUCCESSFUL,
            "task_name": ["tasks.older", "tasks.queued"],
        },
    )
    assert b"tasks.older" in filtered.content
    assert (
        BeautifulSoup(filtered.content, "html.parser")
        .select_one("tbody th")
        .get_text()
        == "tasks.older"
    )


def test_task_list_sorts_and_preserves_filters_across_pages(
    admin_client, monkeypatch
):
    from my_app.views.task_monitoring import TaskListView

    monkeypatch.setattr(TaskListView, "paginate_by", 1)
    create_task("tasks.first")
    create_task("tasks.last")
    create_task("tasks.middle")
    response = admin_client.get(
        reverse("task_list"),
        {"sort": "-task_path", "task_name": ["tasks.first", "tasks.last"]},
    )
    soup = BeautifulSoup(response.content, "html.parser")
    assert soup.select_one("tbody th").get_text() == "tasks.last"

    next_url = soup.find("a", string="Next")["href"]
    next_response = admin_client.get(next_url)
    assert (
        BeautifulSoup(next_response.content, "html.parser")
        .select_one("tbody th")
        .get_text()
        == "tasks.first"
    )


@freeze_time("2026-11-26 12:00:00")
def test_task_list_filters_by_queued_datetime_and_queue_to_completion(
    admin_client,
):
    queued_target = timezone.now() - timedelta(days=1)
    for name, offset_seconds, elapsed in [
        ("tasks.before", -2, timedelta(seconds=6)),
        ("tasks.match", 0, timedelta(seconds=5, microseconds=1)),
        ("tasks.exactly_five", 0, timedelta(seconds=5)),
        ("tasks.after", 2, timedelta(seconds=6)),
    ]:
        task = create_task(name, TaskResultStatus.SUCCESSFUL)
        queued = queued_target + timedelta(seconds=offset_seconds)
        DBTaskResult.objects.filter(pk=task.pk).update(
            enqueued_at=queued, finished_at=queued + elapsed
        )
    unfinished = create_task("tasks.unfinished")
    DBTaskResult.objects.filter(pk=unfinished.pk).update(
        enqueued_at=queued_target
    )

    response = admin_client.get(
        reverse("task_list"),
        {
            "include_history": "on",
            "queued_after": timezone.localtime(
                queued_target - timedelta(seconds=1)
            ).isoformat(timespec="seconds")[:19],
            "queued_before": timezone.localtime(
                queued_target + timedelta(seconds=1)
            ).isoformat(timespec="seconds")[:19],
            "min_queue_to_completion": "5",
        },
    )
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert [row.get_text() for row in soup.select("tbody th")] == [
        "tasks.match"
    ]
