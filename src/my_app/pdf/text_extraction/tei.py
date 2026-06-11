from typing import List

from bs4 import BeautifulSoup

from proj.util import JSONValue

from my_app.pdf.types import PdfCoordinate, PdfPage


class GrobidTeiParser:
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

    def get_page_models(self) -> List[PdfPage]:
        pages_infos = self.soup.find_all("surface")

        return [
            PdfPage(
                width=float(page["lrx"]) - float(page["ulx"]),
                height=float(page["lry"]) - float(page["uly"]),
            )
            for page in pages_infos
        ]

    def get_pages(self) -> List[dict[str, JSONValue]]:
        return [page.as_json_dict() for page in self.get_page_models()]

    def get_coordinate_models(self) -> List[PdfCoordinate]:
        all_blocks_with_coordinates = self.soup.find("text").find_all(
            coords=True
        )

        def filt(c):
            return len(c) > 0 and c[0] != ""

        coordinates = []
        count = 0
        for block in all_blocks_with_coordinates:
            for box in filter(filt, block["coords"].split(";")):
                coordinates.append(
                    self._box_to_coordinate(
                        box.split(","),
                        self._get_color(block.name, count % 2 == 0),
                        annotation_type=block.name,
                        text=block.text,
                    ),
                )
            count += 1
        return coordinates

    def get_coordinates(self) -> List[dict[str, JSONValue]]:
        return [
            coordinate.as_json_dict()
            for coordinate in self.get_coordinate_models()
        ]

    @staticmethod
    def _box_to_coordinate(
        box,
        color=None,
        annotation_type=None,
        text=None,
    ) -> PdfCoordinate:
        if len(box) != 5:
            raise ValueError(
                "Expected a Grobid coordinate box with 5 values, got %s"
                % len(box)
            )

        return PdfCoordinate(
            page=box[0],
            x=box[1],
            y=box[2],
            width=box[3],
            height=box[4],
            color=color,
            annotation_type=annotation_type,
            text=text,
        )

    @staticmethod
    def _box_to_dict(box, color=None, type=None, text=None):
        coordinate = GrobidTeiParser._box_to_coordinate(
            box,
            color=color,
            annotation_type=type,
            text=text,
        )
        return coordinate.as_json_dict()


StructureProcessor = GrobidTeiParser
