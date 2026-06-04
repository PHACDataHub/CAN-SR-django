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


class StructureProcessor:

    COLORS = {
        "persName": "rgba(0, 0, 255, 1)",  # Blue
        "s": "rgba(139, 0, 0, 1)",  # Green
        "p": "rgba(139, 0, 0, 1)",  # Dark red
        "ref": "rgba(255, 255, 0, 1)",  # ??
        "biblStruct": "rgba(139, 0, 0, 1)",  # Dark Red
        "head": "rgba(139, 139, 0, 1)",  # Dark Yellow
        "formula": "rgba(255, 165, 0, 1)",  # Orange
        "figure": "rgba(165, 42, 42, 1)",  # Brown
        "title": "rgba(255, 0, 0, 1)",  # Red
        "affiliation": "rgba(255, 165, 0, 1)",  # red-orengi
    }

    @classmethod
    def _get_color(cls, name, param):
        color = cls.COLORS.get(name, "rgba(128, 128, 128, 1.0)")
        if param:
            color = color.replace("1)", "0.4)")

        return color

    def __init__(self, xml_text):
        self.soup = BeautifulSoup(xml_text, "xml")

    def get_pages(
        self,
    ):
        pages_infos = self.soup.find_all("surface")

        pages = [
            {
                "width": float(page["lrx"]) - float(page["ulx"]),
                "height": float(page["lry"]) - float(page["uly"]),
            }
            for page in pages_infos
        ]

        return pages

    def get_coordinates(self):
        # exclude certain tag names
        all_blocks_with_coordinates = self.soup.find("text").find_all(
            coords=True
        )

        def filt(c):
            return len(c) > 0 and c[0] != ""

        coordinates = []
        count = 0
        for block_id, block in enumerate(all_blocks_with_coordinates):
            for box in filter(filt, block["coords"].split(";")):
                coordinates.append(
                    self._box_to_dict(
                        box.split(","),
                        self._get_color(block.name, count % 2 == 0),
                        type=block.name,
                        text=block.text,
                    ),
                )
            count += 1
        return coordinates

    @staticmethod
    def _box_to_dict(box, color=None, type=None, text=None):

        item = {
            "page": box[0],
            "x": box[1],
            "y": box[2],
            "width": box[3],
            "height": box[4],
        }
        if color is not None:
            item["color"] = color

        if type:
            item["type"] = type

        if text:
            item["text"] = text

        return item
