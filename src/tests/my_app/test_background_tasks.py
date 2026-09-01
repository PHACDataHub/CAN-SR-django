from unittest.mock import MagicMock, patch

from django.tasks import task
from django.tasks.base import TaskResultStatus
from django.test import override_settings

import pytest
from data_fetcher.global_request_context import storage
from data_fetcher.util import get_request


def func_to_spy(args):
    pass


def inner_func():
    request = get_request()
    from tests.my_app.test_background_tasks import func_to_spy

    func_to_spy(request)
    func_to_spy(request.context_id)


@task
def example_task_for_testing(arg: int):
    request = get_request()
    from tests.my_app.test_background_tasks import func_to_spy

    func_to_spy(request)
    func_to_spy(request.context_id)
    func_to_spy(arg)
    inner_func()


def get_task_backend(code):
    if code == "immediate":
        backend = "django.tasks.backends.immediate.ImmediateBackend"
    elif code == "database":
        backend = "django_tasks_db.DatabaseBackend"

    return {
        "default": {
            "BACKEND": backend,
            "QUEUES": ["default"],
        }
    }


@pytest.mark.parametrize("backend", ["immediate", "database"])
def test_signals_and_contextvars_are_set_in_task_execution(
    backend, run_database_tasks
):
    fake_ids = iter(["123456", "abcdef"])
    spy = MagicMock()

    assert storage.get() is None

    with (
        override_settings(TASKS=get_task_backend(backend)),
        patch("proj.signals.generate_context_id", side_effect=fake_ids),
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
            run_database_tasks()
            assert storage.get() is None

        assert spy.call_count == 10

        request_ctx1 = spy.call_args_list[0][0][0]
        context_id1 = spy.call_args_list[1][0][0]
        task_arg1 = spy.call_args_list[2][0][0]
        inner_request_ctx1 = spy.call_args_list[3][0][0]
        inner_request_ctx_id = spy.call_args_list[4][0][0]
        assert task_arg1 == 42
        assert context_id1 == "t-123456"
        assert request_ctx1.context_id == "t-123456"
        assert inner_request_ctx_id == "t-123456"
        assert inner_request_ctx1 is request_ctx1

        request_ctx2 = spy.call_args_list[5][0][0]
        context_id2 = spy.call_args_list[6][0][0]
        task_arg2 = spy.call_args_list[7][0][0]
        inner_request_ctx2 = spy.call_args_list[8][0][0]
        inner_request_ctx_id2 = spy.call_args_list[9][0][0]
        assert task_arg2 == 43
        assert context_id2 == "t-abcdef"
        assert request_ctx2.context_id == "t-abcdef"
        assert inner_request_ctx_id2 == "t-abcdef"
        assert inner_request_ctx2 is request_ctx2

    if backend == "database":
        task_result.refresh()
        task_result2.refresh()
        assert task_result.status == TaskResultStatus.SUCCESSFUL
        assert task_result2.status == TaskResultStatus.SUCCESSFUL
