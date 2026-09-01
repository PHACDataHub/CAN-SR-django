from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping

from django.db import transaction
from django.tasks.base import Task, TaskResultStatus
from django.utils import timezone
from django.utils.json import normalize_json
from django.utils.module_loading import import_string

from proj.models import TaskGroup


class InvalidTaskGroup(ValueError):
    pass


@dataclass(frozen=True)
class TaskCall:
    task: Task
    args: tuple
    kwargs: dict


def task_call(task, *args, **kwargs):
    """Describe a Django Task invocation without enqueueing it."""
    if not isinstance(task, Task):
        raise InvalidTaskGroup("task_call() requires a decorated Django Task")

    return TaskCall(task=task, args=args, kwargs=kwargs)


def _task_reference(task):
    return {
        "task_path": task.module_path,
        "backend": task.backend,
    }


def _callback_fields(task, kwargs):
    if task is None:
        return "", "", {}
    if not isinstance(task, Task):
        raise InvalidTaskGroup("Task group callbacks must be Django Tasks")
    if kwargs and "task_group_id" in kwargs:
        raise InvalidTaskGroup(
            '"task_group_id" is reserved for the task group callback'
        )
    return task.module_path, task.backend, normalize_json(kwargs or {})


def _serialize_errors(task_result):
    return [
        {
            "exception_class_path": error.exception_class_path,
            "traceback": error.traceback,
        }
        for error in task_result.errors
    ]


def _snapshot_results(task_results):
    results = {}
    errors = {}

    for key, task_result in task_results.items():
        if task_result.status == TaskResultStatus.SUCCESSFUL:
            results[key] = task_result.return_value
        elif task_result.status == TaskResultStatus.FAILED:
            errors[key] = _serialize_errors(task_result)
        else:
            raise InvalidTaskGroup(
                f'Task group member "{key}" has not finished'
            )

    return results, errors


def _resolve_task(task_path, backend):
    task = import_string(task_path)
    if not isinstance(task, Task):
        raise InvalidTaskGroup(
            f'"{task_path}" does not resolve to a Django Task'
        )
    if task.backend != backend:
        task = task.using(backend=backend)
    return task


def _callback_for_group(group):
    if group.status == TaskGroup.Status.SUCCESSFUL:
        task_path = group.callback_task_path
        backend = group.callback_task_backend
        kwargs = group.callback_kwargs
    elif group.completion_policy == TaskGroup.CompletionPolicy.ALL_SETTLED:
        task_path = group.callback_task_path
        backend = group.callback_task_backend
        kwargs = group.callback_kwargs
    else:
        task_path = group.error_callback_task_path
        backend = group.error_callback_task_backend
        kwargs = group.error_callback_kwargs

    if not task_path:
        return None, None
    return _resolve_task(task_path, backend), kwargs


def _complete_group(group, task_results):
    results, errors = _snapshot_results(task_results)
    group.results = results
    group.errors = errors
    group.status = (
        TaskGroup.Status.FAILED if errors else TaskGroup.Status.SUCCESSFUL
    )
    group.finished_at = timezone.now()
    group.save(
        update_fields=[
            "results",
            "errors",
            "status",
            "finished_at",
            "updated_at",
        ]
    )

    callback, callback_kwargs = _callback_for_group(group)
    if callback is None:
        return

    callback_result = callback.enqueue(
        task_group_id=str(group.id),
        **callback_kwargs,
    )
    group.callback_task_result_id = callback_result.id
    group.save(update_fields=["callback_task_result_id", "updated_at"])


def _member_task_result(member):
    task = _resolve_task(member["task_path"], member["backend"])
    return task.get_result(member["task_result_id"])


def check_task_group_result(task_group_id):
    from proj.tasks import check_task_group

    with transaction.atomic():
        group = TaskGroup.objects.select_for_update().get(id=task_group_id)
        if group.status != TaskGroup.Status.WAITING:
            return

        task_results = {
            key: _member_task_result(member)
            for key, member in group.members.items()
        }
        if all(result.is_finished for result in task_results.values()):
            _complete_group(group, task_results)
            return

        check_task_group.using(
            run_after=timezone.now() + timedelta(seconds=1)
        ).enqueue(task_group_id=str(group.id))


def gather_tasks(
    calls: Mapping[str, TaskCall],
    *,
    then=None,
    then_kwargs=None,
    on_error=None,
    on_error_kwargs=None,
    completion_policy=TaskGroup.CompletionPolicy.ALL_SUCCESS,
    key="",
):
    """Enqueue named tasks and run a callback after they have all finished."""
    from proj.tasks import check_task_group

    if not calls:
        raise InvalidTaskGroup("A task group must contain at least one task")
    if any(
        not isinstance(member_key, str) or not member_key
        for member_key in calls
    ):
        raise InvalidTaskGroup(
            "Task group member keys must be non-empty strings"
        )
    if any(not isinstance(call, TaskCall) for call in calls.values()):
        raise InvalidTaskGroup("Every task group member must be a TaskCall")
    if completion_policy not in TaskGroup.CompletionPolicy.values:
        raise InvalidTaskGroup(
            f'Unknown task group completion policy: "{completion_policy}"'
        )

    callback_path, callback_backend, callback_kwargs = _callback_fields(
        then, then_kwargs
    )
    error_path, error_backend, error_kwargs = _callback_fields(
        on_error, on_error_kwargs
    )

    with transaction.atomic():
        group = TaskGroup.objects.create(
            key=key,
            completion_policy=completion_policy,
            callback_task_path=callback_path,
            callback_task_backend=callback_backend,
            callback_kwargs=callback_kwargs,
            error_callback_task_path=error_path,
            error_callback_task_backend=error_backend,
            error_callback_kwargs=error_kwargs,
        )

        task_results = {
            member_key: call.task.enqueue(*call.args, **call.kwargs)
            for member_key, call in calls.items()
        }
        group.members = {
            member_key: {
                **_task_reference(calls[member_key].task),
                "task_result_id": task_result.id,
                "args": normalize_json(calls[member_key].args),
                "kwargs": normalize_json(calls[member_key].kwargs),
            }
            for member_key, task_result in task_results.items()
        }
        group.save(update_fields=["members", "updated_at"])

        if all(result.is_finished for result in task_results.values()):
            _complete_group(group, task_results)
            return group

        unsupported_backends = {
            result.backend
            for result in task_results.values()
            if not result.is_finished
            and not result.task.get_backend().supports_get_result
        }
        if unsupported_backends:
            aliases = ", ".join(sorted(unsupported_backends))
            raise InvalidTaskGroup(
                "Unfinished task results must be queryable; unsupported "
                f"backends: {aliases}"
            )
        if not check_task_group.get_backend().supports_defer:
            raise InvalidTaskGroup(
                "The task-group coordinator backend must support deferred tasks"
            )

        check_task_group.enqueue(task_group_id=str(group.id))
        return group
