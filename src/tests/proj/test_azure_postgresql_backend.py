from unittest.mock import patch

from proj.azure.azure_postgresql.base import DatabaseWrapper

TOKEN_PATH = "proj.azure.azure_postgresql.base.get_access_token"

SETTINGS_DICT = {
    "NAME": "mydb",
    "USER": "me@tenant.onmicrosoft.com",
    "PASSWORD": "",
    "HOST": "myhost.postgres.database.azure.com",
    "PORT": "5432",
    "OPTIONS": {},
    "TIME_ZONE": None,
}


def get_params():
    wrapper = DatabaseWrapper(SETTINGS_DICT.copy(), alias="azure_test")
    return wrapper.get_connection_params()


def test_access_token_used_as_password():
    with patch(TOKEN_PATH, return_value="fake-token") as mock_token:
        params = get_params()

    assert params["password"] == "fake-token"
    assert params["user"] == "me@tenant.onmicrosoft.com"
    assert params["sslmode"] == "require"
    assert mock_token.call_count == 1


def test_token_fetched_on_each_connection():
    """Tokens are short lived, so a stale one must never be reused."""
    with patch(TOKEN_PATH, side_effect=["token-1", "token-2"]):
        assert get_params()["password"] == "token-1"
        assert get_params()["password"] == "token-2"


def test_azure_db_auth_mode(reloaded_settings):
    new_settings = reloaded_settings(
        **{
            "DB_AUTH_MODE": "azure",
            "USE_SQLITE": "False",
            "DB_NAME": "mydb",
            "DB_USER": "myapp",
            "DB_PASSWORD": "should_be_cleared",
            "DB_HOST": "localhost",
            "DB_PORT": "5432",
        }
    )

    database_settings = new_settings.DATABASES["default"]

    assert database_settings["ENGINE"] == "proj.azure.azure_postgresql"
    assert database_settings["PASSWORD"] == ""
    assert database_settings["TEST"]["ENGINE"] == "proj.azure.azure_postgresql"
