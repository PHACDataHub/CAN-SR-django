"""Resolve DOI locations and attach a verified PDF to a pending request."""

import ipaddress
import json
import logging
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
from shortcuts import logger, tdt

# Maximum distinct PDF download attempts per provider.
PDF_FROM_DOI_MAX_RETRIES = 3
PDF_FROM_DOI_MAX_BYTES = 50 * 1024 * 1024
PDF_FROM_DOI_TIMEOUT = (10, 30)
PDF_FROM_DOI_MAX_SECONDS = 120


def redact_doi_pdf_error(error):
    message = re.sub(
        r"\?(?!<redacted>)[^\s'\"<>)]*", "?<redacted>", str(error)
    )
    return re.sub(r"(https?://)[^/\s@]+@", r"\1<redacted>@", message)


def log_doi_pdf_event(event, *, level=logging.INFO, exc_info=False, **details):
    # Publisher URLs may contain signed query parameters; keep these out of logs.
    for key, value in details.items():
        if key.endswith("url") and value:
            try:
                parsed = urlsplit(value)
                details[key] = (
                    f"{parsed.scheme}://{parsed.hostname}{parsed.path}"
                )
            except (TypeError, ValueError):
                details[key] = "<invalid URL>"
        elif key == "error" and isinstance(value, str):
            # Requests exceptions can embed query parameters and URL credentials.
            details[key] = redact_doi_pdf_error(value)
    fields = " ".join(f"{key}={value!r}" for key, value in details.items())
    logger.log(level, "doi_pdf.%s %s", event, fields, exc_info=exc_info)


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
    for query in queries:
        result_id = query.values_list("pk", flat=True).first()
        if result_id is not None:
            log_doi_pdf_event(
                "processing_pending",
                level=logging.WARNING,
                citation_id=citation.pk,
                document_id=citation.document_id,
                model=query.model.__name__,
                processing_result_id=result_id,
            )
            raise PendingDocumentProcessingError(
                "Wait for pending document extraction and AI processing to finish "
                "before replacing the PDF."
            )


def normalize_doi(value):
    doi = value.strip()
    if doi.lower().startswith(("doi.org/", "dx.doi.org/", "www.doi.org/")):
        doi = f"https://{doi}"
    if doi.lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(doi)
        except ValueError:
            log_doi_pdf_event("doi_url_invalid", level=logging.WARNING)
            raise
        if parsed.hostname not in {"doi.org", "dx.doi.org", "www.doi.org"}:
            log_doi_pdf_event("doi_host_invalid", level=logging.WARNING)
            raise DoiPdfError("Expected a DOI or a doi.org URL.")
        doi = unquote(parsed.path.lstrip("/"))
    elif doi.lower().startswith("doi:"):
        doi = doi[4:].strip()
    if not re.fullmatch(r"10\.\d{4,9}/\S+", doi, flags=re.IGNORECASE):
        log_doi_pdf_event("doi_format_invalid", level=logging.WARNING, doi=doi)
        raise DoiPdfError("The citation does not have a valid DOI.")
    return doi.lower()


