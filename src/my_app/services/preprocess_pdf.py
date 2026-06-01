from my_app.models import Document, DocumentMetadata
from my_app.pdf_processor import StructureProcessor, get_pdf_processor
from shortcuts import logger


class QueuePreprocessPDFService:
    """
    creates metadata record
    queues up the grobid processing task

    (later TODO: queue up the docint task too)
    """

    def __init__(self, document: Document):
        self.document = document

    def perform(self):
        from my_app.tasks.process_document_task import (
            process_document_metadata,
        )

        logger.info(
            "QueuePreprocessPDFService started for document_id=%s",
            self.document.id,
        )

        metadata_record, created = DocumentMetadata.objects.get_or_create(
            document=self.document,
        )

        if not created:
            logger.info(
                "QueuePreprocessPDFService was called "
                "for a document (document_id=%s) "
                "that already has a metadata record. "
                "this is tolerated, but unexpected ",
                self.document.id,
            )

        metadata_record.status = (
            DocumentMetadata.DocumentProcessingStatus.PENDING
        )
        metadata_record.save()

        process_document_metadata.enqueue(document_id=self.document.id)


class PreprocessPDFService:
    """
    performs the actual grobid processing of the PDF
    """

    def __init__(self, document: Document):
        self.document = document

    def perform(self):
        logger.info(
            "PreprocessPDFService started for document_id=%s", self.document.id
        )

        document = self.document
        document_metadata = document.document_metadata

        try:
            raw_xml = get_pdf_processor().process_pdf(document.file)
            structure_processor = StructureProcessor(raw_xml)
            pages = structure_processor.get_pages()
            coordinates = structure_processor.get_coordinates()
        except Exception:
            document_metadata.status = (
                DocumentMetadata.DocumentProcessingStatus.FAILED
            )
            document_metadata.save(update_fields=["status"])
            raise

        document_metadata.raw_xml = raw_xml
        document_metadata.pages = pages
        document_metadata.coordinates = coordinates
        document_metadata.status = (
            DocumentMetadata.DocumentProcessingStatus.COMPLETED
        )
        document_metadata.save()
