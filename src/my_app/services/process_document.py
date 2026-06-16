from my_app.models import Document
from my_app.services.figure_extraction_service import (
    QueueFigureExtractionService,
)
from my_app.services.text_extraction import QueueTextExtractionService
from shortcuts import logger


class QueueProcessDocumentService:
    def __init__(self, document: Document):
        self.document = document

    def perform(self):

        logger.info(
            "QueueProcessDocumentService started for document_id=%s",
            self.document.id,
        )

        QueueTextExtractionService(self.document).perform()
        QueueFigureExtractionService(self.document).perform()
