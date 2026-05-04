import os
import tempfile
from abc import ABC, abstractmethod

from django.conf import settings

from bs4 import BeautifulSoup
from grobid_client.grobid_client import GrobidClient

from proj.util import JSONValue

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


TODO: 
- document consistent format/type we expect from processor
    - change test/dev processors to return that format
- split up any consistent types into proper model fields
- the rest can go into json 
- use lxml or BS4 to parse grobid's xml output and extract relevant metadata
    - e.g. coordinates, pages, 
"""


class PdfProcessor(ABC):

    def process_pdf(self, file):
        xml = self.pdf_to_xml(file)
        return self.xml_to_json(xml)

    def process_text(self, text):
        xml = self.text_to_xml(text)
        return self.xml_to_json(xml)

    @abstractmethod
    def pdf_to_xml(self, file_descriptor) -> str:
        raise NotImplementedError

    @abstractmethod
    def text_to_xml(self, text) -> str:
        raise NotImplementedError

    def xml_to_json(self, xml_str: str) -> JSONValue:
        # placeholder for actual XML parsing logic
        soup = BeautifulSoup(xml_str, "xml")
        # extract relevant metadata from the XML and return as dict
        return {"xml_content": soup.prettify()}


def get_grobid_client():
    # safer not to cache instance for now
    return GrobidClient(
        grobid_server=settings.GROBID_URL,
        # ....
    )


def get_xml_from_grobid(file):
    grobid_client = get_grobid_client()
    try:
        # grobid client only accepts file paths,
        # so we need to write the uploaded file to a temp location
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(file.read())
        tmp.flush()
        tmp.close()

        _file, status, xml = grobid_client.process_pdf(
            "processFulltextDocument",
            tmp.name,
            consolidate_header=True,
            consolidate_citations=False,
            segment_sentences=True,
            tei_coordinates=True,
            include_raw_citations=False,
            include_raw_affiliations=False,
            generateIDs=True,
        )
        return xml
    finally:
        os.unlink(tmp.name)


class GrobidPdfProcessor(PdfProcessor):
    def __init__(self):
        self.grobid_client = get_grobid_client()

    def pdf_to_xml(self, file) -> str:
        xml = get_xml_from_grobid(file)
        return xml

    def text_to_xml(self, text) -> str:
        raise Exception("TODO")


class TestPdfProcessor(PdfProcessor):
    def pdf_to_xml(self, file_descriptor) -> str:
        return "<test>pdf content</test>"

    def text_to_xml(self, text) -> str:
        return f"<test>{text}</test>"


class MinimalDevPdfProcessor(TestPdfProcessor):
    """
    same as test for now
    maybe we should introduce some randomness in this one
    """

    pass


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
