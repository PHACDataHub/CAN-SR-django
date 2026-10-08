from my_app.router import route
from my_app.tables.human_answer_table import (
    L1HumanAnswerTableDef,
    L2HumanAnswerTableDef,
)

from .common import ReviewTableView


@route(
    "/reviews/<int:review_id>/tables/l1-human-answers/",
    name="l1_human_answer_table",
)
class L1HumanAnswerTableView(ReviewTableView):
    table_def_class = L1HumanAnswerTableDef


@route(
    "/reviews/<int:review_id>/tables/l2-human-answers/",
    name="l2_human_answer_table",
)
class L2HumanAnswerTableView(ReviewTableView):
    table_def_class = L2HumanAnswerTableDef
