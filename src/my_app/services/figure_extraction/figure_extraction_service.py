from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction

from my_app.models import (
    Document,
    DocumentFigure,
    DocumentTable,
    FigureExtractionResult,
)
from shortcuts import cached_property, logger

from .figure_extraction_client import get_figure_extraction_client
from .figure_extraction_util import DocIntResult


class QueueFigureExtractionService:
    def __init__(self, document: Document):
        self.document = document

    def perform(self):
        from my_app.tasks.figure_extraction_task import (
            process_figure_extraction,
        )

        logger.info(
            "QueueFigureExtractionService started for document_id=%s",
            self.document.id,
        )

        result_record, created = FigureExtractionResult.objects.get_or_create(
            document=self.document,
        )
        if not created:
            logger.info(
                "QueueFigureExtractionService was called for a document "
                "(document_id=%s) that already has a result record.",
                self.document.id,
            )

        result_record.status = FigureExtractionResult.Status.PENDING
        result_record.save(update_fields=["status", "updated_at"])

        process_figure_extraction.enqueue(document_id=self.document.id)


class FigureExtractionService:
    """
    Should be called from task
    """

    def __init__(self, document: Document):
        self.document = document

    @cached_property
    def progress_result_record(self):
        result_record, created = FigureExtractionResult.objects.get_or_create(
            document=self.document,
            defaults={
                "status": FigureExtractionResult.Status.PENDING,
            },
        )
        return result_record

    @cached_property
    def extraction_result(self) -> DocIntResult:
        client = get_figure_extraction_client()
        result = client.extract_figures(self.document.file)
        return result

    def save_figures(self):
        result = self.extraction_result
        for figure in result.figures:
            document_figure = DocumentFigure(
                document=self.document,
                index=figure.index,
                caption=figure.caption,
                bounding_box=[
                    coordinate.model_dump()
                    for coordinate in figure.coordinates
                ],
            )
            if figure.image is not None:
                filename = self.get_figure_filename(figure.index)
                document_figure.file.save(
                    filename,
                    ContentFile(figure.image.png_bytes),
                    save=False,
                )
            document_figure.save()

    def get_figure_filename(self, index: int) -> str:
        document_stem = Path(self.document.file.name).stem or "document"
        return (
            f"documents/{self.document.id}/figures/"
            f"{document_stem}_figure_{index}.png"
        )

    def save_tables(self):
        result = self.extraction_result
        tables = [
            DocumentTable(
                document=self.document,
                index=table.index,
                caption=table.caption or "",
                table_markdown=table.markdown,
                bounding_box=[
                    coordinate.model_dump() for coordinate in table.coordinates
                ],
            )
            for table in result.tables
        ]
        DocumentTable.objects.bulk_create(tables)

    def clear_data(self):
        self.progress_result_record.status = (
            FigureExtractionResult.Status.PENDING
        )
        self.progress_result_record.save(
            update_fields=["status", "updated_at"]
        )
        DocumentFigure.objects.filter(document=self.document).delete()
        DocumentTable.objects.filter(document=self.document).delete()

    def set_success(self):
        self.progress_result_record.status = (
            FigureExtractionResult.Status.COMPLETED
        )
        self.progress_result_record.save(
            update_fields=["status", "updated_at"]
        )

    def perform(self):
        # TODO: add failure handling in the next pass.
        with transaction.atomic():
            self.clear_data()
            self.save_figures()
            self.save_tables()
            self.set_success()
