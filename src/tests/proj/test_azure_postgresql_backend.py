from unittest.mock import patch

from proj.azure.azure_postgresql.base import DatabaseWrapper

TOKEN_PATH = "proj.azure.azure_postgresql.base.get_access_token"

SETTINGS_DICT = {
    "ENGINE": "proj.azure.azure_postgresql",
    "NAME": "mydb",
    "USER": "me@tenant.onmicrosoft.com",
    "PASSWORD": "",
    "HOST": "myhost.postgres.database.azure.com",
    "PORT": "5432",
    "OPTIONS": {},
    "CONN_MAX_AGE": 0,
    "CONN_HEALTH_CHECKS": False,
    "AUTOCOMMIT": True,
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


def test_explicit_sslmode_is_respected():
    settings_dict = SETTINGS_DICT.copy()
    settings_dict["OPTIONS"] = {"sslmode": "verify-full"}

    with patch(TOKEN_PATH, return_value="fake-token"):
        wrapper = DatabaseWrapper(settings_dict, alias="azure_test")
        params = wrapper.get_connection_params()

    assert params["sslmode"] == "verify-full"
