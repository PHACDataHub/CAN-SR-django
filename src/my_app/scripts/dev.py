import random

from django.contrib.auth.models import Group
from django.db import transaction

from proj.models import User

from my_app.constants import ADMIN_USER_GROUP
from my_app.model_factories import ReviewFactory, UserFactory


@transaction.atomic
def run():
    admin_group = Group.objects.get_or_create(name=ADMIN_USER_GROUP)[0]

    admin = User.objects.create_superuser(
        username="admin",
        password="admin",
    )
    admin.groups.add(admin_group)

    reviews = ReviewFactory.create_batch(10)
    for review in reviews:
        for x in range(random.randint(1, 3)):
            user = UserFactory()
            review.user_links.create(user=user)
