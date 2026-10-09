from my_app.router import route
from my_app.tables.citation_table import CitationTableDef

from .common import ReviewTableView


@route("/reviews/<int:review_id>/tables/citations/", name="citation_table")
class CitationTableView(ReviewTableView):
    table_def_class = CitationTableDef
