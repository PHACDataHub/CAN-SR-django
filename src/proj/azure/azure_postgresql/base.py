from django.db.backends.postgresql import base

from proj.azure.azure_auth import get_azure_credential

OSSRDBMS_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


def get_access_token() -> str:
    return get_azure_credential().get_token(OSSRDBMS_SCOPE).token


class DatabaseWrapper(base.DatabaseWrapper):
    def get_connection_params(self):
        params = super().get_connection_params()
        params["password"] = get_access_token()
        params.setdefault("sslmode", "require")
        return params
