# Part of Odoo. See LICENSE file for full copyright and licensing details.

import hashlib
import hmac
import json
import logging
import pprint

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MyFatoorahController(http.Controller):
    """Controller for MyFatoorah payment callbacks and webhooks."""

    _return_url = '/payment/myfatoorah/return'
    _error_url = '/payment/myfatoorah/error'
    _webhook_url = '/payment/myfatoorah/webhook'

    # === PAYMENT RETURN HANDLERS === #

    @http.route(
        _return_url,
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def myfatoorah_return(self, **kwargs):
        """Handle the customer redirect after a successful payment.

        MyFatoorah appends `paymentId` as a query parameter to the callback URL.
        We use this to look up and verify the payment status.

        :param dict kwargs: The query string parameters from MyFatoorah redirect.
        :return: Redirect to the payment status page.
        """
        _logger.info(
            "MyFatoorah: Received success callback with data:\n%s",
            pprint.pformat(kwargs),
        )

        payment_id = kwargs.get('paymentId')
        if not payment_id:
            _logger.error("MyFatoorah: No paymentId in success callback.")
            return request.redirect('/payment/status')

        # Build notification data
        notification_data = {
            'paymentId': payment_id,
            'status': 'success',
        }

        # Find and process the transaction
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                'myfatoorah', notification_data
            )
            tx_sudo._handle_notification_data('myfatoorah', notification_data)
        except Exception as e:
            _logger.exception(
                "MyFatoorah: Error processing success callback for paymentId %s: %s",
                payment_id, str(e),
            )

        return request.redirect('/payment/status')

    @http.route(
        _error_url,
        type='http',
        auth='public',
        methods=['GET'],
        csrf=False,
        save_session=False,
    )
    def myfatoorah_error(self, **kwargs):
        """Handle the customer redirect after a failed/canceled payment.

        :param dict kwargs: The query string parameters from MyFatoorah redirect.
        :return: Redirect to the payment status page.
        """
        _logger.info(
            "MyFatoorah: Received error callback with data:\n%s",
            pprint.pformat(kwargs),
        )

        payment_id = kwargs.get('paymentId')
        if not payment_id:
            _logger.error("MyFatoorah: No paymentId in error callback.")
            return request.redirect('/payment/status')

        # Build notification data
        notification_data = {
            'paymentId': payment_id,
            'status': 'error',
        }

        # Find and process the transaction
        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                'myfatoorah', notification_data
            )
            tx_sudo._handle_notification_data('myfatoorah', notification_data)
        except Exception as e:
            _logger.exception(
                "MyFatoorah: Error processing error callback for paymentId %s: %s",
                payment_id, str(e),
            )

        return request.redirect('/payment/status')

    # === WEBHOOK HANDLER === #

    @http.route(
        _webhook_url,
        type='http',
        auth='public',
        methods=['POST'],
        csrf=False,
        save_session=False,
    )
    def myfatoorah_webhook(self, **kwargs):
        """Handle incoming MyFatoorah webhook events.

        Verifies the webhook signature using HMAC-SHA256, parses the event,
        and updates the corresponding payment transaction.

        MyFatoorah Webhook V2 events include:
        - PAYMENT_STATUS_CHANGED
        - REFUND_STATUS_CHANGED
        - BALANCE_TRANSFERRED

        :return: HTTP 200 on success, 400/401 on error.
        """
        _logger.info("MyFatoorah: Received webhook event.")

        # Read raw body for signature verification
        try:
            raw_body = request.httprequest.get_data()
            event_data = json.loads(raw_body)
        except (ValueError, TypeError) as e:
            _logger.error("MyFatoorah: Invalid webhook JSON body: %s", str(e))
            return request.make_json_response(
                {'status': 'error', 'message': 'Invalid JSON body'},
                status=400,
            )

        _logger.info(
            "MyFatoorah: Webhook event data:\n%s",
            pprint.pformat(event_data),
        )

        # Extract signature from headers
        signature = request.httprequest.headers.get('MyFatoorah-Signature', '')
        if not signature:
            # Also check lowercase header
            signature = request.httprequest.headers.get('myfatoorah-signature', '')

        event_type = event_data.get('Event') or event_data.get('EventType', 'Unknown')
        _logger.info("MyFatoorah: Webhook event type: %s", event_type)

        # Find the appropriate provider for signature verification
        providers = request.env['payment.provider'].sudo().search([
            ('code', '=', 'myfatoorah'),
            ('state', 'in', ['enabled', 'test']),
            ('myfatoorah_webhook_enabled', '=', True),
        ])

        if not providers:
            _logger.warning(
                "MyFatoorah: No active provider with webhooks enabled. "
                "Ignoring webhook event."
            )
            return request.make_json_response(
                {'status': 'error', 'message': 'No active webhook provider'},
                status=400,
            )

        # Verify signature with at least one provider
        signature_verified = False
        matching_provider = None
        for provider in providers:
            if provider._myfatoorah_verify_webhook_signature(raw_body, signature):
                signature_verified = True
                matching_provider = provider
                break

        if not signature_verified:
            _logger.warning(
                "MyFatoorah: Webhook signature verification failed for all providers."
            )
            return request.make_json_response(
                {'status': 'error', 'message': 'Invalid signature'},
                status=401,
            )

        # Process the webhook event based on type
        try:
            self._process_webhook_event(event_type, event_data, matching_provider)
        except Exception as e:
            _logger.exception(
                "MyFatoorah: Error processing webhook event %s: %s",
                event_type, str(e),
            )
            # Still return 200 to avoid MyFatoorah retries for processing errors
            # The error is logged for debugging
            return request.make_json_response(
                {'status': 'ok', 'message': 'Event received but processing failed'},
                status=200,
            )

        return request.make_json_response(
            {'status': 'ok', 'message': 'Event processed successfully'},
            status=200,
        )

    def _process_webhook_event(self, event_type, event_data, provider):
        """Process a verified webhook event.

        :param str event_type: The type of webhook event.
        :param dict event_data: The full webhook event payload.
        :param payment.provider provider: The matched provider record.
        """
        _logger.info(
            "MyFatoorah: Processing webhook event type: %s",
            event_type,
        )

        # Extract relevant data from the event
        data = event_data.get('Data', event_data)
        invoice_id = data.get('InvoiceId')
        payment_id = data.get('PaymentId')
        customer_reference = data.get('CustomerReference')

        if event_type in ('PAYMENT_STATUS_CHANGED', 'TransactionStatusChanged'):
            # Build notification data for transaction processing
            notification_data = {
                'InvoiceId': invoice_id,
                'paymentId': payment_id,
                'CustomerReference': customer_reference,
                'webhook_event': event_type,
            }

            try:
                tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
                    'myfatoorah', notification_data
                )
                tx_sudo._handle_notification_data('myfatoorah', notification_data)
                _logger.info(
                    "MyFatoorah: Webhook — Transaction %s updated for event %s.",
                    tx_sudo.reference, event_type,
                )
            except Exception as e:
                _logger.error(
                    "MyFatoorah: Webhook — Failed to process PAYMENT_STATUS_CHANGED "
                    "for InvoiceId %s: %s",
                    invoice_id, str(e),
                )
                raise

        elif event_type in ('REFUND_STATUS_CHANGED', 'RefundStatusChanged'):
            refund_status = data.get('RefundStatus', '').lower()
            _logger.info(
                "MyFatoorah: Webhook — Refund status changed for InvoiceId %s: %s",
                invoice_id, refund_status,
            )
            # Find the transaction and log the refund status
            if invoice_id:
                tx_sudo = request.env['payment.transaction'].sudo().search([
                    ('provider_reference', '=', str(invoice_id)),
                    ('provider_code', '=', 'myfatoorah'),
                ], limit=1)
                if tx_sudo:
                    tx_sudo.message_post(body=(
                        f"MyFatoorah Webhook: Refund status changed to "
                        f"'{refund_status}' for invoice {invoice_id}."
                    ))
                    _logger.info(
                        "MyFatoorah: Refund status logged on transaction %s.",
                        tx_sudo.reference,
                    )

        elif event_type in ('BALANCE_TRANSFERRED', 'BalanceTransferred'):
            _logger.info(
                "MyFatoorah: Webhook — Balance transferred event received. "
                "Data: %s", pprint.pformat(data),
            )
            # Informational — no transaction update needed

        else:
            _logger.info(
                "MyFatoorah: Webhook — Unhandled event type: %s. Data: %s",
                event_type, pprint.pformat(data),
            )
