import json
from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import override_settings

import pytest

pytestmark = pytest.mark.backend

XML = """
<TEI>
  <text>
    <p coords="1,10,20,30,40">Paragraph</p>
  </text>
  <surface ulx="0" uly="0" lrx="612" lry="792" />
</TEI>
"""


class FakePdfProcessor:
    def process_pdf(self, file_descriptor):
        assert file_descriptor.read() == b"%PDF-1.4 fake"
        return XML


@override_settings(
    GROBID_URL="http://grobid.example",
    IS_RUNNING_PYTESTS=False,
)
def test_check_grobid_command_outputs_json(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    stdout = StringIO()

    with patch(
        "my_app.management.commands.check_grobid.get_pdf_processor",
        return_value=FakePdfProcessor(),
    ):
        call_command(
            "check_grobid",
            str(pdf_path),
            stdout=stdout,
            verbosity=0,
        )

    payload = json.loads(stdout.getvalue())

    assert payload["raw_xml"].strip() == XML.strip()
    assert payload["pages"] == [{"width": 612.0, "height": 792.0}]
    assert payload["coordinates"] == [
        {
            "page": 1,
            "x": 10.0,
            "y": 20.0,
            "width": 30.0,
            "height": 40.0,
            "color": "rgba(139, 0, 0, 0.4)",
            "type": "p",
            "text": "Paragraph",
        }
    ]


@override_settings(
    GROBID_URL="dev",
    IS_RUNNING_PYTESTS=False,
)
def test_check_grobid_command_rejects_demo_mode(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    try:
        call_command("check_grobid", str(pdf_path), verbosity=0)
    except CommandError as exc:
        assert "requires a real Grobid server URL" in str(exc)
    else:
        raise AssertionError("Expected CommandError")
