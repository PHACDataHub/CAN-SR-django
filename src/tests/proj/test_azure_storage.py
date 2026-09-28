import pytest

AZURE_STORAGE_ENV = {
    "MEDIA_STORAGE_MODE": "azure",
    "AZURE_STORAGE_ACCOUNT_NAME": "app",
    "AZURE_STORAGE_MEDIA_CONTAINER": "media",
}


def test_azure_storage_mode(reloaded_settings, fake_azure_credential):
    new_settings = reloaded_settings(**AZURE_STORAGE_ENV)

    storage_settings = new_settings.STORAGES["default"]
    options = storage_settings["OPTIONS"]

    assert (
        storage_settings["BACKEND"]
        == "storages.backends.azure_storage.AzureStorage"
    )
    assert options["token_credential"] is fake_azure_credential
    assert options["account_name"] == "app"
    assert options["azure_container"] == "media"


def test_local_storage_mode_is_default(reloaded_settings):
    new_settings = reloaded_settings(**{"MEDIA_STORAGE_MODE": "local"})

    assert (
        new_settings.STORAGES["default"]["BACKEND"]
        == "django.core.files.storage.FileSystemStorage"
    )


def test_unknown_storage_mode_is_rejected(reloaded_settings):
    with pytest.raises(ValueError, match="Invalid MEDIA_STORAGE_MODE"):
        reloaded_settings(**{"MEDIA_STORAGE_MODE": "s3"})
