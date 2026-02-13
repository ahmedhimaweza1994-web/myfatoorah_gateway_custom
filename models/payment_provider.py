# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import logging
import pprint

import requests

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Country-specific live API URLs
MYFATOORAH_LIVE_URLS = {
    'SA': 'https://api-sa.myfatoorah.com',
    'AE': 'https://api-ae.myfatoorah.com',
    'QA': 'https://api-qa.myfatoorah.com',
    'EG': 'https://api-eg.myfatoorah.com',
    'KW': 'https://api.myfatoorah.com',
    'BH': 'https://api.myfatoorah.com',
    'JO': 'https://api.myfatoorah.com',
    'OM': 'https://api.myfatoorah.com',
}

MYFATOORAH_TEST_URL = 'https://apitest.myfatoorah.com'

MYFATOORAH_COUNTRY_SELECTION = [
    ('SA', 'Saudi Arabia'),
    ('KW', 'Kuwait'),
    ('BH', 'Bahrain'),
    ('AE', 'United Arab Emirates'),
    ('QA', 'Qatar'),
    ('EG', 'Egypt'),
    ('OM', 'Oman'),
    ('JO', 'Jordan'),
]

# Timeout for API requests in seconds
MYFATOORAH_TIMEOUT = 30


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    # === SELECTION EXTENSION === #
    code = fields.Selection(
        selection_add=[('myfatoorah', "MyFatoorah")],
        ondelete={'myfatoorah': 'set default'},
    )

    # === CREDENTIAL FIELDS === #
    myfatoorah_secret_key = fields.Char(
        string="MyFatoorah Secret Key (Live)",
        required_if_provider='myfatoorah',
        copy=False,
        groups='base.group_system',
    )
    myfatoorah_test_secret_key = fields.Char(
        string="MyFatoorah Secret Key (Test)",
        copy=False,
        groups='base.group_system',
    )
    myfatoorah_country_code = fields.Selection(
        selection=MYFATOORAH_COUNTRY_SELECTION,
        string="MyFatoorah Country",
        default='SA',
        required_if_provider='myfatoorah',
    )

    # === WEBHOOK FIELDS === #
    myfatoorah_webhook_secret = fields.Char(
        string="Webhook Secret Key",
        copy=False,
        groups='base.group_system',
    )
    myfatoorah_webhook_enabled = fields.Boolean(
        string="Enable Webhooks",
        default=False,
    )

    # === COMPUTE METHODS === #

    def _compute_feature_support_fields(self):
        """ Override of `payment` to enable additional features. """
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'myfatoorah').update({
            'support_refund': 'full_only',
        })

    # === CRUD METHODS === #

    def _get_default_payment_method_codes(self):
        """ Override of `payment` to return the default payment method codes. """
        self.ensure_one()
        if self.code != 'myfatoorah':
            return super()._get_default_payment_method_codes()
        return {'card'}

    # === API HELPERS === #

    def _myfatoorah_get_api_url(self):
        """Return the correct API base URL based on state and country.

        :return: The MyFatoorah API base URL.
        :rtype: str
        """
        self.ensure_one()
        if self.state == 'test':
            return MYFATOORAH_TEST_URL
        country = self.myfatoorah_country_code or 'SA'
        return MYFATOORAH_LIVE_URLS.get(country, MYFATOORAH_LIVE_URLS['SA'])

    def _myfatoorah_get_api_key(self):
        """Return the correct API key based on provider state.

        :return: The API key (token).
        :rtype: str
        """
        self.ensure_one()
        if self.state == 'test':
            key = self.myfatoorah_test_secret_key
        else:
            key = self.myfatoorah_secret_key
        if not key:
            raise ValidationError(_(
                "MyFatoorah: Missing API key. Please configure the %(mode)s secret key "
                "in the MyFatoorah payment provider settings.",
                mode='Test' if self.state == 'test' else 'Live',
            ))
        return key

    def _myfatoorah_make_request(self, endpoint, payload=None, method='POST'):
        """Make an HTTP request to the MyFatoorah API.

        :param str endpoint: The API endpoint path (e.g. '/v2/SendPayment').
        :param dict payload: The JSON request body.
        :param str method: The HTTP method ('POST' or 'GET').
        :return: The parsed JSON response data.
        :rtype: dict
        :raises ValidationError: If the request fails or returns an error.
        """
        self.ensure_one()

        api_url = self._myfatoorah_get_api_url()
        api_key = self._myfatoorah_get_api_key()
        url = f"{api_url}{endpoint}"

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        _logger.info(
            "MyFatoorah API request: %s %s\nPayload:\n%s",
            method, url,
            pprint.pformat(payload) if payload else 'None',
        )

        try:
            if method.upper() == 'POST':
                response = requests.post(
                    url, json=payload, headers=headers, timeout=MYFATOORAH_TIMEOUT,
                )
            else:
                response = requests.get(
                    url, headers=headers, timeout=MYFATOORAH_TIMEOUT,
                )
        except requests.exceptions.Timeout:
            _logger.error("MyFatoorah API request timed out: %s %s", method, url)
            raise ValidationError(_(
                "MyFatoorah: The request to the payment gateway timed out. Please try again."
            ))
        except requests.exceptions.ConnectionError:
            _logger.error("MyFatoorah API connection error: %s %s", method, url)
            raise ValidationError(_(
                "MyFatoorah: Could not connect to the payment gateway. "
                "Please check your internet connection and try again."
            ))
        except requests.exceptions.RequestException as e:
            _logger.error("MyFatoorah API request error: %s", str(e))
            raise ValidationError(_(
                "MyFatoorah: An error occurred while communicating with the payment gateway."
            ))

        try:
            response_data = response.json()
        except ValueError:
            _logger.error(
                "MyFatoorah API returned non-JSON response: %s (HTTP %s)",
                response.text[:500], response.status_code,
            )
            raise ValidationError(_(
                "MyFatoorah: Received an invalid response from the payment gateway."
            ))

        _logger.info(
            "MyFatoorah API response (HTTP %s):\n%s",
            response.status_code,
            pprint.pformat(response_data),
        )

        if response.status_code != 200 or not response_data.get('IsSuccess'):
            error_message = response_data.get('Message', 'Unknown error')
            validation_errors = response_data.get('ValidationErrors')
            if validation_errors:
                details = '; '.join(
                    err.get('Error', '') for err in validation_errors if isinstance(err, dict)
                )
                error_message = f"{error_message} — {details}"
            _logger.error("MyFatoorah API error: %s", error_message)
            raise ValidationError(_(
                "MyFatoorah: %(error)s",
                error=error_message,
            ))

        return response_data.get('Data', {})

    def _myfatoorah_verify_webhook_signature(self, raw_body, signature):
        """Verify the HMAC-SHA256 signature of a webhook event.

        :param bytes raw_body: The raw request body bytes.
        :param str signature: The signature from the header.
        :return: True if signature is valid.
        :rtype: bool
        """
        self.ensure_one()

        if not self.myfatoorah_webhook_secret:
            _logger.warning(
                "MyFatoorah webhook: No secret key configured for provider %s.", self.name,
            )
            return False

        expected_signature = hmac.new(
            key=self.myfatoorah_webhook_secret.encode('utf-8'),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        is_valid = hmac.compare_digest(expected_signature, signature)

        if is_valid:
            _logger.info("MyFatoorah webhook: Signature verification PASSED.")
        else:
            _logger.warning(
                "MyFatoorah webhook: Signature verification FAILED. "
                "Expected: %s..., Got: %s...",
                expected_signature[:16], signature[:16] if signature else 'None',
            )

        return is_valid
