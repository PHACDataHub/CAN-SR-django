from types import SimpleNamespace
from uuid import uuid4

from django.dispatch import receiver
from django.tasks import task
from django.tasks.signals import task_finished, task_started

from data_fetcher.global_request_context import storage
from data_fetcher.util import GlobalRequest, clear_request_caches, get_request

from proj.logging import logger

# TASK related signals
# tasks get their own request context, for caching and for logging
# a context ID is logged on each log message, so we can trace logs by task


@receiver(task_started)
def on_task_started(sender, task_result, **kwargs):
    task_name = task_result.task.func.__name__
    context_id = str(uuid4())
    new_request = SimpleNamespace(
        context_id=context_id, task_id=task_result.id
    )
    clear_request_caches()

    logger.info("Starting task %s with context_id %s", task_name, context_id)

    storage.set(new_request)


@receiver(task_finished)
def on_task_finished(sender, task_result, **kwargs):
    logger.info("Finished task")
    clear_request_caches()
    storage.set(None)
