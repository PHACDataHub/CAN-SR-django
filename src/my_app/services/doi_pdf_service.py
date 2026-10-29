"""Resolve DOI locations and attach a verified PDF to a pending request."""

import ipaddress
import json
import re
import socket
import tempfile
import time
import uuid
from contextlib import contextmanager
from itertools import islice
from urllib.parse import quote, unquote, urljoin, urlsplit

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.utils import timezone

import requests
from bs4 import BeautifulSoup

from proj.util import MissingPreconditionError

from my_app.models import (
    Citation,
    Document,
    DocumentFigure,
    DocumentTable,
    FigureExtractionResult,
    L1CriticalScreeningResult,
    L1ScreeningResult,
    L2CriticalScreeningResult,
    L2ScreeningResult,
    ParameterExtractionResult,
    PdfFromDOIRequest,
    TextExtractionResult,
)
from shortcuts import logger

PDF_FROM_DOI_MAX_RETRIES = 3
PDF_FROM_DOI_MAX_BYTES = 50 * 1024 * 1024
PDF_FROM_DOI_TIMEOUT = (10, 30)
PDF_FROM_DOI_MAX_SECONDS = 120


class DoiPdfError(Exception):
    pass


class DoiPdfConfigurationError(DoiPdfError):
    pass


class PendingDocumentProcessingError(MissingPreconditionError):
    pass


class PdfFromDOIAlreadyPendingError(MissingPreconditionError):
    pass


def ensure_no_pending_processing(citation):
    queries = [
        model.objects.filter(citation=citation, status="pending")
        for model in (
            L1ScreeningResult,
            L2ScreeningResult,
            ParameterExtractionResult,
        )
    ]
    queries.extend(
        model.objects.filter(
            initial_result__citation=citation, status="pending"
        )
        for model in (L1CriticalScreeningResult, L2CriticalScreeningResult)
    )
    if citation.document_id:
        queries.extend(
            model.objects.filter(
                document_id=citation.document_id, status="pending"
            )
            for model in (TextExtractionResult, FigureExtractionResult)
        )
    if any(query.exists() for query in queries):
        raise PendingDocumentProcessingError(
            "Wait for pending document extraction and AI processing to finish "
            "before replacing the PDF."
        )


def normalize_doi(value):
    doi = value.strip()
    if doi.lower().startswith(("http://", "https://")):
        parsed = urlsplit(doi)
        if parsed.hostname not in {"doi.org", "dx.doi.org", "www.doi.org"}:
            raise DoiPdfError("Expected a DOI or a doi.org URL.")
        doi = unquote(parsed.path.lstrip("/"))
    elif doi.lower().startswith("doi:"):
        doi = doi[4:].strip()
    if not re.fullmatch(r"10\.\d{4,9}/\S+", doi, flags=re.IGNORECASE):
        raise DoiPdfError("The citation does not have a valid DOI.")
    return doi.lower()


def validate_public_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 80, 443}
    ):
        raise DoiPdfError("PDF locations must be public HTTP(S) URLs.")
    addresses = socket.getaddrinfo(
        parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
    )
    if not addresses or any(
        not ipaddress.ip_address(address[4][0]).is_global
        for address in addresses
    ):
        raise DoiPdfError("PDF locations must not point to private networks.")


def get_public_response(url, *, params=None):
    """Validate every redirect before making a bounded, streaming request."""
    for _ in range(6):
        try:
            validate_public_url(url)
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": "EvidenceSynthesis-DoiPdf/1.0"},
                timeout=PDF_FROM_DOI_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
        except (requests.RequestException, OSError, ValueError) as exc:
            raise DoiPdfError(
                f"Could not reach {urlsplit(url).hostname}: {type(exc).__name__}."
            ) from exc
        params = None
        if response.is_redirect:
            target = response.headers.get("Location")
            response.close()
            if not target:
                raise DoiPdfError("PDF location returned an empty redirect.")
            url = urljoin(url, target)
            continue
        if response.status_code != 200:
            response.close()
            raise DoiPdfError(
                f"{urlsplit(url).hostname} returned HTTP {response.status_code}."
            )
        return response
    raise DoiPdfError("PDF location returned too many redirects.")


def read_response(response, output, *, max_bytes):
    size = 0
    started = time.monotonic()
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise DoiPdfError(
                    "The response exceeds the download size limit."
                )
            if time.monotonic() - started > PDF_FROM_DOI_MAX_SECONDS:
                raise DoiPdfError("The download exceeded its time limit.")
            output.write(chunk)
    except requests.RequestException as exc:
        raise DoiPdfError("The download was interrupted.") from exc
    output.seek(0)


