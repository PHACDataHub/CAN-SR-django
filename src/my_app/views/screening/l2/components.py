from my_app.models import Citation
from my_app.views.screening.components import Badge
from my_app.views.screening.util import BADGE_CLASSES


def L2ScreeningBadge(citation_row: Citation, status_fetcher):
    status = status_fetcher.get(citation_row.id)
    return Badge(
        status.label,
        BADGE_CLASSES[status],
        badge_id=f"l2-screening-row-status-{citation_row.id}",
    )
