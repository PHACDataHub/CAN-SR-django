from datetime import timedelta

from django.conf import settings

DEPENDENT_TASK_PRIORITY = 20
CITATION_CHECK_PRIORITY = 10
BULK_CHECK_PRIORITY = -10


def initial_check_delay(question_count=None):
    seconds = settings.WORKFLOW_CHECK_INITIAL_SECONDS
    if question_count is not None:
        workers = max(1, settings.WORKFLOW_EFFECTIVE_SCREENING_WORKERS)
        # Each question has a serial initial/critical chain.
        seconds *= max(2, 2 * question_count / workers)
    return timedelta(seconds=seconds)


def followup_check_delay():
    return timedelta(seconds=settings.WORKFLOW_CHECK_FOLLOWUP_SECONDS)