class UnpaywallClient:
    """Prefer Unpaywall's best location, then published publisher copies."""

    def get_locations(self, doi):
        email = settings.UNPAYWALL_EMAIL
        if not email or not email.strip():
            raise DoiPdfConfigurationError(
                "UNPAYWALL_EMAIL must be set to a contact email."
            )
        url = "https://api.unpaywall.org/v2/" + quote(
            normalize_doi(doi), safe="/"
        )
        with get_public_response(url, params={"email": email}) as response:
            with tempfile.SpooledTemporaryFile(
                max_size=1024 * 1024
            ) as content:
                read_response(response, content, max_bytes=2 * 1024 * 1024)
                try:
                    payload = json.load(content)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise DoiPdfError(
                        "Unpaywall returned invalid JSON."
                    ) from exc
        if not isinstance(payload, dict):
            raise DoiPdfError("Unpaywall returned an invalid response.")
        best = payload.get("best_oa_location")
        locations = sorted(
            payload.get("oa_locations") or [], key=self.location_rank
        )
        if best:
            locations.insert(0, best)
        return locations

    @staticmethod
    def location_rank(location):
        versions = {
            "publishedVersion": 0,
            "acceptedVersion": 1,
            "submittedVersion": 2,
        }
        return (
            location.get("host_type") != "publisher",
            versions.get(location.get("version"), 3),
        )

    def iter_pdf_urls(self, doi):
        locations = self.get_locations(doi)
        seen = set()
        for location in locations:
            url = location.get("url_for_pdf")
            if url and url not in seen:
                seen.add(url)
                yield url
        landing_pages = dict.fromkeys(
            location.get("url_for_landing_page")
            for location in locations
            if location.get("url_for_landing_page")
        )
        for page in islice(landing_pages, PDF_FROM_DOI_MAX_RETRIES):
            try:
                url = self.get_landing_page_pdf_url(page)
            except DoiPdfError as exc:
                logger.info("DOI PDF landing page failed: %s", exc)
                continue
            if url and url not in seen:
                seen.add(url)
                yield url

    @staticmethod
    def get_landing_page_pdf_url(page):
        with get_public_response(page) as response:
            with tempfile.SpooledTemporaryFile(
                max_size=1024 * 1024
            ) as content:
                read_response(response, content, max_bytes=2 * 1024 * 1024)
                soup = BeautifulSoup(content.read(), "html.parser")
            metadata = soup.find("meta", attrs={"name": "citation_pdf_url"})
            if metadata and metadata.get("content"):
                return urljoin(response.url, metadata["content"])
        return None


@contextmanager
def download_pdf(url):
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as content:
        with get_public_response(url) as response:
            read_response(response, content, max_bytes=PDF_FROM_DOI_MAX_BYTES)
        header = content.read(1024)
        if not header.lstrip().startswith(b"%PDF-"):
            raise DoiPdfError("The URL did not return a PDF file.")
        content.seek(0)
        yield content


def delete_stored_file(storage, name):
    try:
        storage.delete(name)
    except Exception:
        logger.exception("Could not delete replaced DOI PDF file %s", name)


class QueueDoiPdfService:
    """Reset one request per citation and dispatch its task after commit."""

    def __init__(self, citation: Citation, *, requesting_user=None):
        self.citation = citation
        self.requesting_user = requesting_user

    def perform(self):
        with transaction.atomic():
            citation = Citation.objects.select_for_update().get(
                pk=self.citation.pk
            )
            normalize_doi(citation.doi)
            result = (
                PdfFromDOIRequest.objects.select_for_update()
                .filter(citation=citation)
                .first()
            )
            if result is None:
                result = PdfFromDOIRequest(citation=citation)
            elif result.status == result.Status.PENDING:
                raise PdfFromDOIAlreadyPendingError(
                    "A PDF request is already pending for this citation."
                )
            result.status = result.Status.PENDING
            result.selected_url = None
            result.requesting_user = self.requesting_user
            result.request_dt = timezone.now()
            result.run_id = uuid.uuid4()
            result.error = ""
            result.save()
            request_id = result.pk
            run_id = str(result.run_id)
            transaction.on_commit(lambda: self.enqueue(request_id, run_id))
        return result

    @staticmethod
    def enqueue(request_id, run_id):
        from my_app.tasks.doi_pdf_task import process_doi_pdf_request

        try:
            process_doi_pdf_request.enqueue(
                request_id=request_id, run_id=run_id
            )
        except Exception as exc:
            PdfFromDOIRequest.objects.filter(
                pk=request_id,
                run_id=run_id,
                status=PdfFromDOIRequest.Status.PENDING,
            ).update(
                status=PdfFromDOIRequest.Status.FAILED,
                error=f"Could not enqueue the PDF request: {exc}",
                updated_dt=timezone.now(),
            )
            raise


