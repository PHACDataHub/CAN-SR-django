from proj.text import tdt

from my_app.models import (
    L1HumanAnswer,
    L1ScreeningResult,
    L2HumanAnswer,
    L2ScreeningResult,
)

from .answer_table import AnswerTableDef
from .table_framework import DateTimeAttributeColumn


class AIAnswerTableDef(AnswerTableDef):
    def answer_columns(self):
        return [
            *self.ai_columns(prefix="table_ai."),
            *self.human_columns(prefix="table_human."),
            DateTimeAttributeColumn(
                "updated_at", tdt("Last updated"), sort_field="updated_at"
            ),
        ]


class L1AIAnswerTableDef(AIAnswerTableDef):
    title = tdt("L1 AI answers")
    stage = "l1"
    model = result_model = L1ScreeningResult
    answer_model = L1HumanAnswer


class L2AIAnswerTableDef(AIAnswerTableDef):
    title = tdt("L2 AI answers")
    stage = "l2"
    model = result_model = L2ScreeningResult
    answer_model = L2HumanAnswer
