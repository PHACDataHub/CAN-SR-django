from phac_aspc.rules import add_rule, auto_rule

from .constants import ADMIN_USER_GROUP
from .queries import get_accessible_systematic_reviews


@auto_rule
def is_admin(user):
    return user.is_authenticated and (
        user.is_superuser or ADMIN_USER_GROUP in user.group_names
    )


@auto_rule
def can_access_systematic_review(user, systematic_review_id):
    if is_admin(user):
        return True

    accessible_reviews = get_accessible_systematic_reviews(user.id)
    return any(
        review.id == systematic_review_id for review in accessible_reviews
    )
