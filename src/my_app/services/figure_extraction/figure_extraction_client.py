"""
This is mostly plumbing, most of the smarts around querying azure
and handling its output will be in the sibling util module
"""

from abc import ABC, abstractmethod

from django.conf import settings

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    AnalyzeResult,
    BoundingRegion,
    DocumentFigure,
    DocumentPage,
    DocumentTable,
)
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential

from shortcuts import logger

from .figure_extraction_util import DocIntResult, process_pdf_with_docint


class DocIntConfigurationError(Exception):
    pass


class FigureExtractionClient(ABC):
    @abstractmethod
    def extract_figures(self, file) -> DocIntResult:
        pass


class AzureDocIntExtractionClient(FigureExtractionClient):
    def __init__(self, docint_client: DocumentIntelligenceClient):
        self.docint_client = docint_client

    def extract_figures(self, file) -> DocIntResult:
        result = process_pdf_with_docint(file=file, client=self.docint_client)

        return result


def get_azure_client():
    if settings.AZURE_DOC_INT_MODE not in ["key", "entra"]:
        raise DocIntConfigurationError(
            f"Invalid AZURE_DOC_INT_MODE: {settings.AZURE_DOC_INT_MODE}. "
            "Must be 'key' or 'entra'."
        )

    if not settings.AZURE_DOC_INT_ENDPOINT:
        raise DocIntConfigurationError(
            "Azure Document Intelligence endpoint not found. "
            "Set AZURE_DOC_INT_ENDPOINT environment variable."
        )

    if (
        settings.AZURE_DOC_INT_MODE == "key"
        and not settings.AZURE_DOC_INT_API_KEY
    ):
        raise DocIntConfigurationError(
            "Azure Document Intelligence API key not found. "
            "Set AZURE_DOC_INT_API_KEY for key-based auth."
        )

    if settings.AZURE_DOC_INT_MODE == "key":
        credential = AzureKeyCredential(settings.AZURE_DOC_INT_API_KEY)
    elif settings.AZURE_DOC_INT_MODE == "entra":
        credential = DefaultAzureCredential()
    else:
        # This should never happen due to the earlier check,
        # but we include it for completeness.
        raise DocIntConfigurationError(
            f"Unsupported AZURE_DOC_INT_MODE: {settings.AZURE_DOC_INT_MODE}"
        )

    try:
        docint_client = DocumentIntelligenceClient(
            endpoint=settings.AZURE_DOC_INT_ENDPOINT,
            credential=credential,
        )
        return AzureDocIntExtractionClient(docint_client)
    except Exception as e:
        raise DocIntConfigurationError(
            f"Failed to initialize Azure Document Intelligence client: {e}"
        ) from e


class FakeFigureExtractionClient(FigureExtractionClient):
    def extract_figures(self, file) -> DocIntResult:
        logger.info(
            "FakeFigureExtractionClient called - returning empty result"
        )
        return DocIntResult(
            # TODO get better fake structure here
            figures=[],
            tables=[],
        )


def get_figure_extraction_client() -> FigureExtractionClient:
    if settings.FIGURE_EXTRACTION_MODE == "azure_doc_int":
        return get_azure_client()

    else:

        return FakeFigureExtractionClient()
