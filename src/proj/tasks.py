# this is a fake/testing-only task file
from django.tasks import task

from data_fetcher.util import get_request


def func_to_spy(args):
    pass


def inner_func():
    # just checking context propagation
    request = get_request()
    func_to_spy(request)
    func_to_spy(request.context_id)


@task
def example_task_for_testing(arg: int):
    """
    This is an example task we can test using
    both immediate and DB backends
    """
    request = get_request()
    func_to_spy(request)
    func_to_spy(request.context_id)
    func_to_spy(arg)
    inner_func()
