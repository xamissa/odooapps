{
        'name': 'Aging Bucket Follow up Report',
        'description': """
                The Aging Bucket Follow up Report module extends Odoo's native accounting capabilities with advanced partner aging analysis and customizable follow-up reporting. It provides businesses with powerful tools to manage accounts receivable more effectively through configurable aging periods and professional PDF reports.
         """,
        'author': 'ERPWEB',
        'depends': ['account_followup','account_reports'],
        'application': True,
        'version': '17.0.0.1',
        'support': 'helpdesk2@internal.odoo.zone',
        'website': 'www.erpweb.co.za',
        'installable': True,
        "data": [               
                'views/ageing_bucket.xml',
                'data/aged_partner_balance.xml',
        ],
       'assets': {
                'account_reports.assets_pdf_export': [
                    'erpweb_follow_up_report/static/src/scss/**/*',
                ],
                'web.report_assets_common': [
                    'erpweb_follow_up_report/static/src/scss/account_pdf_export_template.scss',
                ],
        },
        "price"       : 86.10,
        "currency"    : "USD",
        "images"      : ["static/description/banner.png",],
        'license'     : 'OPL-1',
}

