from abc import ABC, abstractmethod

from django.conf import settings

from bs4 import BeautifulSoup
from grobid_client.grobid_client import GrobidClient

"""
This whole module is ideally never called from a django request, 
only from background tasks

There should be no async here, because grobid client does not support async

We can look into performance later:
- async
    - we can use httpx and query grobid ourselves without grobid-client
    - or use alternative grobid-client lib that does this for us using async
    - for this reason, isolate all grobid interaction in case we need to swap out client
- OR, tweaking background task concurrency settings 
"""


class PdfProcessor(ABC):
    @abstractmethod
    def process_pdf(self, file_descriptor):
        pass

    @abstractmethod
    def process_text(self, text):
        pass


def get_grobid_client():
    # safer not to cache instance for now
    return GrobidClient(
        grobid_server=settings.GROBID_URL,
        # ....
    )


class GrobidPdfProcessor(PdfProcessor):
    def __init__(self):
        self.grobid_client = get_grobid_client()

    def process_pdf(self, file_descriptor):
        return self.grobid_client.process(
            "processFulltextDocument", file_descriptor
        )

    def process_text(self, text):
        soup = BeautifulSoup(text, "html.parser")
        return soup.get_text()


class TestPdfProcessor(PdfProcessor):
    def process_pdf(self, file_descriptor):
        return "processed pdf"

    def process_text(self, text):
        return text


class MinimalDevPdfProcessor(PdfProcessor):
    """
    return constants or semi-random trivial metadata
    """

    def process_pdf(self, file_descriptor):
        return "processed pdf - minimal dev"

    def process_text(self, text):
        return text


def get_pdf_processor():
    if settings.IS_RUNNING_PYTESTS:
        return TestPdfProcessor()

    if not settings.GROBID_URL:

        raise ValueError(
            "GROBID_URL is not set. "
            "Set GROBID_URL in environment variables "
            "or set GROBID_URL=dev"
        )

    if settings.GROBID_URL == "dev":
        return MinimalDevPdfProcessor()

    return GrobidPdfProcessor()
