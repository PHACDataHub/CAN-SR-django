from django.contrib.auth.models import Group
from django.db import transaction

from proj.models import User

from my_app.constants import ADMIN_USER_GROUP
from my_app.models import LanguageModel, Review

DEMO_REVIEW_COUNT = 10


@transaction.atomic
def run():
    admin_group = Group.objects.get_or_create(name=ADMIN_USER_GROUP)[0]

    admin, created = User.objects.get_or_create(
        username="admin",
        defaults={"is_staff": True, "is_superuser": True},
    )
    if created:
        admin.set_password("admin")
        admin.save()
    admin.groups.add(admin_group)

    if Review.objects.exists():
        print("Demo reviews already exist; skipping review seed.")
        return

    model = LanguageModel.get_default_model()
    for number in range(1, DEMO_REVIEW_COUNT + 1):
        review = Review.objects.create(
            title=f"Demo systematic review {number}",
            description="Example review created by the local Docker demo.",
            language_model=model,
        )
        review.user_links.create(user=admin)
