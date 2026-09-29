from functools import lru_cache

from azure.identity import DefaultAzureCredential


@lru_cache(maxsize=1)
def get_azure_credential() -> DefaultAzureCredential:
    return DefaultAzureCredential()
