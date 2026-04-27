from django.core.management import call_command
from django.db import transaction

import pytest


@pytest.fixture(scope="package")
def my_app_scoped_autofixture(django_db_setup, django_db_blocker):
    """
    We could have put this in the root conftest (tests/conftest) but expect people to clone the project so put it here instead
    """

    with django_db_blocker.unblock():
        # Wrap in try + atomic block to do non crashing rollback
        try:
            with transaction.atomic():
                yield
                raise Exception
        except Exception:
            pass


@pytest.fixture(scope="package", autouse=True)
def create_seed_data(my_app_scoped_autofixture):
    call_command("loaddata", "lookups", verbosity=0)
