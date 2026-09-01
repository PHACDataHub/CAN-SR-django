from unittest.mock import patch

from django.core.management import call_command
from django.tasks import task
from django.test import override_settings

import pytest
from data_fetcher.util import get_request

from proj.models import TaskGroup
from proj.task_groups import gather_tasks, task_call


def task_group_callback_spy(task_group_id, label):
    pass


@task
def task_group_value_for_testing(value):
    return value


@task
def task_group_failure_for_testing(message):
    raise RuntimeError(message)


@task
def task_group_callback_for_testing(task_group_id, label):
    # patch works easier if we re-import
    from tests.proj.test_task_groups import task_group_callback_spy

    task_group_callback_spy(task_group_id, label)


def task_backend(backend):
    return {
        "default": {
            "BACKEND": backend,
            "QUEUES": [],
        }
    }


IMMEDIATE_TASKS = task_backend(
    "django.tasks.backends.immediate.ImmediateBackend"
)
DATABASE_TASKS = task_backend(
    "django_database_task.backends.DatabaseTaskBackend"
)


@override_settings(TASKS=IMMEDIATE_TASKS)
def test_gather_tasks_completes_and_calls_back_with_immediate_backend():
    with patch(
        "tests.proj.test_task_groups.task_group_callback_spy"
    ) as callback_spy:
        group = gather_tasks(
            {
                "first": task_call(task_group_value_for_testing, "one"),
                "second": task_call(task_group_value_for_testing, "two"),
            },
            then=task_group_callback_for_testing,
            then_kwargs={"label": "finished"},
        )

    group.refresh_from_db()
    assert group.status == TaskGroup.Status.SUCCESSFUL
    assert group.results == {"first": "one", "second": "two"}
    assert group.errors == {}
    assert group.callback_task_result_id
    callback_spy.assert_called_once_with(str(group.id), "finished")


@override_settings(TASKS=DATABASE_TASKS)
def test_gather_tasks_waits_and_calls_back_with_database_backend():
    with patch(
        "tests.proj.test_task_groups.task_group_callback_spy"
    ) as callback_spy:
        group = gather_tasks(
            {
                "first": task_call(task_group_value_for_testing, "one"),
                "second": task_call(task_group_value_for_testing, "two"),
            },
            then=task_group_callback_for_testing,
            then_kwargs={"label": "finished"},
        )

        group.refresh_from_db()
        assert group.status == TaskGroup.Status.WAITING
        callback_spy.assert_not_called()

        call_command("run_database_tasks", verbosity=0)

    group.refresh_from_db()
    assert group.status == TaskGroup.Status.SUCCESSFUL
    assert group.results == {"first": "one", "second": "two"}
    assert group.errors == {}
    assert group.callback_task_result_id
    callback_spy.assert_called_once_with(str(group.id), "finished")


@pytest.mark.parametrize(
    "backend",
    [IMMEDIATE_TASKS, DATABASE_TASKS],
)
def test_gather_tasks_records_failure_and_calls_error_callback(backend):
    with override_settings(TASKS=backend):
        with patch(
            "tests.proj.test_task_groups.task_group_callback_spy"
        ) as callback_spy:
            group = gather_tasks(
                {
                    "success": task_call(
                        task_group_value_for_testing,
                        "value",
                    ),
                    "failure": task_call(
                        task_group_failure_for_testing,
                        "broken",
                    ),
                },
                on_error=task_group_callback_for_testing,
                on_error_kwargs={"label": "failed"},
            )

            if group.status == TaskGroup.Status.WAITING:
                call_command("run_database_tasks", verbosity=0)

    group.refresh_from_db()
    assert group.status == TaskGroup.Status.FAILED
    assert group.results == {"success": "value"}
    assert group.errors["failure"][0]["exception_class_path"] == (
        "builtins.RuntimeError"
    )
    assert "broken" in group.errors["failure"][0]["traceback"]
    callback_spy.assert_called_once_with(str(group.id), "failed")


def test_task_group_can_identify_the_latest_group_with_a_key():
    older = TaskGroup.objects.create(key="document:1")
    newer = TaskGroup.objects.create(key="document:1")
    unrelated = TaskGroup.objects.create(key="document:2")

    assert older.is_latest_with_key() is False
    assert newer.is_latest_with_key() is True
    assert unrelated.is_latest_with_key() is True
