import logging

from django.core.management.base import BaseCommand, CommandError

from my_app.services.doi_pdf_service import (
    DoiPdfError,
    download_pdf,
    iter_doi_pdf_urls,
    log_doi_pdf_event,
    normalize_doi,
)

DEFAULT_DOI = "10.1016/j.jcv.2006.04.001"


class Command(BaseCommand):
    help = "Check DOI PDF resolution through Unpaywall and OpenAlex, optionally validating a download."

    def add_arguments(self, parser):
        parser.add_argument(
            "doi",
            nargs="?",
            default=DEFAULT_DOI,
            help="DOI or doi.org URL; defaults to a PubMed Central article.",
        )
        parser.add_argument(
            "--download",
            action="store_true",
            help="Download and validate a PDF without saving or attaching it.",
        )
        parser.add_argument(
            "--provider",
            choices=["auto", "unpaywall", "openalex"],
            default="auto",
            help="Select a provider; auto tries Unpaywall, then configured OpenAlex, with a separate retry limit for each.",
        )

    def handle(self, *args, **options):
        log_doi_pdf_event("resolution_check_started", doi=options["doi"])
        try:
            doi = normalize_doi(options["doi"])
            candidates = iter_doi_pdf_urls(doi, provider=options["provider"])
            if options["download"]:
                verified_url = self.verify_download(candidates)
                urls = []
                if verified_url:
                    urls.append(verified_url)
            else:
                urls = list(candidates)
            if not urls:
                log_doi_pdf_event(
                    "resolution_check_no_pdf_candidates",
                    level=logging.ERROR,
                    doi=doi,
                )
                raise DoiPdfError(
                    "No open-access PDF URL was found for this DOI."
                )
        except DoiPdfError as exc:
            log_doi_pdf_event(
                "resolution_check_failed",
                level=logging.ERROR,
                doi=options["doi"],
                error=str(exc),
            )
            raise CommandError(
                f"DOI PDF resolution check failed: {exc}"
            ) from exc
        message = f"DOI PDF resolution check passed for {doi}"
        if options["download"]:
            message = f"DOI PDF download check passed for {doi}"
        self.stdout.write(self.style.SUCCESS(message))
        for url in urls:
            self.stdout.write(url)
        log_doi_pdf_event(
            "resolution_check_finished", doi=doi, pdf_urls=len(urls)
        )

    def verify_download(self, candidates):
        last_error = None
        for attempt, url in enumerate(candidates, start=1):
            try:
                with download_pdf(url):
                    return url
            except DoiPdfError as exc:
                last_error = exc
                log_doi_pdf_event(
                    "resolution_check_candidate_failed",
                    level=logging.WARNING,
                    attempt=attempt,
                    url=url,
                    error=str(exc),
                )
        if last_error is not None:
            raise last_error
        return None
