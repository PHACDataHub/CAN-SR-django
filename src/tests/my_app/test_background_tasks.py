from django.core.management import call_command
from django.db import connection
from django.tasks.base import TaskResultStatus
from django.urls import reverse

import pytest
from django_database_task.models import DatabaseTask

from my_app.model_factories import SystematicReviewFactory
from my_app.models import DemoTaskRun
from my_app.tasks.example_tasks import (
    record_sr_snapshot,
    record_sr_snapshot_async,
)


def test_background_tasks_demo_page_renders(admin_client):
    response = admin_client.get(reverse("background_tasks_demo"))

    assert response.status_code == 200

    content = response.content.decode()

    assert "Background tasks" in content
    assert "Enqueue sync demo task" in content
    assert "Enqueue async demo task" in content
    assert "run_database_tasks" in content


def test_background_tasks_demo_sync_enqueue_and_worker_process(admin_client):
    SystematicReviewFactory()

    response = admin_client.post(
        reverse("background_tasks_demo"),
        {"task_kind": "enqueue_sync_demo_task"},
    )

    assert response.status_code == 302
    assert DatabaseTask.objects.count() == 1

    queued_task = DatabaseTask.objects.get()
    assert queued_task.status == TaskResultStatus.READY

    call_command("run_database_tasks", verbosity=0)

    queued_task.refresh_from_db()
    assert queued_task.status == TaskResultStatus.SUCCESSFUL
    assert queued_task.return_value_json["record_count"] == 1

    task_run = DemoTaskRun.objects.get(task_result_id=str(queued_task.id))
    assert task_run.kind == "sync"
    assert task_run.record_count == 1
    assert task_run.label == queued_task.kwargs_json["label"]
    assert task_run.attempt == 1


@pytest.mark.skipif(
    connection.vendor == "sqlite",
    reason="SQLite locks async ORM writes in the worker test harness.",
)
def test_background_tasks_demo_async_enqueue_and_worker_process(admin_client):
    SystematicReviewFactory()

    response = admin_client.post(
        reverse("background_tasks_demo"),
        {"task_kind": "enqueue_async_demo_task"},
    )

    assert response.status_code == 302
    assert DatabaseTask.objects.count() == 1

    queued_task = DatabaseTask.objects.get()
    assert queued_task.status == TaskResultStatus.READY
    assert queued_task.kwargs_json["record_count"] == 1

    call_command("run_database_tasks", verbosity=0)

    queued_task.refresh_from_db()
    assert queued_task.status == TaskResultStatus.SUCCESSFUL
    assert queued_task.return_value_json["record_count"] == 1

    task_run = DemoTaskRun.objects.get(task_result_id=str(queued_task.id))
    assert task_run.kind == "async"
    assert task_run.record_count == 1
    assert task_run.label == queued_task.kwargs_json["label"]
    assert task_run.attempt == 1


def test_record_record_snapshot_enqueue_uses_database_backend():
    SystematicReviewFactory()

    task_result = record_sr_snapshot.enqueue(label="manual-run")

    assert task_result.status == TaskResultStatus.READY
    assert task_result.id

    queued_task = DatabaseTask.objects.get(pk=task_result.id)
    assert queued_task.kwargs_json["label"] == "manual-run"


def test_record_record_snapshot_async_enqueue_uses_database_backend():
    SystematicReviewFactory()

    task_result = record_sr_snapshot_async.enqueue(
        label="manual-run", record_count=1
    )

    assert task_result.status == TaskResultStatus.READY
    assert task_result.id

    queued_task = DatabaseTask.objects.get(pk=task_result.id)
    assert queued_task.kwargs_json["label"] == "manual-run"
    assert queued_task.kwargs_json["record_count"] == 1
