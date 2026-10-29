from itertools import islice

from django.core.management.base import BaseCommand, CommandError

from my_app.services.doi_pdf_service import (
    PDF_FROM_DOI_MAX_RETRIES,
    DoiPdfError,
    UnpaywallClient,
    normalize_doi,
)

DEFAULT_DOI = "10.1016/j.jcv.2006.04.001"


class Command(BaseCommand):
    help = "Check Unpaywall connectivity and resolve a DOI to a PDF URL."

    def add_arguments(self, parser):
        parser.add_argument(
            "doi",
            nargs="?",
            default=DEFAULT_DOI,
            help="DOI or doi.org URL; defaults to a PubMed Central article.",
        )

    def handle(self, *args, **options):
        try:
            doi = normalize_doi(options["doi"])
            urls = list(
                islice(
                    UnpaywallClient().iter_pdf_urls(doi),
                    PDF_FROM_DOI_MAX_RETRIES,
                )
            )
            if not urls:
                raise DoiPdfError(
                    "No open-access PDF URL was found for this DOI."
                )
        except DoiPdfError as exc:
            raise CommandError(
                f"DOI PDF resolution check failed: {exc}"
            ) from exc
        self.stdout.write(
            self.style.SUCCESS(f"DOI PDF resolution check passed for {doi}")
        )
        for url in urls:
            self.stdout.write(url)
