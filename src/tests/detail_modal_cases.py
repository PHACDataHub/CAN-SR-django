from types import SimpleNamespace

from my_app import model_factories as factories
from my_app import models

ANSWER_CASES = (
    "neither",
    "ai-only",
    "human-only",
    "agreement",
    "disagreement",
    "multiple-humans",
    "pending",
    "error",
    "critical-disagreement",
    "critical-pending",
    "critical-error",
)


def create_answer_case(stage, case):
    review = factories.ReviewFactory(title="Community health review")
    citation = factories.CitationFactory(
        dataset=factories.CitationDatasetFactory(review=review),
        order=1,
        title="Community health interventions in Canada",
        abstract="A randomized study of community health interventions and population outcomes.",
        data={
            "Authors": ["A. Smith", "B. Chen"],
            "Year": 2025,
            "Population": "Adults in Canada",
            "Metadata": {"source": "MEDLINE"},
        },
    )
    column = factories.CitationDatasetColumnFactory(
        dataset=citation.dataset, name="Population"
    )
    citation.dataset.screening_columns.add(column)
    prefix = stage.upper()
    question = getattr(factories, f"{prefix}ScreeningQuestionFactory")(
        review=review,
        question_text="Does the study include the population of interest?",
    )
    option_factory = getattr(
        factories, f"{prefix}ScreeningQuestionOptionFactory"
    )
    include = option_factory(
        question=question,
        option_text="Include",
        option_value="Includes Canadian adults",
        screening_action="screen_in",
    )
    exclude = option_factory(
        question=question,
        option_text="Exclude",
        option_value="Population outside the review scope",
        screening_action="screen_out",
    )
    result = None
    if case not in {"neither", "human-only"}:
        status = models.ScreeningResultStatus.COMPLETED
        selected = include
        if case == "pending":
            status = models.ScreeningResultStatus.PENDING
            selected = None
        elif case == "error":
            status = models.ScreeningResultStatus.ABANDONED
            selected = None
        result = getattr(factories, f"{prefix}ScreeningResultFactory")(
            citation=citation,
            question=question,
            selected_option=selected,
            status=status,
            confidence=0.94 if selected else None,
            explanation="The study population meets the inclusion criteria.",
        )
        if case == "error":
            result.explanation = (
                "Screening could not be completed: UnexpectedLLMOutputError"
            )
            result.abandoned_at = result.updated_at
            result.save()
        if stage == "l2":
            document = factories.DocumentFactory()
            citation.document = document
            citation.save()
            factories.TextExtractionResultFactory(
                document=document,
                status="completed",
                coordinates=[
                    {
                        "type": "s",
                        "text": "Participants were adults living in Canada.",
                    }
                ],
            )
            models.DocumentTable.objects.create(
                document=document,
                index=1,
                caption="Study population",
                description="Participant characteristics by study group.",
                table_markdown="| Group | Participants |\n| Intervention | 120 |\n| Control | 118 |",
            )
            models.DocumentFigure.objects.create(
                document=document,
                index=2,
                caption="Participant flow",
                description="Participants recruited from Canadian community clinics.",
            )
            result.evidence_sentences = [0]
            result.evidence_tables = [1]
            result.evidence_figures = [2]
            result.save()
        if case not in {"pending", "error"}:
            critical_status = models.ScreeningResultStatus.COMPLETED
            if case == "critical-pending":
                critical_status = models.ScreeningResultStatus.PENDING
            elif case == "critical-error":
                critical_status = models.ScreeningResultStatus.ABANDONED
            getattr(models, f"{prefix}CriticalScreeningResult").objects.create(
                initial_result=result,
                status=critical_status,
                confidence=0.92 if critical_status == "completed" else None,
                selected_option=(
                    exclude if case == "critical-disagreement" else None
                ),
                error=(
                    "Critical screening could not be completed: UnexpectedLLMOutputError"
                    if case == "critical-error"
                    else ""
                ),
            )
    if case in {"human-only", "agreement", "disagreement", "multiple-humans"}:
        human_factory = getattr(factories, f"{prefix}HumanAnswerFactory")
        human_factory(
            citation=citation,
            question=question,
            user=factories.UserFactory(
                username="reviewer-alex", first_name="Alex", last_name="Smith"
            ),
            selected_option=exclude if case == "disagreement" else include,
            notes="Population verified against the eligibility criteria.",
        )
        if case == "multiple-humans":
            human_factory(
                citation=citation,
                question=question,
                user=factories.UserFactory(
                    username="reviewer-blair",
                    first_name="Blair",
                    last_name="Chen",
                ),
                selected_option=exclude,
                notes="Second review: population needs further assessment.",
            )
    return SimpleNamespace(
        review=review, citation=citation, question=question, result=result
    )
