import base64
from datetime import datetime

import requests
from django.conf import settings

from .daraja import get_daraja_access_token


def initiate_stk_push(phone_number, amount, account_reference):
    """
    Initiate a Daraja sandbox STK Push.
    This requests payment approval; it does not confirm payment.
    """

    shortcode = settings.DARAJA_SHORTCODE
    passkey = settings.DARAJA_PASSKEY
    base_url = settings.DARAJA_BASE_URL.rstrip("/")

    if not shortcode or not passkey:
        raise ValueError(
            "Configure DARAJA_SHORTCODE and DARAJA_PASSKEY "
            "in the local .env file first."
        )

    token = get_daraja_access_token()

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        f"{shortcode}{passkey}{timestamp}".encode()
    ).decode()

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": int(amount),
        "PartyA": phone_number,
        "PartyB": shortcode,
        "PhoneNumber": phone_number,
        "CallBackURL": settings.DARAJA_CALLBACK_URL,
        "AccountReference": account_reference,
        "TransactionDesc": "Nexora calling credit",
    }

    response = requests.post(
        f"{base_url}/mpesa/stkpush/v1/processrequest",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


    
def query_stk_push_status(checkout_request_id):
    """
    Ask Daraja for the status of an existing STK Push.
    This function does not credit an account.
    """
    import base64
    from datetime import datetime

    import requests
    from django.conf import settings

    from .daraja import get_daraja_access_token

    shortcode = settings.DARAJA_SHORTCODE
    passkey = settings.DARAJA_PASSKEY
    base_url = settings.DARAJA_BASE_URL.rstrip("/")

    if not shortcode or not passkey:
        raise ValueError(
            "Configure the Daraja shortcode and passkey first."
        )

    if not checkout_request_id or not checkout_request_id.strip():
        raise ValueError("A checkout request ID is required.")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    password = base64.b64encode(
        f"{shortcode}{passkey}{timestamp}".encode("utf-8")
    ).decode("utf-8")

    payload = {
        "BusinessShortCode": shortcode,
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": checkout_request_id.strip(),
    }

    token = get_daraja_access_token()

    try:
        response = requests.post(
            f"{base_url}/mpesa/stkpushquery/v1/query",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()

    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(
            "Could not retrieve the STK Push status from Daraja."
        ) from exc

    # Return the provider response for interpretation by the caller.
    # Never credit an account based only on this API response.
    return result
