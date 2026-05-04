from data_fetcher.middleware import GlobalRequest

# creating a variable called test_rules triggers pytest to run it as a test!
from phac_aspc.rules import test_rule as my_test_rule

from proj.models import User

from my_app.model_factories import (
    SystematicReviewFactory,
    SystematicReviewUserLinkFactory,
)


def test_systematic_review_access_rule(admin_user):
    linked_user = User.objects.create(username="linked-user")
    other_user = User.objects.create(username="other-user")
    linked_review = SystematicReviewFactory()
    other_review = SystematicReviewFactory()
    SystematicReviewUserLinkFactory(
        user=linked_user, systematic_review=linked_review
    )

    with GlobalRequest():
        assert my_test_rule(
            "can_access_systematic_review", admin_user, linked_review.id
        )
        assert my_test_rule(
            "can_access_systematic_review", linked_user, linked_review.id
        )
        assert not my_test_rule(
            "can_access_systematic_review", linked_user, other_review.id
        )
        assert not my_test_rule(
            "can_access_systematic_review", other_user, linked_review.id
        )
