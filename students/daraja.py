
import requests

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from requests.auth import HTTPBasicAuth


def get_daraja_access_token():
    """
    Request an OAuth access token from Safaricom Daraja sandbox.
    Never print or log the consumer secret or access token.
    """
    consumer_key = settings.DARAJA_CONSUMER_KEY
    consumer_secret = settings.DARAJA_CONSUMER_SECRET
    base_url = settings.DARAJA_BASE_URL.rstrip("/")

    if not consumer_key or not consumer_secret:
        raise ImproperlyConfigured(
            "Daraja credentials are missing. "
            "Check your local .env file."
        )

    url = f"{base_url}/oauth/v1/generate"

    try:
        response = requests.get(
            url,
            params={"grant_type": "client_credentials"},
            auth=HTTPBasicAuth(consumer_key, consumer_secret),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            "Could not connect to Daraja sandbox. "
            "Check your network and sandbox configuration."
        ) from exc

    access_token = data.get("access_token")

    if not access_token:
        raise RuntimeError(
            "Daraja did not return an access token. "
            "Check your sandbox app credentials."
        )

    return access_token