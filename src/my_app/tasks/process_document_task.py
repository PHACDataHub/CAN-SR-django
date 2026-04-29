from django.tasks import task

from my_app.models import Document, DocumentMetadata
from my_app.pdf_processor import get_pdf_processor


@task(takes_context=True)
def process_document_metadata(context, document_id: int):

    document = Document.objects.get(pk=document_id)
    metadata = get_pdf_processor().process_pdf(document.file)

    if not isinstance(metadata, dict):
        metadata = {"text": metadata}

    document = Document.objects.get(pk=document_id)
    document_metadata, _ = DocumentMetadata.objects.update_or_create(
        document=document,
        defaults={"metadata": metadata},
    )

    # not sure if worth it to return anything at all...
    # return {
    #     "task_result_id": context.task_result.id,
    #     "attempt": context.attempt,
    # }
