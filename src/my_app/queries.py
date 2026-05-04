from data_fetcher.extras import cache_within_request as cached_within_request
from phac_aspc.rules import test_rule

from my_app.models import (
    Project,
    ProjectUserRole,
    SystematicReview,
    SystematicReviewUserLink,
)


@cached_within_request
def get_accessible_systematic_reviews(user_id):
    if not user_id:
        return []

    accessible_ids = SystematicReviewUserLink.objects.filter(
        user_id=user_id
    ).values_list("systematic_review_id", flat=True)
    return list(
        SystematicReview.objects.filter(id__in=accessible_ids).order_by(
            "-created_at", "-id"
        )
    )


def get_project_qs_for_user(user):
    if test_rule("is_admin", user):
        return Project.objects.all()

    roles = ProjectUserRole.objects.filter(user=user)
    proj_ids = [role.project_id for role in roles]
    return Project.objects.filter(id__in=proj_ids)
