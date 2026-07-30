from django.contrib.auth.models import Group

import pytest

from proj.models import User

from my_app.constants import ADMIN_USER_GROUP
from my_app.models import Review
from my_app.scripts.dev import DEMO_REVIEW_COUNT, run

pytestmark = pytest.mark.django_db


def test_run_creates_demo_admin_and_reviews():
    run()

    admin = User.objects.get(username="admin")
    assert admin.is_staff
    assert admin.is_superuser
    assert admin.check_password("admin")
    assert admin.groups.get().name == ADMIN_USER_GROUP

    reviews = Review.objects.order_by("id")
    assert reviews.count() == DEMO_REVIEW_COUNT
    assert reviews.first().title == "Demo systematic review 1"
    assert reviews.last().title == "Demo systematic review 10"
    assert all(review.user_links.get().user == admin for review in reviews)


def test_run_is_idempotent(capsys):
    run()
    run()

    assert User.objects.filter(username="admin").count() == 1
    assert Group.objects.filter(name=ADMIN_USER_GROUP).count() == 1
    assert Review.objects.count() == DEMO_REVIEW_COUNT
    assert (
        "Demo reviews already exist; skipping review seed."
        in capsys.readouterr().out
    )


def test_run_does_not_reset_existing_admin_password():
    admin = User.objects.create_superuser(username="admin", password="secret")

    run()

    admin.refresh_from_db()
    assert admin.check_password("secret")
