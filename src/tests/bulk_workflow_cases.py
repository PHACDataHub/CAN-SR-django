from my_app.model_factories import (
    CitationDatasetFactory,
    CitationFactory,
    DocumentFactory,
    FigureExtractionResultFactory,
    L1ScreeningQuestionFactory,
    L1ScreeningQuestionOptionFactory,
    L2HumanAnswerFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterFactory,
    ReviewFactory,
    TextExtractionResultFactory,
)
from my_app.models import ScreeningActions


def bulk_context(phase, count=2):
    review = ReviewFactory()
    dataset = CitationDatasetFactory(review=review)
    citations = [CitationFactory(dataset=dataset) for _ in range(count)]
    if phase == 1:
        question = L1ScreeningQuestionFactory(review=review)
        option = L1ScreeningQuestionOptionFactory(question=question)
    else:
        question = ParameterFactory(review=review)
        option = None
        l2 = L2ScreeningQuestionFactory(review=review)
        include = L2ScreeningQuestionOptionFactory(
            question=l2, screening_action=ScreeningActions.ScreenIn
        )
        for citation in citations:
            citation.document = DocumentFactory()
            citation.save()
            TextExtractionResultFactory(
                document=citation.document, status="completed"
            )
            FigureExtractionResultFactory(
                document=citation.document, status="completed"
            )
            L2HumanAnswerFactory(
                citation=citation, question=l2, selected_option=include
            )
    return review, citations, question, option
