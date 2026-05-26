from django.tasks import task

from my_app.models import Document, DocumentMetadata
from my_app.pdf_processor import StructureProcessor, get_pdf_processor


@task(takes_context=True)
def process_document_metadata(context, document_id: int):

    document = Document.objects.get(pk=document_id)
    raw_xml = get_pdf_processor().process_pdf(document.file)
    structure_processor = StructureProcessor(raw_xml)
    pages = structure_processor.get_pages()
    coordinates = structure_processor.get_coordinates()

    document = Document.objects.get(pk=document_id)
    document_metadata, _ = DocumentMetadata.objects.update_or_create(
        document=document,
        defaults={
            "raw_xml": raw_xml,
            "pages": pages,
            "coordinates": coordinates,
        },
    )