def validate_public_url(url):
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in {"https", "http"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and parsed.port in {None, 80, 443}
        )
    except ValueError:
        valid = False
    if not valid:
        log_doi_pdf_event("url_invalid", level=logging.WARNING, url=url)
        raise DoiPdfError("PDF locations must be public HTTP(S) URLs.")
    try:
        addresses = socket.getaddrinfo(
            parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        log_doi_pdf_event(
            "dns_failed", level=logging.WARNING, url=url, error=str(exc)
        )
        raise
    if not addresses or any(
        not ipaddress.ip_address(address[4][0]).is_global
        for address in addresses
    ):
        log_doi_pdf_event(
            "url_private_network",
            level=logging.WARNING,
            url=url,
            resolved_addresses=[address[4][0] for address in addresses],
        )
        raise DoiPdfError("PDF locations must not point to private networks.")


def get_public_response(url, *, params=None):
    """Validate every redirect before making a bounded, streaming request."""
    for redirect_count in range(6):
        try:
            validate_public_url(url)
            log_doi_pdf_event(
                "http_started", url=url, redirects=redirect_count
            )
            response = requests.get(
                url,
                params=params,
                headers=doi_pdf_request_headers(url),
                timeout=PDF_FROM_DOI_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
        except (requests.RequestException, OSError, ValueError) as exc:
            event = "http_request_failed"
            if isinstance(exc, requests.Timeout):
                event = "http_timeout"
            elif isinstance(exc, requests.exceptions.SSLError):
                event = "http_tls_failed"
            elif isinstance(exc, requests.exceptions.ProxyError):
                event = "http_proxy_failed"
            elif isinstance(exc, requests.ConnectionError):
                event = "http_connection_failed"
            log_doi_pdf_event(
                event,
                level=logging.WARNING,
                url=url,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise DoiPdfError(
                f"Could not reach {urlsplit(url).hostname}: "
                f"{type(exc).__name__}: {redact_doi_pdf_error(exc)}"
            ) from exc
        params = None
        if response.is_redirect:
            target = response.headers.get("Location")
            response.close()
            if not target:
                log_doi_pdf_event(
                    "redirect_empty", level=logging.WARNING, url=url
                )
                raise DoiPdfError("PDF location returned an empty redirect.")
            try:
                next_url = urljoin(url, target)
            except ValueError:
                log_doi_pdf_event(
                    "redirect_invalid", level=logging.WARNING, url=url
                )
                raise
            log_doi_pdf_event("http_redirected", url=url, target_url=next_url)
            url = next_url
            continue
        if response.status_code != 200:
            log_doi_pdf_event(
                "http_status_failed",
                level=logging.WARNING,
                url=url,
                status=response.status_code,
                content_type=response.headers.get("Content-Type"),
            )
            response.close()
            raise DoiPdfError(
                f"{urlsplit(url).hostname} returned HTTP {response.status_code}."
            )
        log_doi_pdf_event(
            "http_succeeded",
            url=url,
            status=response.status_code,
            content_type=response.headers.get("Content-Type"),
        )
        return response
    log_doi_pdf_event(
        "redirect_limit_exceeded", level=logging.WARNING, url=url
    )
    raise DoiPdfError("PDF location returned too many redirects.")


def doi_pdf_request_headers(url):
    headers = {"User-Agent": "EvidenceSynthesis-DoiPdf/1.0"}
    parsed = urlsplit(url)
    key = (settings.OPENALEX_API_KEY or "").strip()
    if (
        key
        and parsed.scheme == "https"
        and parsed.hostname in {"api.openalex.org", "content.openalex.org"}
        and parsed.port in {None, 443}
    ):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def read_response(response, output, *, max_bytes):
    size = 0
    started = time.monotonic()
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                log_doi_pdf_event(
                    "response_too_large",
                    level=logging.WARNING,
                    url=response.url,
                    bytes_read=size,
                    max_bytes=max_bytes,
                )
                raise DoiPdfError(
                    "The response exceeds the download size limit."
                )
            if time.monotonic() - started > PDF_FROM_DOI_MAX_SECONDS:
                log_doi_pdf_event(
                    "response_time_limit_exceeded",
                    level=logging.WARNING,
                    url=response.url,
                    bytes_read=size,
                    max_seconds=PDF_FROM_DOI_MAX_SECONDS,
                )
                raise DoiPdfError("The download exceeded its time limit.")
            output.write(chunk)
    except requests.RequestException as exc:
        log_doi_pdf_event(
            "response_interrupted",
            level=logging.WARNING,
            url=response.url,
            bytes_read=size,
            error_type=type(exc).__name__,
        )
        raise DoiPdfError("The download was interrupted.") from exc
    output.seek(0)
    log_doi_pdf_event("response_read", url=response.url, bytes_read=size)


class UnpaywallClient:
    """Prefer Unpaywall's best location, then published publisher copies."""

    def get_locations(self, doi):
        email = settings.UNPAYWALL_EMAIL
        if not email or not email.strip():
            log_doi_pdf_event("unpaywall_email_missing", level=logging.ERROR)
            raise DoiPdfConfigurationError(
                "UNPAYWALL_EMAIL must be set to a contact email."
            )
        url = "https://api.unpaywall.org/v2/" + quote(
            normalize_doi(doi), safe="/"
        )
        log_doi_pdf_event("unpaywall_lookup_started", doi=doi)
        with get_public_response(url, params={"email": email}) as response:
            with tempfile.SpooledTemporaryFile(
                max_size=1024 * 1024
            ) as content:
                read_response(response, content, max_bytes=2 * 1024 * 1024)
                try:
                    payload = json.load(content)
                except (ValueError, UnicodeDecodeError) as exc:
                    log_doi_pdf_event(
                        "unpaywall_json_invalid", level=logging.ERROR, doi=doi
                    )
                    raise DoiPdfError(
                        "Unpaywall returned invalid JSON."
                    ) from exc
        if not isinstance(payload, dict):
            log_doi_pdf_event(
                "unpaywall_response_invalid", level=logging.ERROR, doi=doi
            )
            raise DoiPdfError("Unpaywall returned an invalid response.")
        best = payload.get("best_oa_location")
        locations = payload.get("oa_locations") or []
        if (
            not isinstance(locations, list)
            or any(not isinstance(location, dict) for location in locations)
            or (best is not None and not isinstance(best, dict))
        ):
            log_doi_pdf_event(
                "unpaywall_locations_invalid", level=logging.ERROR, doi=doi
            )
            raise DoiPdfError("Unpaywall returned invalid PDF locations.")
        locations = sorted(locations, key=self.location_rank)
        if best:
            locations.insert(0, best)
        log_doi_pdf_event(
            "unpaywall_lookup_finished",
            doi=doi,
            is_oa=payload.get("is_oa"),
            oa_status=payload.get("oa_status"),
            locations=len(locations),
            pdf_locations=sum(
                bool(location.get("url_for_pdf")) for location in locations
            ),
        )
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
                log_doi_pdf_event(
                    "pdf_candidate_found", source="unpaywall", url=url, doi=doi
                )
                yield url
        landing_pages = dict.fromkeys(
            location.get("url_for_landing_page")
            for location in locations
            if location.get("url_for_landing_page")
        )
        for page in islice(landing_pages, PDF_FROM_DOI_MAX_RETRIES):
            try:
                log_doi_pdf_event("landing_lookup_started", url=page, doi=doi)
                url = self.get_landing_page_pdf_url(page)
            except DoiPdfError as exc:
                log_doi_pdf_event(
                    "landing_lookup_failed",
                    level=logging.WARNING,
                    url=page,
                    doi=doi,
                    error=str(exc),
                )
                continue
            if url and url not in seen:
                seen.add(url)
                log_doi_pdf_event(
                    "pdf_candidate_found",
                    source="landing_metadata",
                    url=url,
                    doi=doi,
                )
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
            log_doi_pdf_event(
                "landing_pdf_metadata_missing",
                level=logging.WARNING,
                url=page,
                content_type=response.headers.get("Content-Type"),
            )
        return None


class OpenAlexClient:
    """Prefer OpenAlex's cached PDF, followed by its open-access locations."""

    def iter_pdf_urls(self, doi):
        if not (settings.OPENALEX_API_KEY or "").strip():
            log_doi_pdf_event("openalex_key_missing", level=logging.ERROR)
            raise DoiPdfConfigurationError(
                tdt(
                    "OPENALEX_API_KEY must be set to enable OpenAlex PDF downloads."
                )
            )
        doi = normalize_doi(doi)
        url = "https://api.openalex.org/works/https://doi.org/" + quote(
            doi, safe="/"
        )
        log_doi_pdf_event("openalex_lookup_started", doi=doi)
        with get_public_response(url) as response:
            with tempfile.SpooledTemporaryFile(
                max_size=1024 * 1024
            ) as content:
                read_response(response, content, max_bytes=2 * 1024 * 1024)
                try:
                    work = json.load(content)
                except (ValueError, UnicodeDecodeError) as exc:
                    log_doi_pdf_event(
                        "openalex_json_invalid", level=logging.ERROR, doi=doi
                    )
                    raise DoiPdfError(
                        tdt("OpenAlex returned invalid JSON.")
                    ) from exc
        if not isinstance(work, dict) or not isinstance(
            work.get("has_content") or {}, dict
        ):
            log_doi_pdf_event(
                "openalex_response_invalid", level=logging.ERROR, doi=doi
            )
            raise DoiPdfError(tdt("OpenAlex returned an invalid response."))
        has_pdf = (work.get("has_content") or {}).get("pdf", False)
        log_doi_pdf_event(
            "openalex_lookup_finished", doi=doi, has_cached_pdf=has_pdf
        )
        seen = set()
        if has_pdf:
            work_id = str(work.get("id", "")).rsplit("/", 1)[-1]
            if not re.fullmatch(r"W\d+", work_id):
                log_doi_pdf_event(
                    "openalex_work_id_invalid", level=logging.ERROR, doi=doi
                )
                raise DoiPdfError(
                    tdt("OpenAlex returned an invalid work identifier.")
                )
            # Keep the key in request headers, never in selected_url or log URLs.
            cached_url = f"https://content.openalex.org/works/{work_id}.pdf"
            seen.add(cached_url)
            log_doi_pdf_event(
                "pdf_candidate_found",
                source="openalex_cached",
                doi=doi,
                url=cached_url,
            )
            yield cached_url

        locations = work.get("locations") or []
        best = work.get("best_oa_location")
        if (
            not isinstance(locations, list)
            or any(not isinstance(location, dict) for location in locations)
            or (best is not None and not isinstance(best, dict))
        ):
            log_doi_pdf_event(
                "openalex_locations_invalid", level=logging.ERROR, doi=doi
            )
            raise DoiPdfError(tdt("OpenAlex returned invalid PDF locations."))
        if best:
            locations = [best, *locations]
        for location in locations:
            url = location.get("pdf_url")
            if location.get("is_oa") and url and url not in seen:
                seen.add(url)
                log_doi_pdf_event(
                    "pdf_candidate_found",
                    source="openalex_location",
                    doi=doi,
                    url=url,
                )
                yield url


def iter_doi_pdf_urls(doi, *, provider="auto"):
    """Try each provider in order, with a separate budget and shared deduplication."""
    clients = []
    if provider in {"auto", "unpaywall"}:
        clients.append(("unpaywall", UnpaywallClient()))
    if provider == "openalex" or (
        provider == "auto" and (settings.OPENALEX_API_KEY or "").strip()
    ):
        clients.append(("openalex", OpenAlexClient()))
    elif provider == "auto":
        log_doi_pdf_event(
            "openalex_disabled", reason="OPENALEX_API_KEY is not set"
        )
    if not clients:
        raise ValueError("Unknown DOI PDF provider.")

    seen = set()
    errors = []
    for name, client in clients:
        attempts = 0
        try:
            log_doi_pdf_event(
                "provider_lookup_started", provider=name, doi=doi
            )
            for url in client.iter_pdf_urls(doi):
                if url in seen:
                    log_doi_pdf_event(
                        "duplicate_candidate_skipped", provider=name, url=url
                    )
                    continue
                seen.add(url)
                attempts += 1
                log_doi_pdf_event(
                    "provider_candidate_selected",
                    provider=name,
                    url=url,
                    attempt=attempts,
                    max_attempts=PDF_FROM_DOI_MAX_RETRIES,
                )
                yield url
                if attempts >= PDF_FROM_DOI_MAX_RETRIES:
                    log_doi_pdf_event(
                        "provider_attempts_exhausted", provider=name, doi=doi
                    )
                    break
            else:
                log_doi_pdf_event("provider_exhausted", provider=name, doi=doi)
        except DoiPdfError as exc:
            errors.append(exc)
            log_doi_pdf_event(
                "provider_lookup_failed",
                level=logging.WARNING,
                provider=name,
                doi=doi,
                error=str(exc),
            )
    if not seen and errors:
        raise errors[-1]


@contextmanager
def download_pdf(url):
    log_doi_pdf_event("download_started", url=url)
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as content:
        with get_public_response(url) as response:
            read_response(response, content, max_bytes=PDF_FROM_DOI_MAX_BYTES)
        header = content.read(1024)
        if not header.lstrip().startswith(b"%PDF-"):
            log_doi_pdf_event(
                "download_not_pdf",
                level=logging.WARNING,
                url=url,
                content_type=response.headers.get("Content-Type"),
            )
            raise DoiPdfError(
                tdt(
                    "The URL at {host} did not return a PDF file (content type: {content_type})."
                ).format(
                    host=urlsplit(url).hostname,
                    content_type=response.headers.get("Content-Type")
                    or tdt("unknown"),
                )
            )
        content.seek(0)
        log_doi_pdf_event("download_verified", url=url)
        yield content


def delete_stored_file(storage, name, *, reason="replaced_pdf"):
    try:
        storage.delete(name)
        log_doi_pdf_event(f"{reason}_cleanup_finished", filename=name)
    except Exception:
        log_doi_pdf_event(
            f"{reason}_cleanup_failed",
            level=logging.ERROR,
            exc_info=True,
            filename=name,
        )


class QueueDoiPdfService:
    """Reset one request per citation and dispatch its task after commit."""

    def __init__(self, citation: Citation, *, requesting_user=None):
        self.citation = citation
        self.requesting_user = requesting_user

    def perform(self):
        context = {"citation_id": self.citation.pk}
        log_doi_pdf_event(
            "queue_started",
            **context,
            requesting_user_id=getattr(self.requesting_user, "pk", None),
        )
        stage = "lock_citation"
        try:
            with transaction.atomic():
                citation = Citation.objects.select_for_update().get(
                    pk=self.citation.pk
                )
                stage = "validate_doi"
                normalize_doi(citation.doi)
                stage = "load_request"
                result = (
                    PdfFromDOIRequest.objects.select_for_update()
                    .filter(citation=citation)
                    .first()
                )
                if result is None:
                    result = PdfFromDOIRequest(citation=citation)
                elif result.status == result.Status.PENDING:
                    log_doi_pdf_event(
                        "queue_already_pending",
                        level=logging.WARNING,
                        **context,
                        request_id=result.pk,
                        run_id=str(result.run_id),
                    )
                    raise PdfFromDOIAlreadyPendingError(
                        "A PDF request is already pending for this citation."
                    )
                result.status = result.Status.PENDING
                result.selected_url = None
                result.requesting_user = self.requesting_user
                result.request_dt = timezone.now()
                result.run_id = uuid.uuid4()
                result.error = ""
                stage = "save_request"
                result.save()
                request_id = result.pk
                run_id = str(result.run_id)
                context.update(request_id=request_id, run_id=run_id)
                log_doi_pdf_event("queue_request_saved", **context)
                stage = "register_dispatch"
                transaction.on_commit(lambda: self.enqueue(request_id, run_id))
                stage = "commit"
        except PdfFromDOIAlreadyPendingError:
            raise
        except Exception as exc:
            log_doi_pdf_event(
                f"queue_{stage}_failed",
                level=logging.ERROR,
                exc_info=not isinstance(exc, (DoiPdfError, ValueError)),
                **context,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise
        log_doi_pdf_event("queue_finished", **context)
        return result

    @staticmethod
    def enqueue(request_id, run_id):
        context = {"request_id": request_id, "run_id": run_id}
        log_doi_pdf_event("task_enqueue_started", **context)
        stage = "import"
        try:
            from my_app.tasks.doi_pdf_task import process_doi_pdf_request

            stage = "enqueue"
            task_result = process_doi_pdf_request.enqueue(
                request_id=request_id, run_id=run_id
            )
        except Exception as exc:
            log_doi_pdf_event(
                f"task_{stage}_failed",
                level=logging.ERROR,
                exc_info=True,
                **context,
                error=str(exc),
            )
            try:
                updated = PdfFromDOIRequest.objects.filter(
                    pk=request_id,
                    run_id=run_id,
                    status=PdfFromDOIRequest.Status.PENDING,
                ).update(
                    status=PdfFromDOIRequest.Status.FAILED,
                    error=f"Could not enqueue the PDF request: {redact_doi_pdf_error(exc)}",
                    updated_dt=timezone.now(),
                )
                if not updated:
                    log_doi_pdf_event(
                        "enqueue_failure_status_skipped", **context
                    )
            except Exception:
                log_doi_pdf_event(
                    "enqueue_failure_status_save_failed",
                    level=logging.ERROR,
                    exc_info=True,
                    **context,
                )
            raise
        log_doi_pdf_event("task_enqueued", **context, task_id=task_result.id)


class DoiPdfService:
    """Download first, then lock and replace the citation's document."""

    def __init__(self, citation: Citation, *, run_id=None):
        self.citation = citation
        self.run_id = run_id
        self.result_id = None

    def log(self, event, **details):
        log_doi_pdf_event(
            event,
            citation_id=self.citation.pk,
            request_id=self.result_id,
            run_id=str(self.run_id),
            **details,
        )

    def perform(self):
        stage = "load_request"
        self.log("request_started", doi=self.citation.doi)
        try:
            result = PdfFromDOIRequest.objects.get(citation=self.citation)
            if self.run_id is None:
                self.run_id = result.run_id
            self.run_id = str(self.run_id)
            self.result_id = result.pk
            if not self.pending_requests().exists():
                self.log(
                    "request_skipped",
                    status=result.status,
                    current_run_id=str(result.run_id),
                )
                return result
            self.log("request_loaded", doi=self.citation.doi)
            initial_document_id = self.citation.document_id
            stage = "check_processing"
            ensure_no_pending_processing(self.citation)
            stage = "resolve_url"
            urls = iter_doi_pdf_urls(self.citation.doi)
            last_error = "No open-access PDF URL was found for this DOI."
            attempts = 0
            for attempt, url in enumerate(urls, start=1):
                stage = "select_candidate"
                if not self.pending_requests().update(
                    selected_url=url, updated_dt=timezone.now()
                ):
                    self.log(
                        "candidate_skipped_request_not_pending",
                        attempt=attempt,
                        url=url,
                    )
                    break
                attempts = attempt
                self.log(
                    "candidate_selected",
                    attempt=attempt,
                    max_attempts_per_provider=PDF_FROM_DOI_MAX_RETRIES,
                    url=url,
                )
                try:
                    stage = "download_candidate"
                    with download_pdf(url) as content:
                        stage = "attach_document"
                        self.save_document(content, url, initial_document_id)
                    break
                except DoiPdfError as exc:
                    last_error = str(exc)
                    self.log(
                        "candidate_failed",
                        level=logging.WARNING,
                        attempt=attempt,
                        url=url,
                        error=last_error,
                    )
                stage = "resolve_url"
            else:
                event = "no_pdf_candidates"
                if attempts:
                    event = "download_attempts_exhausted"
                self.log(
                    event,
                    level=logging.ERROR,
                    attempts=attempts,
                    max_attempts_per_provider=PDF_FROM_DOI_MAX_RETRIES,
                    error=last_error,
                )
                stage = event
                raise DoiPdfError(last_error)
            stage = "refresh_request"
            result.refresh_from_db()
        except Exception as exc:
            self.log(
                f"request_{stage}_failed",
                level=logging.ERROR,
                exc_info=not isinstance(
                    exc, (DoiPdfError, MissingPreconditionError)
                ),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            if self.result_id is not None:
                try:
                    self.mark_failed(str(exc))
                except Exception:
                    self.log(
                        "failure_status_save_failed",
                        level=logging.ERROR,
                        exc_info=True,
                    )
            raise
        self.log(
            "request_finished",
            status=result.status,
            selected_url=result.selected_url,
        )
        return result

    def pending_requests(self):
        return PdfFromDOIRequest.objects.filter(
            pk=self.result_id,
            run_id=self.run_id,
            status=PdfFromDOIRequest.Status.PENDING,
        )

    def mark_failed(self, error):
        updated = self.pending_requests().update(
            status=PdfFromDOIRequest.Status.FAILED,
            error=redact_doi_pdf_error(error),
            updated_dt=timezone.now(),
        )
        self.log("failure_status_saved", rows_updated=updated, error=error)

    def save_document(self, content, url, initial_document_id):
        saved_file = None
        stage = "lock_citation"
        self.log(
            "attachment_started", url=url, document_id=initial_document_id
        )
        try:
            with transaction.atomic():
                citation = Citation.objects.select_for_update().get(
                    pk=self.citation.pk
                )
                stage = "lock_request"
                result = PdfFromDOIRequest.objects.select_for_update().get(
                    pk=self.result_id
                )
                if (
                    str(result.run_id) != self.run_id
                    or result.status != result.Status.PENDING
                ):
                    self.log(
                        "attachment_skipped",
                        status=result.status,
                        current_run_id=str(result.run_id),
                    )
                    return
                if citation.document_id != initial_document_id:
                    self.log(
                        "attachment_document_changed",
                        level=logging.WARNING,
                        expected_document_id=initial_document_id,
                        current_document_id=citation.document_id,
                    )
                    result.status = result.Status.CANCELED
                    result.error = "The attached document changed."
                    stage = "cancel_request"
                    result.save(
                        update_fields=["status", "error", "updated_dt"]
                    )
                    return
                document = Document()
                if citation.document_id:
                    stage = "lock_document"
                    document = Document.objects.select_for_update().get(
                        pk=citation.document_id
                    )
                    if document.citations.exclude(pk=citation.pk).exists():
                        self.log(
                            "attachment_document_shared",
                            level=logging.WARNING,
                            document_id=document.pk,
                        )
                        raise MissingPreconditionError(
                            "Cannot replace a document shared by multiple citations."
                        )
                stage = "check_processing"
                ensure_no_pending_processing(citation)
                old_file = document.file.name
                stage = "store_file"
                document.file.save(
                    f"citation-{citation.pk}-{uuid.uuid4().hex}.pdf",
                    File(content),
                    save=False,
                )
                saved_file = (document.file.storage, document.file.name)
                self.log("attachment_file_stored", filename=document.file.name)
                document.uploaded_at = timezone.now()
                stage = "save_document"
                document.save()
                citation.document = document
                stage = "link_citation"
                citation.save(update_fields=["document"])
                stage = "clear_downstream_results"
                self.clear_downstream_results(citation, document)
                result.selected_url = url
                result.status = result.Status.FULFILLED
                result.error = ""
                stage = "fulfill_request"
                result.save()
                if old_file:
                    transaction.on_commit(
                        lambda: delete_stored_file(
                            document.file.storage, old_file
                        )
                    )
                stage = "commit"
            self.log(
                "attachment_finished",
                document_id=document.pk,
                filename=document.file.name,
            )
        except Exception as exc:
            self.log(
                f"attachment_{stage}_failed",
                level=logging.ERROR,
                exc_info=not isinstance(
                    exc, (DoiPdfError, MissingPreconditionError)
                ),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            if saved_file:
                delete_stored_file(*saved_file, reason="rollback_new_pdf")
            raise

    @staticmethod
    def clear_downstream_results(citation, document):
        for figure in DocumentFigure.objects.filter(document=document):
            if figure.file.name:
                storage, name = figure.file.storage, figure.file.name
                transaction.on_commit(
                    lambda storage=storage, name=name: delete_stored_file(
                        storage, name, reason="replaced_figure"
                    )
                )
        for model in (
            TextExtractionResult,
            FigureExtractionResult,
            DocumentFigure,
            DocumentTable,
        ):
            try:
                deleted, _ = model.objects.filter(document=document).delete()
            except Exception:
                log_doi_pdf_event(
                    f"downstream_{model._meta.model_name}_delete_failed",
                    level=logging.ERROR,
                    exc_info=True,
                    citation_id=citation.pk,
                    document_id=document.pk,
                )
                raise
            log_doi_pdf_event(
                "downstream_results_cleared",
                model=model.__name__,
                citation_id=citation.pk,
                document_id=document.pk,
                deleted=deleted,
            )
        for model in (
            L1ScreeningResult,
            L2ScreeningResult,
            ParameterExtractionResult,
        ):
            try:
                deleted, _ = model.objects.filter(citation=citation).delete()
            except Exception:
                log_doi_pdf_event(
                    f"downstream_{model._meta.model_name}_delete_failed",
                    level=logging.ERROR,
                    exc_info=True,
                    citation_id=citation.pk,
                    document_id=document.pk,
                )
                raise
            log_doi_pdf_event(
                "downstream_results_cleared",
                model=model.__name__,
                citation_id=citation.pk,
                document_id=document.pk,
                deleted=deleted,
            )
