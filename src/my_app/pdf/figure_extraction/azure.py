"""
this behavior (with lots of refactoring applied) is ported from CAN-SR
"""

from __future__ import annotations

import re
from typing import Any, Literal, Optional

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeResult,
    BoundingRegion,
    DocumentFigure,
    DocumentPage,
    DocumentTable,
)
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

from my_app.pdf.types import PdfCoordinate

# ---------------------------------------------------------------------------
# Pydantic models for normalized Azure-shaped data we care about
# ---------------------------------------------------------------------------


class AzurePageMeta(BaseModel):
    """Subset of Azure page metadata needed for coordinate normalization.

    Azure often reports page coordinates in inches. The PDF viewer expects a
    PDF-like point/pixel coordinate system. In the production app we multiply
    inch coordinates by 72, which approximates PDF points.
    """

    page_number: int = Field(alias="pageNumber")
    width: Optional[float] = None
    height: Optional[float] = None
    unit: Optional[str] = None


class AzureBoundingRegion(BaseModel):
    """Azure polygon for a table or figure on one page.

    Azure polygons are usually a flat list:

        [x1, y1, x2, y2, x3, y3, x4, y4]

    The app converts that polygon into one axis-aligned rectangle because the
    frontend PDF viewer wants `{page, x, y, width, height}` boxes.
    """

    page_number: int = Field(alias="pageNumber")
    polygon: list[float]


class RawDocIntTable(BaseModel):
    """Table data as extracted from the Azure response before app formatting."""

    index: int
    caption: Optional[str] = None
    bounding_regions: list[AzureBoundingRegion] = Field(default_factory=list)
    table_markdown: str = ""


class RawDocIntFigure(BaseModel):
    """Figure data as extracted from the Azure response before app formatting."""

    index: int
    azure_id: str
    caption: Optional[str] = None
    bounding_regions: list[AzureBoundingRegion] = Field(default_factory=list)
    png_bytes: bytes = Field(default=b"", repr=False)


# ---------------------------------------------------------------------------
# Pydantic models for final port-friendly app data
# ---------------------------------------------------------------------------


class FigureImage(BaseModel):
    """Downloaded figure image data, kept alongside the figure it belongs to.

    In a real app you would usually upload `png_bytes` to object storage and
    keep `blob_address` or a public/private URL. Keeping them together here
    avoids CAN-SR's separate `upload_payloads` list.
    """

    # blob_address: str
    content_type: Literal["image/png"] = "image/png"
    png_bytes: bytes = Field(repr=False)


class ExtractedFigure(BaseModel):
    """Final figure shape for a cleaner port.

    Coordinates live directly on the figure. The PNG file/blob data also lives
    directly on the figure. There is no separate artifact-coordinate list and no
    separate upload-payload list.
    """

    model_config = ConfigDict(populate_by_name=True)

    index: int
    provider_id: str | None = Field(default=None, alias="azure_id")
    caption: Optional[str] = None
    coordinates: list[PdfCoordinate] = Field(default_factory=list)
    image: Optional[FigureImage] = None

    @property
    def azure_id(self) -> str | None:
        return self.provider_id


class ExtractedTable(BaseModel):
    """Final table shape for a cleaner port.

    Tables are text, so markdown is inline string data. Coordinates live
    directly on the table. There is no `.md` file/blob indirection.
    """

    index: int
    caption: Optional[str] = None
    markdown: str
    coordinates: list[PdfCoordinate] = Field(default_factory=list)


class FigureExtractionResultData(BaseModel):
    """Nicely typed end result of the DocInt-only portion of the pipeline."""

    figures: list[ExtractedFigure]
    tables: list[ExtractedTable]


# ---------------------------------------------------------------------------
# Small HTML-table-to-markdown converter
# ---------------------------------------------------------------------------
#
# Azure's markdown output contains HTML `<table>...</table>` chunks. The current
# app pulls those chunks out and converts each table into GitHub-flavored
# markdown before storing it as a table artifact.


