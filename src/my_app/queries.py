from data_fetcher.extras import cache_within_request as cached_within_request
from phac_aspc.rules import test_rule

from my_app.models import SystematicReview, SystematicReviewUserLink


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
