import os
import tempfile
from abc import ABC, abstractmethod

from django.conf import settings

from grobid_client.grobid_client import GrobidClient


class PdfProcessor(ABC):
    def process_pdf(self, file):
        xml = self.pdf_to_xml(file)
        return xml

    def process_text(self, text):
        xml = self.text_to_xml(text)
        return xml

    @abstractmethod
    def pdf_to_xml(self, file_descriptor) -> str:
        raise NotImplementedError

    @abstractmethod
    def text_to_xml(self, text) -> str:
        raise NotImplementedError


class GrobidPdfProcessor(PdfProcessor):
    def pdf_to_xml(self, file) -> str:
        xml = get_xml_from_grobid(file)
        return xml

    def text_to_xml(self, text) -> str:
        raise Exception("TODO")


TEST_XML_STR = """
<TEI>
  <text>
    <p coords="1,10,20,30,40;2,15,25,35,45;">Paragraph</p>
    <head coords="2,50,60,70,80">Heading</head>
  </text>
  <surface ulx="0" uly="0" lrx="612" lry="792" />
  <surface ulx="10" uly="20" lrx="210" lry="320" />
</TEI>
"""


class TestPdfProcessor(PdfProcessor):
    def pdf_to_xml(self, file_descriptor) -> str:
        return TEST_XML_STR

    def text_to_xml(self, text) -> str:
        return TEST_XML_STR


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


def get_grobid_client():
    return GrobidClient(grobid_server=settings.GROBID_URL)


def get_xml_from_grobid(file):
    grobid_client = get_grobid_client()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    try:
        # grobid client only accepts file paths,
        # so we need to write the uploaded file to a temp location
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