def html_table_to_markdown(html_table: str) -> str:
    """Convert one Azure HTML table string to GitHub-flavored markdown."""

    # This mirrors the production helper in azure_docint_client.py:
    # parse the Azure-produced `<table>...</table>` block with BeautifulSoup,
    # then flatten each row's cell text into a markdown table.
    soup = BeautifulSoup(html_table or "", "html.parser")
    table = soup.find("table")
    if table is None:
        return html_table

    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        row = [
            " ".join(cell.get_text(" ", strip=True).split()) for cell in cells
        ]
        if row:
            rows.append(row)

    if not rows:
        return ""

    # Pad ragged rows so every row has the same column count.
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    # Treat the first row as the markdown header, matching current app behavior.
    header = rows[0]
    body = rows[1:]

    def esc(value: str) -> str:
        return (value or "").replace("|", "\\|")

    lines = [
        "| " + " | ".join(esc(value) for value in header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(esc(value) for value in row) + " |")
    return "\n".join(lines)


def extract_html_tables_from_markdown(markdown_content: str) -> list[str]:
    """Extract raw `<table>...</table>` chunks from Azure layout markdown."""

    if not markdown_content:
        return []
    return re.findall(r"<table>.*?</table>", markdown_content, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# Coordinate normalization
# ---------------------------------------------------------------------------
#
# This mirrors api/core/docint_coords.py. Azure returns polygons. The frontend
# wants rectangles. Azure units are commonly inches, so this converts inches to
# PDF points using 72 points per inch.


def unit_to_scale(unit: Optional[str]) -> float:
    """Return multiplier to convert Azure units into viewer coordinate units."""

    if not unit:
        return 1.0
    normalized = unit.strip().lower()
    if normalized in {"pixel", "pixels", "px"}:
        return 1.0
    if normalized in {"inch", "in"}:
        return 72.0
    return 1.0


def polygon_to_bbox(polygon: list[float]) -> tuple[float, float, float, float]:
    """Convert Azure flat polygon coordinates to `(min_x, min_y, max_x, max_y)`."""

    xs = [float(polygon[i]) for i in range(0, len(polygon), 2)]
    ys = [float(polygon[i]) for i in range(1, len(polygon), 2)]
    return min(xs), min(ys), max(xs), max(ys)


def normalize_bounding_regions_to_boxes(
    bounding_regions: list[AzureBoundingRegion],
    pages: list[AzurePageMeta],
) -> list[PdfCoordinate]:
    """Convert Azure bounding regions into CAN-SR viewer boxes."""

    page_by_number = {page.page_number: page for page in pages}
    boxes: list[PdfCoordinate] = []

    for region in bounding_regions:
        page_meta = page_by_number.get(region.page_number)
        scale = unit_to_scale(page_meta.unit if page_meta else None)

        min_x, min_y, max_x, max_y = polygon_to_bbox(region.polygon)
        min_x *= scale
        min_y *= scale
        max_x *= scale
        max_y *= scale

        boxes.append(
            PdfCoordinate(
                page=region.page_number,
                x=min_x,
                y=min_y,
                width=max(0.0, max_x - min_x),
                height=max(0.0, max_y - min_y),
            )
        )

    return boxes


# ---------------------------------------------------------------------------
# Azure client/request helpers
# ---------------------------------------------------------------------------


def extract_result_id_from_poller(poller: Any) -> str:
    """Extract the Azure analyze result ID from the poller.

    Azure's figure download API needs a `result_id`. The current app extracts it
    from the `operation-location` response header. This uses the same private
    SDK internals as the production code because the SDK does not expose the ID
    directly in the result object.
    """

    initial_response = poller._polling_method._initial_response
    headers = initial_response.http_response.headers
    operation_location = headers.get("operation-location") or headers.get(
        "Operation-Location"
    )

    # Example operation location shape:
    #   .../documentModels/prebuilt-layout/analyzeResults/{result_id}?api-version=...
    return operation_location.split("/")[-1].split("?")[0]


def analyze_pdf(
    client: DocumentIntelligenceClient, file: Any
) -> tuple[AnalyzeResult, str]:
    """Send a local PDF to Azure Document Intelligence and wait synchronously.

    This mirrors the production DocInt request:

    - model_id: `prebuilt-layout`
    - body: raw PDF bytes
    - content_type: `application/octet-stream`
    - output_content_format: `markdown`
    - output: `["figures"]` so figure metadata/images are available
    """

    pdf_bytes = file.read()

    poller = client.begin_analyze_document(
        model_id="prebuilt-layout",
        body=pdf_bytes,
        content_type="application/octet-stream",
        output_content_format="markdown",
        output=["figures"],
    )

    # Synchronous wait. This is the main blocking Azure call.
    result: AnalyzeResult = poller.result()

    # Needed later to download cropped figure PNG bytes.
    result_id = extract_result_id_from_poller(poller)
    return result, result_id


def download_figure_png(
    client: DocumentIntelligenceClient,
    result_id: str,
    figure_id: str,
) -> bytes:
    """Download one cropped figure PNG from Azure Document Intelligence."""

    stream = client.get_analyze_result_figure(
        model_id="prebuilt-layout",
        result_id=result_id,
        figure_id=figure_id,
    )
    return b"".join(chunk for chunk in stream)


# ---------------------------------------------------------------------------
# Azure response -> typed intermediate artifacts
# ---------------------------------------------------------------------------


def parse_pages(result: AnalyzeResult) -> list[AzurePageMeta]:
    """Normalize Azure `DocumentPage` SDK objects.

    We intentionally read from `result.pages` instead of `result.as_dict()`.
    """

    pages: list[AzurePageMeta] = []
    for page in result.pages or []:
        page_sdk: DocumentPage = page
        pages.append(
            AzurePageMeta(
                pageNumber=int(page_sdk.page_number),
                width=(
                    float(page_sdk.width)
                    if page_sdk.width is not None
                    else None
                ),
                height=(
                    float(page_sdk.height)
                    if page_sdk.height is not None
                    else None
                ),
                unit=page_sdk.unit,
            )
        )
    return pages


def parse_bounding_regions(
    regions_sdk: list[BoundingRegion] | None,
) -> list[AzureBoundingRegion]:
    """Normalize Azure `BoundingRegion` SDK objects.

    The SDK object has snake_case attributes (`page_number`, `polygon`), while
    Azure JSON uses camelCase (`pageNumber`). The app's final viewer boxes do
    not care about either original spelling; they only need page and polygon.
    """

    regions: list[AzureBoundingRegion] = []
    for region in regions_sdk or []:
        regions.append(
            AzureBoundingRegion(
                pageNumber=int(region.page_number),
                polygon=[float(value) for value in region.polygon],
            )
        )
    return regions


def extract_tables(result: AnalyzeResult) -> list[RawDocIntTable]:
    """Extract table markdown and table bounding regions from Azure SDK types."""

    # Azure returns the document content as markdown because we requested
    # `output_content_format="markdown"`.
    markdown_content = result.content or ""

    # 1. Extract HTML table blocks from Azure markdown.
    # 2. Convert those HTML tables to GitHub-flavored markdown.
    html_tables = extract_html_tables_from_markdown(markdown_content)
    markdown_tables = [html_table_to_markdown(html) for html in html_tables]

    # Bounding regions come from Azure `DocumentTable.bounding_regions`.
    sdk_tables: list[DocumentTable] = list(result.tables or [])

    tables: list[RawDocIntTable] = []
    for index, table_markdown in enumerate(markdown_tables, start=1):
        sdk_table = (
            sdk_tables[index - 1] if index - 1 < len(sdk_tables) else None
        )

        tables.append(
            RawDocIntTable(
                index=index,
                caption=None,
                bounding_regions=parse_bounding_regions(
                    sdk_table.bounding_regions if sdk_table else []
                ),
                table_markdown=table_markdown,
            )
        )

    return tables


def extract_figures(
    client: DocumentIntelligenceClient,
    result: AnalyzeResult,
    result_id: str,
) -> list[RawDocIntFigure]:
    """Extract figure metadata, bounding regions, captions, and PNG bytes."""

    figures: list[RawDocIntFigure] = []

    # Azure `DocumentFigure` objects expose caption and bounding region fields
    # directly, so no `as_dict()` conversion is needed.
    sdk_figures: list[DocumentFigure] = list(result.figures or [])
    for index, figure in enumerate(sdk_figures, start=1):
        azure_id = figure.id or f"unknown_{index}"

        # Caption is optional. Azure provides it as a nested object with content.
        caption = figure.caption.content if figure.caption else None

        bounding_regions = parse_bounding_regions(
            figure.bounding_regions or []
        )

        # Production downloads the figure bytes and uploads them to app storage.
        png_bytes = download_figure_png(client, result_id, azure_id)

        figures.append(
            RawDocIntFigure(
                index=index,
                azure_id=azure_id,
                caption=caption,
                bounding_regions=bounding_regions,
                png_bytes=png_bytes,
            )
        )

    return figures


# ---------------------------------------------------------------------------
# Intermediate artifacts -> final port-friendly format
# ---------------------------------------------------------------------------


def convert_to_app_result(
    *,
    pages: list[AzurePageMeta],
    figures: list[RawDocIntFigure],
    tables: list[RawDocIntTable],
) -> FigureExtractionResultData:
    """Convert DocInt artifacts into final app output.

    Pages are accepted here only because Azure table/figure polygons need page
    units for normalization. They are not returned. In your target app, keep
    using GROBID page metadata for the PDF viewer if that is your source of
    truth.
    """

    final_figures: list[ExtractedFigure] = []
    final_tables: list[ExtractedTable] = []

    # -------------------------
    # Figures -> app artifacts
    # -------------------------
    for figure in figures:
        # Production storage path for the cropped figure PNG.

        # Convert Azure polygons into the viewer rectangle boxes the app stores.
        boxes = normalize_bounding_regions_to_boxes(
            figure.bounding_regions, pages
        )

        image = None
        if figure.png_bytes:
            image = FigureImage(
                png_bytes=figure.png_bytes,
            )

        final_figures.append(
            ExtractedFigure(
                index=figure.index,
                provider_id=figure.azure_id,
                caption=figure.caption,
                coordinates=boxes,
                image=image,
            )
        )

    # -----------------------
    # Tables -> app artifacts
    # -----------------------
    for table in tables:
        boxes = normalize_bounding_regions_to_boxes(
            table.bounding_regions, pages
        )

        final_tables.append(
            ExtractedTable(
                index=table.index,
                caption=table.caption,
                markdown=table.table_markdown,
                coordinates=boxes,
            )
        )

    return FigureExtractionResultData(
        figures=final_figures,
        tables=final_tables,
    )


def process_pdf_with_docint(
    *,
    file: Any,
    client: DocumentIntelligenceClient,
) -> FigureExtractionResultData:
    """One-call happy-path example: PDF -> DocInt -> final typed result.

    Returns:
        FigureExtractionResultData:
            Nicely typed end result containing just figures and tables.
    """

    # 1. Send raw PDF bytes to Azure Document Intelligence.
    result, result_id = analyze_pdf(client=client, file=file)

    # 2. Pull page metadata used for polygon normalization.
    #    This reads Azure `DocumentPage` SDK objects directly.
    pages = parse_pages(result)

    # 3. Extract table artifacts from Azure markdown + Azure `DocumentTable`
    #    SDK objects.
    tables = extract_tables(result)

    # 4. Extract figure artifacts from Azure `DocumentFigure` SDK objects plus
    #    the figure PNG download API.
    figures = extract_figures(client, result, result_id)

    # 5. Convert intermediate DocInt artifacts into the final shapes the app
    #    should persist or pass to downstream LLM/UI code.
    return convert_to_app_result(
        pages=pages,
        figures=figures,
        tables=tables,
    )
