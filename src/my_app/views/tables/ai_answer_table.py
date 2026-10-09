from my_app.router import route
from my_app.tables.ai_answer_table import (
    L1AIAnswerTableDef,
    L2AIAnswerTableDef,
)

from .common import ReviewTableView


@route(
    "/reviews/<int:review_id>/tables/l1-ai-answers/", name="l1_ai_answer_table"
)
class L1AIAnswerTableView(ReviewTableView):
    table_def_class = L1AIAnswerTableDef


@route(
    "/reviews/<int:review_id>/tables/l2-ai-answers/", name="l2_ai_answer_table"
)
class L2AIAnswerTableView(ReviewTableView):
    table_def_class = L2AIAnswerTableDef
