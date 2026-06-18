import htpy as h

from my_app.models import ScreeningResultStatus
from my_app.views.screening.util import BADGE_CLASSES
from shortcuts import tdt


def Badge(label, class_name, badge_id=None):
    attrs = {
        "class_": f"badge rounded-pill {class_name}",
    }
    if badge_id is not None:
        attrs["id"] = badge_id

    return h.span(**attrs)[label]


def NotStartedBadge():
    return Badge(
        ScreeningResultStatus.NOT_STARTED.label,
        BADGE_CLASSES[ScreeningResultStatus.NOT_STARTED],
    )


def EmptyCitationPageMessage():
    return h.p(".text-muted.mb-0")[tdt("No citations on this page.")]
