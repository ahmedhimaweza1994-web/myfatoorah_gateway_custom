# MyFatoorah Payment Gateway — Odoo 19 Enterprise

Fully integrated MyFatoorah payment gateway module for Odoo 19 Enterprise eCommerce.
Supports all MENA region countries with Live and Sandbox environments.

---

## Features

- **Full payment flow**: Redirect customer to MyFatoorah hosted payment page
- **Sandbox & Live**: Switch between test and production modes
- **Country-specific**: Auto-selects correct API endpoint per country (SA, KW, BH, AE, QA, EG, OM, JO)
- **Webhook v2**: HMAC-SHA256 signature verification for secure event processing
- **Comprehensive logging**: All API requests, responses, and webhook events logged
- **eCommerce ready**: Works with Odoo 19 Website Sale checkout

---

## Installation

1. **Copy the module** to your Odoo 19 custom addons directory:

   ```bash
   cp -r myfatoorah_gateway_custom /path/to/odoo/custom_addons/
   ```

2. **Update the addons path** in `odoo.conf`:

   ```ini
   addons_path = /path/to/odoo/addons,/path/to/odoo/custom_addons
   ```

3. **Restart Odoo** and update the module list:

   ```
   Settings → Apps → Update Apps List
   ```

4. **Install the module**: Search for "MyFatoorah" in the Apps menu and click **Install**.

---

## Configuration

### Step 1: Open Payment Provider Settings

Navigate to: **Website → Configuration → Payment Providers → MyFatoorah**

### Step 2: Configure API Keys

| Field | Description |
|---|---|
| **Live Secret Key** | Your production API Token Key from MyFatoorah dashboard → Integration Settings |
| **Test Secret Key** | Your sandbox API Token Key from [MyFatoorah Demo Portal](https://demo.myfatoorah.com/) |
| **Country** | Select your MyFatoorah account country (determines the live API URL) |

### Step 3: Set Provider State

- **Test Mode**: Uses sandbox API (`https://apitest.myfatoorah.com`) with Test Secret Key
- **Enabled**: Uses live API (country-specific URL) with Live Secret Key

### Step 4: Configure Callback URLs in MyFatoorah Dashboard

In your MyFatoorah portal (dashboard), set these callback URLs:

| URL Type | URL |
|---|---|
| **Success URL** | `https://your-odoo-domain.com/payment/myfatoorah/return` |
| **Error URL** | `https://your-odoo-domain.com/payment/myfatoorah/error` |
| **Webhook URL** | `https://your-odoo-domain.com/payment/myfatoorah/webhook` |

> **Note**: Replace `your-odoo-domain.com` with your actual Odoo domain. MyFatoorah does **not** accept `localhost` URLs.

### Step 5: Webhook Configuration (Optional)

1. In the MyFatoorah payment provider form, check **Enable Webhooks**
2. Enter your **Webhook Secret Key** (from MyFatoorah portal → Webhook Settings)
3. The webhook URL is: `https://your-odoo-domain.com/payment/myfatoorah/webhook`
4. MyFatoorah will send events for: Payment Status Changes, Refund Status Changes, Balance Transfers

---

## API URL Mapping

| Country | Live API URL |
|---|---|
| Saudi Arabia (SA) | `https://api-sa.myfatoorah.com` |
| Kuwait (KW) | `https://api.myfatoorah.com` |
| Bahrain (BH) | `https://api.myfatoorah.com` |
| UAE (AE) | `https://api-ae.myfatoorah.com` |
| Qatar (QA) | `https://api-qa.myfatoorah.com` |
| Egypt (EG) | `https://api-eg.myfatoorah.com` |
| Oman (OM) | `https://api.myfatoorah.com` |
| Jordan (JO) | `https://api.myfatoorah.com` |
| **Test (all)** | `https://apitest.myfatoorah.com` |

---

## Payment Flow

1. Customer adds items to cart and proceeds to checkout
2. Customer selects **MyFatoorah** as payment method and clicks **Pay Now**
3. Odoo calls `POST /v2/SendPayment` to create a MyFatoorah invoice
4. Customer is redirected to the MyFatoorah hosted payment page
5. After payment, customer is redirected back to Odoo (success or error URL)
6. Odoo calls `POST /v2/GetPaymentStatus` to verify the payment
7. Transaction is updated to Done, Pending, Canceled, or Error accordingly
8. (Optional) MyFatoorah sends a webhook event for asynchronous status updates

---

## Troubleshooting

### Check Logs

All API communication is logged. Check the Odoo server logs:

```bash
grep "MyFatoorah" /var/log/odoo/odoo-server.log
```

### Common Issues

| Issue | Solution |
|---|---|
| "Missing API key" error | Configure the correct secret key for your provider state (Test/Live) |
| Redirect not working | Ensure your domain is HTTPS and not localhost |
| Webhook signature fails | Verify the webhook secret key matches your MyFatoorah portal settings |
| "No transaction found" | Check that the `CustomerReference` matches the Odoo transaction reference |

---

## Module Structure

```
myfatoorah_gateway_custom/
├── __init__.py
├── __manifest__.py
├── README.md
├── controllers/
│   ├── __init__.py
│   └── main.py
├── data/
│   ├── payment_method_data.xml
│   └── payment_provider_data.xml
├── models/
│   ├── __init__.py
│   ├── payment_provider.py
│   └── payment_transaction.py
├── security/
│   └── ir.model.access.csv
├── static/
│   └── description/
│       └── icon.png
└── views/
    ├── payment_myfatoorah_templates.xml
    └── payment_provider_views.xml
```

---

## License

LGPL-3.0 — See [LICENSE](https://www.gnu.org/licenses/lgpl-3.0.html)
