from my_app.models import Document, TextExtractionResult
from my_app.pdf.text_extraction.processors import get_pdf_processor
from my_app.pdf.text_extraction.tei import GrobidTeiParser
from shortcuts import logger


class QueueTextExtractionService:
    """
    creates text extraction result record
    queues up the text extraction task

    (later TODO: queue up the docint task too)
    """

    def __init__(self, document: Document):
        self.document = document

    def perform(self):
        from my_app.tasks.text_extraction_task import (
            process_text_extraction_result,
        )

        logger.info(
            "QueueTextExtractionService started for document_id=%s",
            self.document.id,
        )

        text_extraction_result, created = (
            TextExtractionResult.objects.get_or_create(
                document=self.document,
            )
        )

        if not created:
            logger.info(
                "QueueTextExtractionService was called "
                "for a document (document_id=%s) "
                "that already has a text extraction result. "
                "this is tolerated, but unexpected ",
                self.document.id,
            )

        text_extraction_result.status = (
            TextExtractionResult.TextExtractionStatus.PENDING
        )
        text_extraction_result.save()

        process_text_extraction_result.enqueue(document_id=self.document.id)


class TextExtractionService:
    """
    performs text extraction for the PDF
    """

    def __init__(self, document: Document):
        self.document = document

    def perform(self):
        logger.info(
            "TextExtractionService started for document_id=%s",
            self.document.id,
        )

        document = self.document
        text_extraction_result = document.text_extraction_result

        try:
            raw_xml = get_pdf_processor().process_pdf(document.file)
            parser = GrobidTeiParser(raw_xml)
            pages = parser.get_pages()
            coordinates = parser.get_coordinates()
        except Exception:
            text_extraction_result.status = (
                TextExtractionResult.TextExtractionStatus.FAILED
            )
            text_extraction_result.save(update_fields=["status"])
            raise

        text_extraction_result.raw_xml = raw_xml
        text_extraction_result.pages = pages
        text_extraction_result.coordinates = coordinates
        text_extraction_result.status = (
            TextExtractionResult.TextExtractionStatus.COMPLETED
        )
        text_extraction_result.save()
