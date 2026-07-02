import contextvars
from types import SimpleNamespace

from django.dispatch import receiver
from django.tasks import task
from django.tasks.signals import task_finished, task_started

from data_fetcher.global_request_context import storage as request_storage
from data_fetcher.util import GlobalRequest, clear_request_caches, get_request

from proj.logging import generate_context_id, logger

# TASK related signals
# tasks get their own request context, for caching and for logging
# a context ID is logged on each log message, so we can trace logs by task


stack_storage = contextvars.ContextVar("request", default=None)
# Why a new stack-based contextvar?
# when we use the immediate task backend,
# tasks are called during (not after) a request, in the same thread
# so they override the request's context
# if the request then uses get_request() (like via caches), it warns or raises
# So we swap out the context using stacks, then restore the previous ctx
# This also allows tasks to queue other tasks
# we need to restore the previous task's context when the inner task is finished
# we may want to consider promoting this stack approach to the data_fetcher package
# generally, we should probably not use immediate backend much,


@receiver(task_started)
def on_task_started(sender, task_result, **kwargs):

    old_context = request_storage.get()
    current_stack = stack_storage.get() or []
    current_stack.append(old_context)
    stack_storage.set(current_stack)

    task_name = task_result.task.func.__name__
    context_id = generate_context_id()
    new_request = SimpleNamespace(
        context_id=context_id, task_id=task_result.id
    )
    clear_request_caches()

    logger.info("Starting task %s with context_id %s", task_name, context_id)

    request_storage.set(new_request)


@receiver(task_finished)
def on_task_finished(sender, task_result, **kwargs):
    logger.info("Finished task")
    clear_request_caches()

    current_stack = stack_storage.get() or []
    if current_stack:
        old_context = current_stack.pop()
        stack_storage.set(current_stack)
        request_storage.set(old_context)
    else:
        request_storage.set(None)
