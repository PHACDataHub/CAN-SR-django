from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from my_app.pdf_processor import StructureProcessor, get_pdf_processor


def validate_grobid_url() -> str:
    grobid_url = settings.GROBID_URL.strip()

    if not grobid_url:
        raise CommandError(
            "GROBID_URL is not set. Set it to the Grobid server URL."
        )

    if grobid_url == "dev":
        raise CommandError(
            "GROBID_URL='dev' uses the demo processor; this command requires "
            "a real Grobid server URL."
        )

    parsed_url = urlparse(grobid_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise CommandError(
            "GROBID_URL must be a full http(s) URL, got '%s'" % grobid_url
        )

    return grobid_url


def build_payload(pdf_path: Path) -> dict:
    validate_grobid_url()

    pdf_processor = get_pdf_processor()
    with pdf_path.open("rb") as pdf_file:
        raw_xml = pdf_processor.process_pdf(pdf_file)

    structure_processor = StructureProcessor(raw_xml)

    return {
        "raw_xml": raw_xml,
        "pages": structure_processor.get_pages(),
        "coordinates": structure_processor.get_coordinates(),
    }


class Command(BaseCommand):
    help = "Run Grobid against a PDF and print the raw XML, pages, and coordinates as JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "pdf_path",
            help="Path to the PDF file to process.",
        )

    def handle(self, *args, **options):
        pdf_path = Path(options["pdf_path"])

        if not pdf_path.exists():
            raise CommandError("PDF file does not exist: %s" % pdf_path)

        if not pdf_path.is_file():
            raise CommandError("PDF path is not a file: %s" % pdf_path)

        payload = build_payload(pdf_path)
        self.stdout.write(json.dumps(payload, indent=2))
