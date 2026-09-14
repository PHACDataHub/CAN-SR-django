"""
Postgres backend that authenticates with an Entra ID access token instead of a
static password. Used when DB_AUTH_MODE=azure.

Azure Database for PostgreSQL Flexible Server accepts an Entra access token
(scope https://ossrdbms-aad.database.windows.net) in place of the password.
Tokens are short lived, so the token is fetched per-connection rather than
being baked into settings.DATABASES.
"""

from functools import lru_cache

from django.db.backends.postgresql import base

from azure.identity import DefaultAzureCredential

OSSRDBMS_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


@lru_cache(maxsize=1)
def get_credential() -> DefaultAzureCredential:
    """
    A single credential instance is shared across connections. Constructing one
    is cheap, but the instance holds the state that makes get_token() cheap:
    the token cache, and the identity of whichever credential in the chain
    succeeded (so later calls skip re-walking the chain).
    """
    return DefaultAzureCredential()


def get_access_token() -> str:
    """
    Usually served from the credential's in-memory cache; only hits the network
    when there is no cached token or it is close to expiring.
    """
    return get_credential().get_token(OSSRDBMS_SCOPE).token


class DatabaseWrapper(base.DatabaseWrapper):
    def get_connection_params(self):
        params = super().get_connection_params()
        params["password"] = get_access_token()
        params.setdefault("sslmode", "require")
        return params
