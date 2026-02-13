# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Payment Provider: MyFatoorah',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "MyFatoorah payment gateway for MENA region eCommerce.",
    'description': " ",  # Non-empty string to avoid loading the README file.
    'depends': ['payment', 'website_sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/payment_provider_views.xml',
        'views/payment_myfatoorah_templates.xml',
        'data/payment_provider_data.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'assets': {},
    'author': 'MyFatoorah Custom',
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
