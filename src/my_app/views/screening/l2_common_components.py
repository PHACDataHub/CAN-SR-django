import htpy as h

from my_app.models import Citation, L2ScreeningResult, Review
from my_app.views.screening.components import (
    Badge,
    human_review_control_id,
    render_human_review_control,
)
from my_app.views.screening.util import BADGE_CLASSES
from shortcuts import reverse, tdt


def L2ScreeningBadge(citation_row: Citation, status_fetcher):
    status = status_fetcher.get(citation_row.id)
    return Badge(
        status.label,
        BADGE_CLASSES[status],
        badge_id=f"l2-screening-row-status-{citation_row.id}",
    )


def l2_human_review_control_id(result):
    return human_review_control_id("l2", result)


def render_l2_human_review_control(result: L2ScreeningResult, review: Review):
    return render_human_review_control(
        result,
        prefix="l2",
        answer_url=reverse(
            "screen_l2_human_answer", args=[review.id, result.id]
        ),
        validate_url=reverse(
            "screen_l2_validate_correct", args=[review.id, result.id]
        ),
        undo_validation_url=reverse(
            "screen_l2_undo_validation", args=[review.id, result.id]
        ),
    )
