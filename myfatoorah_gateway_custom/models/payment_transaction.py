# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import pprint

from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools.urls import urljoin as url_join

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # === ACTION METHODS === #

    def _get_specific_processing_values(self, processing_values):
        """ Override of `payment` to return MyFatoorah-specific processing values.

        Calls the MyFatoorah SendPayment API to create an invoice
        and returns the invoice URL for customer redirect.

        Note: self.ensure_one() from `_get_processing_values`.

        :param dict processing_values: The generic processing values of the transaction.
        :return: The dict of provider-specific processing values.
        :rtype: dict
        """
        res = super()._get_specific_processing_values(processing_values)
        if self.provider_code != 'myfatoorah':
            return res

        provider = self.provider_id
        base_url = provider.get_base_url()

        # Build callback URLs
        return_url = url_join(base_url, '/payment/myfatoorah/return')
        error_url = url_join(base_url, '/payment/myfatoorah/error')
        webhook_url = url_join(base_url, '/payment/myfatoorah/webhook')

        # Determine language
        lang = 'ar' if self.partner_lang and 'ar' in self.partner_lang else 'en'

        # Build invoice items from sale order lines if available
        invoice_items = []
        if self.sale_order_ids:
            for order in self.sale_order_ids:
                for line in order.order_line:
                    if line.product_id and line.price_unit > 0:
                        invoice_items.append({
                            'ItemName': line.product_id.name or line.name or 'Product',
                            'Quantity': int(line.product_uom_qty) or 1,
                            'UnitPrice': round(line.price_unit, 3),
                        })
        if not invoice_items:
            invoice_items.append({
                'ItemName': self.reference or 'Payment',
                'Quantity': 1,
                'UnitPrice': round(self.amount, 3),
            })

        # Build the SendPayment payload
        payload = {
            'InvoiceValue': round(self.amount, 3),
            'CustomerName': self.partner_name or self.partner_id.name or 'Customer',
            'NotificationOption': 'LNK',
            'CallBackUrl': return_url,
            'ErrorUrl': error_url,
            'Language': lang,
            'DisplayCurrencyIso': self.currency_id.name if self.currency_id else 'SAR',
            'CustomerReference': self.reference,
            'InvoiceItems': invoice_items,
        }

        # Add optional customer data
        if self.partner_email:
            payload['CustomerEmail'] = self.partner_email
            payload['NotificationOption'] = 'ALL'

        if self.partner_phone:
            phone = ''.join(c for c in self.partner_phone if c.isdigit() or c == '+')
            if phone:
                payload['CustomerMobile'] = phone
                if payload['NotificationOption'] == 'LNK':
                    payload['NotificationOption'] = 'SMS'

        # Add customer address if available
        partner = self.partner_id
        if partner and partner.street:
            payload['CustomerAddress'] = {
                'Block': '',
                'Street': partner.street or '',
                'HouseBuildingNo': '',
                'Address': ', '.join(filter(None, [
                    partner.street, partner.street2,
                    partner.city,
                    partner.state_id.name if partner.state_id else '',
                    partner.zip,
                ])),
                'AddressInstructions': '',
            }

        # Add webhook URL if enabled
        if provider.myfatoorah_webhook_enabled:
            payload['WebhookUrl'] = webhook_url

        _logger.info(
            "MyFatoorah: Creating invoice for transaction %s (amount: %s %s)",
            self.reference, self.amount, self.currency_id.name,
        )

        # Call SendPayment API
        response_data = provider._myfatoorah_make_request('/v2/SendPayment', payload)

        invoice_url = response_data.get('InvoiceURL')
        invoice_id = response_data.get('InvoiceId')

        if not invoice_url:
            raise ValidationError(_(
                "MyFatoorah: No invoice URL received from the payment gateway."
            ))

        _logger.info(
            "MyFatoorah: Invoice created — ID: %s, URL: %s, Reference: %s",
            invoice_id, invoice_url, self.reference,
        )

        # Store the invoice ID as provider_reference for later lookup
        self.provider_reference = str(invoice_id) if invoice_id else ''

        return {
            'api_url': invoice_url,
            'reference': self.reference,
        }

    # === NOTIFICATION HANDLING === #

    @api.model
    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Override of `payment` to find the transaction based on MyFatoorah data.

        :param str provider_code: The provider code.
        :param dict notification_data: The notification data from callback/webhook.
        :return: The matching transaction.
        :rtype: payment.transaction recordset
        :raises ValidationError: If the transaction cannot be found.
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'myfatoorah' or len(tx) == 1:
            return tx

        reference = notification_data.get('CustomerReference')
        payment_id = notification_data.get('paymentId')
        invoice_id = notification_data.get('InvoiceId')

        _logger.info(
            "MyFatoorah: Looking up transaction — reference: %s, paymentId: %s, invoiceId: %s",
            reference, payment_id, invoice_id,
        )

        # Try finding by reference first
        if reference:
            tx = self.search([
                ('reference', '=', reference),
                ('provider_code', '=', 'myfatoorah'),
            ], limit=1)
            if tx:
                return tx

        # Try finding by provider_reference (InvoiceId)
        if invoice_id:
            tx = self.search([
                ('provider_reference', '=', str(invoice_id)),
                ('provider_code', '=', 'myfatoorah'),
            ], limit=1)
            if tx:
                return tx

        # If we have a paymentId, query MyFatoorah API for details
        if payment_id:
            providers = self.env['payment.provider'].sudo().search([
                ('code', '=', 'myfatoorah'),
                ('state', 'in', ['enabled', 'test']),
            ])
            for provider in providers:
                try:
                    status_data = provider._myfatoorah_make_request(
                        '/v2/GetPaymentStatus',
                        {'Key': payment_id, 'KeyType': 'PaymentId'},
                    )
                    ref = status_data.get('CustomerReference')
                    inv_id = status_data.get('InvoiceId')
                    if ref:
                        tx = self.search([
                            ('reference', '=', ref),
                            ('provider_code', '=', 'myfatoorah'),
                        ], limit=1)
                        if tx:
                            return tx
                    if inv_id:
                        tx = self.search([
                            ('provider_reference', '=', str(inv_id)),
                            ('provider_code', '=', 'myfatoorah'),
                        ], limit=1)
                        if tx:
                            return tx
                except Exception as e:
                    _logger.warning(
                        "MyFatoorah: Error querying payment status for lookup: %s", str(e),
                    )
                    continue

        raise ValidationError(_(
            "MyFatoorah: No transaction found matching the notification data "
            "(reference: %(ref)s, paymentId: %(pid)s, invoiceId: %(iid)s).",
            ref=reference, pid=payment_id, iid=invoice_id,
        ))

    def _process_notification_data(self, notification_data):
        """ Override of `payment` to process MyFatoorah notification data.

        Calls GetPaymentStatus to get the definitive payment status.

        :param dict notification_data: The notification data from callback/webhook.
        :return: None
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'myfatoorah':
            return

        payment_id = notification_data.get('paymentId')
        invoice_id = notification_data.get('InvoiceId') or self.provider_reference

        _logger.info(
            "MyFatoorah: Processing notification for tx %s (paymentId: %s, invoiceId: %s)",
            self.reference, payment_id, invoice_id,
        )

        # Determine the key for GetPaymentStatus
        if payment_id:
            key = payment_id
            key_type = 'PaymentId'
        elif invoice_id:
            key = invoice_id
            key_type = 'InvoiceId'
        else:
            _logger.error(
                "MyFatoorah: No paymentId or invoiceId in notification for tx %s",
                self.reference,
            )
            self._set_error(_(
                "MyFatoorah: Missing payment identification in the notification."
            ))
            return

        # Call GetPaymentStatus
        try:
            status_data = self.provider_id._myfatoorah_make_request(
                '/v2/GetPaymentStatus',
                {'Key': str(key), 'KeyType': key_type},
            )
        except ValidationError as e:
            _logger.error(
                "MyFatoorah: Error getting payment status for tx %s: %s",
                self.reference, str(e),
            )
            self._set_error(_(
                "MyFatoorah: Failed to verify payment status."
            ))
            return

        _logger.info(
            "MyFatoorah: Payment status response for tx %s:\n%s",
            self.reference, pprint.pformat(status_data),
        )

        # Extract status
        invoice_status = status_data.get('InvoiceStatus', '').lower()
        invoice_id_resp = status_data.get('InvoiceId')

        if invoice_id_resp and not self.provider_reference:
            self.provider_reference = str(invoice_id_resp)

        # Get the latest transaction from InvoiceTransactions
        transactions = status_data.get('InvoiceTransactions', [])
        latest_tx = None
        if transactions:
            latest_tx = transactions[-1]
            tx_status = latest_tx.get('TransactionStatus', '').lower()
        else:
            tx_status = invoice_status

        _logger.info(
            "MyFatoorah: Transaction %s — invoice_status: %s, tx_status: %s",
            self.reference, invoice_status, tx_status,
        )

        # Map MyFatoorah statuses to Odoo states
        if invoice_status == 'paid' or tx_status == 'succss':
            self._set_done()
        elif invoice_status in ('pending', 'initiated') or tx_status in ('pending', 'initiated'):
            self._set_pending()
        elif invoice_status in ('expired', 'canceled') or tx_status in ('expired', 'canceled'):
            self._set_canceled(state_message=_(
                "MyFatoorah: Payment was %(status)s.",
                status=invoice_status or tx_status,
            ))
        elif invoice_status == 'failed' or tx_status == 'failed':
            error_msg = ''
            if latest_tx:
                error_msg = latest_tx.get('Error', '') or latest_tx.get('ErrorCode', '')
            self._set_error(_(
                "MyFatoorah: Payment failed. %(error)s",
                error=error_msg,
            ))
        else:
            _logger.warning(
                "MyFatoorah: Unknown payment status for tx %s: invoice=%s, tx=%s",
                self.reference, invoice_status, tx_status,
            )
            self._set_error(_(
                "MyFatoorah: Received unknown payment status: %(status)s",
                status=invoice_status or tx_status or 'unknown',
            ))
