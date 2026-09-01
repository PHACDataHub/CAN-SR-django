from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.db import connection
from django.tasks.base import TaskResultStatus
from django.test import override_settings
from django.urls import reverse

import pytest
from data_fetcher.global_request_context import storage
from django_database_task.models import DatabaseTask

from my_app.model_factories import ReviewFactory
from my_app.models import DemoTaskRun
from my_app.tasks.example_tasks import (
    record_sr_snapshot,
    record_sr_snapshot_async,
)

pytestmark = pytest.mark.view


from django.tasks import task

from data_fetcher.util import get_request


def func_to_spy(args):
    pass


def inner_func():
    # just checking context propagation
    request = get_request()
    from tests.my_app.test_background_tasks import func_to_spy

    func_to_spy(request)
    func_to_spy(request.context_id)


@task
def example_task_for_testing(arg: int):
    """
    This is an example task we can test using
    both immediate and DB backends
    """
    request = get_request()
    from tests.my_app.test_background_tasks import func_to_spy

    func_to_spy(request)
    func_to_spy(request.context_id)
    func_to_spy(arg)
    inner_func()


def test_background_tasks_demo_page_renders(admin_client):
    response = admin_client.get(reverse("background_tasks_demo"))

    assert response.status_code == 200

    content = response.content.decode()

    assert "Background tasks" in content
    assert "Enqueue sync demo task" in content
    assert "Enqueue async demo task" in content
    assert "run_database_tasks" in content


def test_background_tasks_demo_sync_enqueue_and_worker_process(admin_client):
    ReviewFactory()

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
    ReviewFactory()

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
    ReviewFactory()

    task_result = record_sr_snapshot.enqueue(label="manual-run")

    assert task_result.status == TaskResultStatus.READY
    assert task_result.id

    queued_task = DatabaseTask.objects.get(pk=task_result.id)
    assert queued_task.kwargs_json["label"] == "manual-run"


def test_record_record_snapshot_async_enqueue_uses_database_backend():
    ReviewFactory()

    task_result = record_sr_snapshot_async.enqueue(
        label="manual-run", record_count=1
    )

    assert task_result.status == TaskResultStatus.READY
    assert task_result.id

    queued_task = DatabaseTask.objects.get(pk=task_result.id)
    assert queued_task.kwargs_json["label"] == "manual-run"
    assert queued_task.kwargs_json["record_count"] == 1


def get_task_backend(code):
    if code == "immediate":
        backend = "django.tasks.backends.immediate.ImmediateBackend"
    elif code == "database":
        backend = "django_database_task.backends.DatabaseTaskBackend"

    return {
        "default": {
            "BACKEND": backend,
            "QUEUES": [],
        }
    }


@pytest.mark.parametrize("backend", ["immediate", "database"])
def test_signals_and_contextvars_are_set_in_task_execution(backend):
    """
    This test ensures that the signals and contextvars are set correctly
    when a task is executed, both for immediate and database backend tasks.
    """

    fake_id1 = "123456"
    fake_id2 = "abcdef"

    def make_fake_id_generator():
        yield fake_id1
        yield fake_id2

    fake_id_gen = make_fake_id_generator()

    def fake_generate_context_id():
        return next(fake_id_gen)

    spy = MagicMock()

    assert storage.get() is None

    with (
        override_settings(TASKS=get_task_backend(backend)),
        patch("proj.signals.generate_context_id", fake_generate_context_id),
        patch("tests.my_app.test_background_tasks.func_to_spy", spy),
    ):
        task_result = example_task_for_testing.enqueue(42)
        assert storage.get() is None
        task_result2 = example_task_for_testing.enqueue(43)

        assert storage.get() is None

        if backend == "immediate":
            assert task_result.status == TaskResultStatus.SUCCESSFUL
            assert task_result2.status == TaskResultStatus.SUCCESSFUL
        else:
            assert task_result.status == TaskResultStatus.READY
            assert task_result2.status == TaskResultStatus.READY

        if backend == "database":
            call_command("run_database_tasks", verbosity=0)
            assert storage.get() is None

        assert spy.call_count == 10

        request_ctx1 = spy.call_args_list[0][0][0]
        context_id1 = spy.call_args_list[1][0][0]
        task_arg1 = spy.call_args_list[2][0][0]
        inner_request_ctx1 = spy.call_args_list[3][0][0]
        inner_request_ctx_id = spy.call_args_list[4][0][0]
        assert task_arg1 == 42
        assert context_id1 == "t-" + fake_id1
        assert request_ctx1.context_id == "t-" + fake_id1
        assert inner_request_ctx_id == "t-" + fake_id1
        assert inner_request_ctx1 is request_ctx1

        request_ctx2 = spy.call_args_list[5][0][0]
        context_id2 = spy.call_args_list[6][0][0]
        task_arg2 = spy.call_args_list[7][0][0]
        inner_request_ctx2 = spy.call_args_list[8][0][0]
        inner_request_ctx_id2 = spy.call_args_list[9][0][0]
        assert task_arg2 == 43
        assert context_id2 == "t-" + fake_id2
        assert request_ctx2.context_id == "t-" + fake_id2
        assert inner_request_ctx_id2 == "t-" + fake_id2
        assert inner_request_ctx2 is request_ctx2

    if backend == "database":
        task_result.refresh()
        task_result2.refresh()
        assert task_result.status == TaskResultStatus.SUCCESSFUL
        assert task_result2.status == TaskResultStatus.SUCCESSFUL