class DoiPdfService:
    """Download first, then lock and replace the citation's document."""

    def __init__(self, citation: Citation, *, run_id=None):
        self.citation = citation
        self.run_id = run_id

    def perform(self):
        result = PdfFromDOIRequest.objects.get(citation=self.citation)
        if self.run_id is None:
            self.run_id = result.run_id
        self.run_id = str(self.run_id)
        self.result_id = result.pk
        if not self.pending_requests().exists():
            return result
        initial_document_id = self.citation.document_id
        try:
            ensure_no_pending_processing(self.citation)
            urls = UnpaywallClient().iter_pdf_urls(self.citation.doi)
            last_error = "No open-access PDF URL was found for this DOI."
            for url in islice(urls, PDF_FROM_DOI_MAX_RETRIES):
                if not self.pending_requests().update(
                    selected_url=url, updated_dt=timezone.now()
                ):
                    break
                try:
                    with download_pdf(url) as content:
                        self.save_document(content, url, initial_document_id)
                    break
                except DoiPdfError as exc:
                    last_error = str(exc)
                    logger.info("DOI PDF candidate failed: %s", last_error)
            else:
                raise DoiPdfError(last_error)
        except Exception as exc:
            self.mark_failed(str(exc))
            raise
        result.refresh_from_db()
        return result

    def pending_requests(self):
        return PdfFromDOIRequest.objects.filter(
            pk=self.result_id,
            run_id=self.run_id,
            status=PdfFromDOIRequest.Status.PENDING,
        )

    def mark_failed(self, error):
        self.pending_requests().update(
            status=PdfFromDOIRequest.Status.FAILED,
            error=error,
            updated_dt=timezone.now(),
        )

    def save_document(self, content, url, initial_document_id):
        saved_file = None
        try:
            with transaction.atomic():
                citation = Citation.objects.select_for_update().get(
                    pk=self.citation.pk
                )
                result = PdfFromDOIRequest.objects.select_for_update().get(
                    pk=self.result_id
                )
                if (
                    str(result.run_id) != self.run_id
                    or result.status != result.Status.PENDING
                ):
                    return
                if citation.document_id != initial_document_id:
                    result.status = result.Status.CANCELED
                    result.error = "The attached document changed."
                    result.save(
                        update_fields=["status", "error", "updated_dt"]
                    )
                    return
                document = Document()
                if citation.document_id:
                    document = Document.objects.select_for_update().get(
                        pk=citation.document_id
                    )
                    if document.citations.exclude(pk=citation.pk).exists():
                        raise MissingPreconditionError(
                            "Cannot replace a document shared by multiple citations."
                        )
                ensure_no_pending_processing(citation)
                old_file = document.file.name
                document.file.save(
                    f"citation-{citation.pk}-{uuid.uuid4().hex}.pdf",
                    File(content),
                    save=False,
                )
                saved_file = (document.file.storage, document.file.name)
                document.uploaded_at = timezone.now()
                document.save()
                citation.document = document
                citation.save(update_fields=["document"])
                self.clear_downstream_results(citation, document)
                result.selected_url = url
                result.status = result.Status.FULFILLED
                result.error = ""
                result.save()
                if old_file:
                    transaction.on_commit(
                        lambda: delete_stored_file(
                            document.file.storage, old_file
                        )
                    )
        except Exception:
            if saved_file:
                delete_stored_file(*saved_file)
            raise

    @staticmethod
    def clear_downstream_results(citation, document):
        for figure in DocumentFigure.objects.filter(document=document):
            if figure.file.name:
                storage, name = figure.file.storage, figure.file.name
                transaction.on_commit(
                    lambda storage=storage, name=name: delete_stored_file(
                        storage, name
                    )
                )
        for model in (
            TextExtractionResult,
            FigureExtractionResult,
            DocumentFigure,
            DocumentTable,
        ):
            model.objects.filter(document=document).delete()
        for model in (
            L1ScreeningResult,
            L2ScreeningResult,
            ParameterExtractionResult,
        ):
            model.objects.filter(citation=citation).delete()
