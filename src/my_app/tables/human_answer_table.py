from proj.text import tdt

from my_app.models import (
    L1HumanAnswer,
    L1ScreeningResult,
    L2HumanAnswer,
    L2ScreeningResult,
)

from .answer_table import AnswerTableDef
from .table_framework import DateTimeAttributeColumn


class HumanAnswerTableDef(AnswerTableDef):
    def answer_columns(self):
        return [
            *self.human_columns(),
            *self.ai_columns(prefix="table_ai."),
            DateTimeAttributeColumn(
                "updated_at", tdt("Last updated"), sort_field="updated_at"
            ),
        ]

    def get_base_queryset(self):
        return super().get_base_queryset().select_related("user")


class L1HumanAnswerTableDef(HumanAnswerTableDef):
    title = tdt("L1 human answers")
    stage = "l1"
    model = answer_model = L1HumanAnswer
    result_model = L1ScreeningResult


class L2HumanAnswerTableDef(HumanAnswerTableDef):
    title = tdt("L2 human answers")
    stage = "l2"
    model = answer_model = L2HumanAnswer
    result_model = L2ScreeningResult
