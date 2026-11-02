import logging
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError

from my_app.services.doi_pdf_service import (
    DoiPdfError,
    OpenAlexClient,
    download_pdf,
    log_doi_pdf_event,
    normalize_doi,
)

DEFAULT_DOI = "10.3346/jkms.2017.32.11.1876"


class Command(BaseCommand):
    help = "Check OpenAlex configuration, DOI lookup, and authenticated cached-PDF download without storing it."

    def add_arguments(self, parser):
        parser.add_argument(
            "doi",
            nargs="?",
            default=DEFAULT_DOI,
            help="DOI or doi.org URL; defaults to a JKMS article with an OpenAlex-cached PDF.",
        )

    def handle(self, *args, **options):
        log_doi_pdf_event("openalex_check_started", doi=options["doi"])
        stage = "normalize_doi"
        try:
            doi = normalize_doi(options["doi"])
            stage = "lookup"
            candidates = OpenAlexClient().iter_pdf_urls(doi)
            try:
                url = next(candidates, None)
            finally:
                candidates.close()
            stage = "cached_pdf_available"
            # Publisher URLs would not verify access to OpenAlex's content API.
            if not url or urlsplit(url).hostname != "content.openalex.org":
                raise DoiPdfError(
                    "OpenAlex has no cached PDF for this DOI. Try the default DOI or another DOI with a cached PDF."
                )
            stage = "download"
            with download_pdf(url):
                pass
        except DoiPdfError as exc:
            log_doi_pdf_event(
                f"openalex_check_{stage}_failed",
                level=logging.ERROR,
                doi=options["doi"],
                error=str(exc),
            )
            raise CommandError(f"OpenAlex check failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"OpenAlex check passed for {doi}: DOI lookup and cached PDF download succeeded."
            )
        )
        self.stdout.write(url)
        log_doi_pdf_event("openalex_check_finished", doi=doi, url=url)
