from my_app.router import route
from my_app.views.screening.document_util_components import (
    DocumentCitationDetailView,
)
from my_app.views.screening.parameter_extraction.list import (
    ParameterExtractionPdfPage as BaseParameterExtractionPdfPage,
)
from my_app.views.screening.parameter_extraction.list import (
    render_parameter_extraction_control,
)


class ParameterExtractionPdfPage(BaseParameterExtractionPdfPage):
    pass


@route(
    "/reviews/<int:review_id>/parameter_extraction/rows/<int:row_pk>/details/",
    name="parameter_extraction_citation_detail",
)
class ParameterExtractionPdfView(DocumentCitationDetailView):
    template_component = ParameterExtractionPdfPage
