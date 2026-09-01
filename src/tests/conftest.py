from django.db import transaction
from django.test.client import Client

import pytest
from phac_aspc.django.settings.utils import configure_settings_for_tests

from proj.models import User

# Modify django settings to skip axes authentication backend
configure_settings_for_tests()


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    """
    without this, tests (including old-style) have to explicitly declare db as a dependency
    https://pytest-django.readthedocs.io/en/latest/faq.html#how-can-i-give-database-access-to-all-my-tests-without-the-django-db-marker
    """
    pass


@pytest.fixture
def run_database_tasks():
    """Drain database tasks without closing pytest's managed connection."""
    from django_tasks_db.management.commands.db_worker import Worker
    from django_tasks_db.models import DBTaskResult

    def run():
        worker = Worker(
            queue_names=["default"],
            excluded_queue_names=[],
            interval=0,
            batch=True,
            backend_name="default",
            startup_delay=False,
            max_tasks=None,
            worker_id="pytest-worker",
        )

        while task_result := (
            DBTaskResult.objects.ready()
            .filter(backend_name="default", queue_name="default")
            .first()
        ):
            task_result.claim(worker.worker_id)
            worker.run_task(task_result)

    return run


@pytest.fixture(scope="session")
def globally_scoped_fixture_helper(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        # Wrap in try + atomic block to do non crashing rollback
        # This means we don't have to re-create a test DB each time
        try:
            with transaction.atomic():
                yield
                raise Exception
        except Exception:
            pass


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(username="admin")


@pytest.fixture
def admin_client(admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def vanilla_user():
    return User.objects.create_user(username="vanilla", password="password")


@pytest.fixture
def vanilla_client(vanilla_user):
    client = Client()
    client.force_login(vanilla_user)
    return client


@pytest.fixture
def vanilla_user_client(vanilla_client):
    return vanilla_client
