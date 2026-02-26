from odoo import models, fields, api, _
from odoo.exceptions import AccessError, UserError, ValidationError
import time
import datetime
from datetime import date
from odoo.tools.misc import formatLang, format_date, get_lang
from odoo.tools.translate import _
from odoo.tools import append_content_to_html, DEFAULT_SERVER_DATE_FORMAT, html2plaintext
from odoo.addons.account_followup.models.account_followup_report import AccountFollowupReport
import logging
_logger = logging.getLogger(__name__)

def _send_email1(self, options):
        """
        Send by email the followup to the customer's followup contacts
        """
        partner = self.env['res.partner'].browse(options.get('partner_id'))
        followup_contacts = partner._get_all_followup_contacts() or partner
        followup_recipients = options.get('email_recipient_ids', followup_contacts)
        sent_at_least_once = False
        for to_send_partner in followup_recipients:
            email = to_send_partner.email
            if email and email.strip():
                self = self.with_context(lang=partner.lang or self.env.user.lang)
                body_html = self.with_context(mail=True).get_followup_report_html(options)
                attachment_ids = options.get('attachment_ids', partner._get_invoices_to_print(options).message_main_attachment_id.ids)
                author_id = options.get('author_id', self.env.ref('base.partner_root').id)
                action = self.env.ref('account_followup.action_report_followup')
                tz_date_str = format_date(self.env, fields.Date.today(), lang_code=self.env.user.lang or get_lang(self.env).code)
                tz_date_str = tz_date_str.replace('.', '-')
                followup_letter_name = _("Statement %s - %s", partner.display_name, tz_date_str)
                followup_letter = action.with_context(lang=partner.lang or self.env.user.lang)._render_qweb_pdf('account_followup.report_followup_print_all', partner.id, data={'options': options or {}})[0]
                attachment = self.env['ir.attachment'].create({
                    'name': followup_letter_name,
                    'raw': followup_letter,
                    'res_id': partner.id,
                    'res_model': 'res.partner',
                    'type': 'binary',
                    'mimetype': 'application/pdf',
                })
                if attachment:
                    attachment_ids += [attachment.id]
                #till
                partner.with_context(mail_post_autofollow=True, mail_notify_author=True, lang=partner.lang or self.env.user.lang).message_post(
                    partner_ids=[to_send_partner.id],
                    author_id=author_id,
                    email_from=self._get_email_from(options),
                    body=body_html,
                    subject=self._get_email_subject(options),
                    reply_to=self._get_email_reply_to(options),
                    model_description=_('payment reminder'),
                    email_layout_xmlid='mail.mail_notification_light',
                    attachment_ids=attachment_ids,
                    subtype_id=self.env['ir.model.data']._xmlid_to_res_id('mail.mt_note'),
                )
                sent_at_least_once = True
        if not sent_at_least_once:
            raise UserError(_("You are trying to send an Email, but no follow-up contact has any email address set for customer '%s'", partner.name))
AccountFollowupReport._send_email = _send_email1

@api.model
def _print_followup_letter1(self, partner, options=None):
    """Generate the followup letter for the given partner.
    The letter is saved as ir.attachment and linked in the chatter.

    Returns a client action downloading this letter and closing the wizard.
    """
    action = self.env.ref('account_followup.action_report_followup')
    tz_date_str = format_date(self.env, fields.Date.today(), lang_code=self.env.user.lang or get_lang(self.env).code)
    #to avoid having dots in the name of the file.
    tz_date_str = tz_date_str.replace('.', '-')
    followup_letter_name = _("Statement %s - %s", partner.display_name, tz_date_str)
    followup_letter = action.with_context(lang=partner.lang or self.env.user.lang)._render_qweb_pdf('account_followup.report_followup_print_all', partner.id, data={'options': options or {}})[0]
    attachment = self.env['ir.attachment'].create({
        'name': followup_letter_name,
        'raw': followup_letter,
        'res_id': partner.id,
        'res_model': 'res.partner',
        'type': 'binary',
        'mimetype': 'application/pdf',
    })
    partner.message_post(body=_('Statment generated'), attachment_ids=[attachment.id])
    return {
        'type': 'ir.actions.client',
        'tag': 'close_followup_wizard',
        'params': {
            'url': '/web/content/%s?download=1' % attachment.id,
        }
    }
AccountFollowupReport._print_followup_letter = _print_followup_letter1

def _get_bucket_boundaries(today, step_days):
    buckets = []
    for i in range(7):
        end_offset = i * step_days
        start_offset = (i + 1) * step_days - 1
        date_to_b = today - datetime.timedelta(days=end_offset)
        date_from_b = today - datetime.timedelta(days=start_offset)
        label = f'{(i + 1) * step_days} Days'
        buckets.append((label, date_from_b, date_to_b))
    # oldest bucket
    oldest_boundary = today - datetime.timedelta(days=7 * step_days)
    buckets.append(('older', None, oldest_boundary - datetime.timedelta(days=1)))
    return buckets


class AgingBucket(models.AbstractModel):
    _inherit = 'account.followup.report'

    def _get_aging_step(self):
        mode = getattr(self.env.company, 'aging_period_mode', '7') or '7'
        return 30 if mode == '30' else 7

    def _get_followup_report_columns_name(self):
        result = super(AgingBucket, self)._get_followup_report_columns_name()
        result = [
            {'name': _('Date'), 'class': 'date', 'style': 'text-align:center !important; white-space:nowrap;'},
            {'name': _('Reference'), 'style': 'text-align:center !important; white-space:nowrap;'},
            {'name': _('Description'), 'style': 'text-align:center; white-space:nowrap; width:30% !important;'},
            {'name': _('Allocated To'),  'style': 'text-align:center !important;white-space:nowrap;'},
            {'name': _('Debit'), 'class': 'number o_price_total', 'style': 'text-align:center !important;'},
            {'name': _('Credit'), 'class': 'number o_price_total', 'style': 'text-align:center !important;'},
            {'name': _('Balance'), 'class': 'number o_price_total', 'style': 'text-align:center !important; white-space:nowrap;'},
            {'name': _('O/S Bal'), 'class': 'number o_price_total', 'style': 'text-align:center !important;white-space:nowrap;'},
        ]
        return result

    def _get_report_name(self):
        """
        Override
        Return the name of the report
        """
        return _('Customer Statement')

    def _get_followup_report_lines(self, options):
        """
        Compute and return the lines of the columns of the follow-ups report.
        """
        # Get date format for the lang
        partner = options.get('partner_id') and self.env['res.partner'].browse(options['partner_id']) or False
        if not partner:
            return []

        lang_code = partner.lang
        lines = []
        res = {}
        today = fields.Date.today()
        columns=[]

        for l in partner.unreconciled_aml_ids: #a_ids : #partner.unreconciled_aml_ids.sorted().filtered(lambda aml: not aml.currency_id.is_zero(aml.amount_residual_currency)):
            if l.company_id == self.env.company and not l.blocked:
                currency = l.currency_id or l.company_id.currency_id
                if currency not in res:
                    res[currency] = []
                res[currency].append(l)
        for currency, aml_recs in res.items():
            total = 0
            total_issued = 0
            total_amount_due = 0
            line_num = 0
            for aml in aml_recs:
                if self.env.context.get('fdate'):
                    t_date=self.env.context.get('fdate')
                else:
                    t_date = fields.Date.today()
                aml_date=datetime.datetime.strptime(str(aml.date), "%Y-%m-%d").date()
                if t_date >= aml_date:
                    amount = aml.amount_residual_currency if aml.currency_id else aml.amount_residual
                    invoice_date = {
                        'name': format_date(self.env, aml.move_id.invoice_date or aml.date, lang_code=lang_code),
                        'class': 'date',
                        'style': 'white-space:nowrap;text-align:center;'
                    }
                    date_due = format_date(self.env, aml.date_maturity or aml.move_id.invoice_date or aml.date, lang_code=lang_code)
                    total += not aml.blocked and amount or 0
                    is_overdue = today > aml.date_maturity if aml.date_maturity else today > aml.date
                    is_payment = aml.payment_id
                    if is_overdue or is_payment:
                        total_issued += not aml.blocked and amount or 0
                    date_due = {'name': date_due, 'class': 'date', 'style': 'white-space:nowrap;text-align:center;'}
                    if is_overdue:
                        date_due['style'] += 'color: red;'
                    if is_payment:
                        date_due = ''
                    move_line_name = {
                        'name': self._followup_report_format_aml_name(aml.name, aml.move_id.ref) or '-',
                        'style': 'text-align:center; white-space:normal;'
                    }

                    amount = formatLang(self.env, amount, currency_obj=currency)
                    amount = {
                        'name': amount,
                        'style': 'text-align:center; white-space:normal;',
                    }
                    line_num += 1
                    invoice_origin = aml.move_id.invoice_origin or '-'
                    if len(invoice_origin) > 43:
                        invoice_origin = invoice_origin[:40] + '...'
                    invoice_origin = {
                        'name': invoice_origin,
                        'style': 'text-align:center; white-space:normal;',
                    }

                    ref = aml.move_id.name or '-'
                    allocate_to = ''
                    if aml.amount_residual_currency:
                        invoice_amt = aml.amount_residual_currency
                    else:
                        invoice_amt = aml.move_id.amount_total
                    outstaging_bal = formatLang(self.env, invoice_amt, currency_obj=currency)
                    outstaging_bal = {
                        'name': outstaging_bal,
                        'style': 'text-align:right !important;white-space:normal;',
                    }
                    if aml.amount_residual_currency != aml.move_id.amount_total:
                        debt_amt = aml.amount_residual_currency
                    else:
                        debt_amt = aml.move_id.amount_total
                    total_amount_due += (debt_amt - aml.credit)
                    debit = formatLang(self.env, debt_amt, currency_obj=currency)

                    debit = {
                        'name': debit,
                        'style': 'text-align:right !important;',
                    }

                    credit = formatLang(self.env, aml.credit, currency_obj=currency)
                    credit = {
                        'name': credit,
                        'style': 'text-align:right !important;',
                    }

                    total_amount_due_dict = {
                        'name': formatLang(self.env, total_amount_due, currency_obj=currency),
                        'style': 'text-align:center; white-space:normal;',
                    }

                    columns = [
                        invoice_date,
                        ref,
                        move_line_name,
                        allocate_to,
                        debit,
                        credit,
                        total_amount_due_dict,
                        outstaging_bal,
                    ]
                    lines.append({
                        'id': aml.id,
                        'account_move': aml.move_id,
                        'name': aml.move_id.name,
                        'move_id': aml.move_id.id,
                        'type': is_payment and 'payment' or 'unreconciled_aml',
                        'unfoldable': False,
                        'columns': [isinstance(v, dict) and v or {'name': v} for v in columns],
                        'template': 'account_followup.cell_template_followup_report',
                    })
            line_num += 1
            lines.append({
                'id': line_num,
                'name': '',
                'class': '',
                'style': 'border-bottom-style: none',
                'unfoldable': False,
                'level': 0,
                'columns': [{} for col in columns],
                'template': 'account_followup.cell_template_followup_report',
            })
        # Remove the last empty line
        if lines:
            lines.pop()
        return lines

    def _age_analysis_get(self, data, statement_date):
        step = self._get_aging_step()

        if isinstance(statement_date, str):
            today = datetime.datetime.strptime(statement_date, '%Y-%m-%d').date()
        else:
            today = statement_date

        # Build bucket boundaries
        buckets = _get_bucket_boundaries(today, step)
        # values dict: 'bucket_0'...'bucket_6', 'older'
        values = {f'bucket_{i}': 0.0 for i in range(7)}
        values['older'] = 0.0

        recon = {}
        for line in data:
            recon_id = line['full_reconcile_id']
            if recon_id and line['debit']:
                recon[recon_id] = line['date']

        def _get_period( tr_date ):
            if not tr_date:
                return 'older'
            if isinstance(tr_date, str):
                tr_date = datetime.datetime.strptime(str(tr_date), '%Y-%m-%d').date()
            for idx, (label, date_from, date_to) in enumerate(buckets[:-1]):
                if date_from <= tr_date <= date_to:
                    return f'bucket_{idx}'
            return 'older'

        for line in data[::-1]:
            statement_date_obj = today
            if (line.full_reconcile_id):
                dates = fields.Date.from_string(line.full_reconcile_id.create_date)
                statement_date = datetime.datetime.strptime(str(statement_date), '%Y-%m-%d').date()
            if (line.full_reconcile_id and dates <= statement_date):
                continue
            else:
                debit = line['debit']
                credit = line['credit']

                tdate = line.date
                period_key = _get_period(tdate)
                diff = values[period_key] + debit - credit

                for partial_line in line.matched_debit_ids:
                    if partial_line.debit_move_id.date <= statement_date_obj:
                        diff += partial_line.amount
                for partial_line in line.matched_credit_ids:
                    if partial_line.credit_move_id.date <= statement_date_obj:
                        diff -= partial_line.amount

                values[period_key] = diff

            values[period_key] = diff
            values['cur'] = line.partner_id.currency_id.symbol

        # Attach metadata for template rendering
        values['step'] = step
        values['labels'] = [b[0] for b in buckets]  # e.g. ['7 Days', '14 Days', ..., 'older']
        return values

    @api.model
    def get_ageing_bucket(self, options):
        aml_obj = self.env['account.move.line']
        if self.env.context.get('fdate'):
            today = self.env.context.get('fdate')
        else:
            today = fields.date.today()
        aml_lines = aml_obj.search([('partner_id','=',options['partner_id']),('reconciled', '=', False),('move_id.state', 'in', ['posted']),('date','<=',today),('account_id.account_type', 'in', ['asset_receivable']),('blocked', '=', False)])
        dict1 = self._age_analysis_get(aml_lines, today)
        if not dict1.get('cur',0):
            partner = self.env['res.partner'].browse(options['partner_id'])
            dict1['cur'] = partner.currency_id.symbol
        return dict1

    def get_followup_report_html(self, options):
        """
        Override
        Compute and return the content in HTML of the followup for the partner_id in options
        """
        if options is None:
            options = {}
            options['followup_line'] = self._get_followup_report_lines(options)
        partner = self.env['res.partner'].browse(options['partner_id'])
        options['partner'] = partner
        options['lang'] = partner.lang or get_lang(self.env).code
        options['invoice_address_id'] = self.env['res.partner'].browse(partner.address_get(['invoice'])['invoice'])
        if self.env.context.get('fdate'):
            options['today'] = datetime.datetime.strptime(str(self.env.context.get('fdate')), "%Y-%m-%d").date()
        else:
            options['today'] = fields.Date.today().strftime(DEFAULT_SERVER_DATE_FORMAT)
        return super(AgingBucket,self).get_followup_report_html(options)


class AgingBucketPartner(models.Model):
    _inherit = 'res.partner'

    def get_followup_aging(self,options=None):
        if options is None:
            options = {}
        options.update({
            'partner_id': self.id,
            'followup_line_id': self.followup_line_id,
            'keep_summary': True
        })
        ctx = self.env.context
        if ctx.get('fdate'):
            return self.env['account.followup.report'].with_context(print_mode=True, lang=self.lang or self.env.user.lang, fdate=ctx.get('fdate')).get_ageing_bucket(options)
        return self.env['account.followup.report'].with_context(print_mode=True, lang=self.lang or self.env.user.lang).get_ageing_bucket(options)

    def get_followup_html(self,options=None):
        if options is None:
            options = {}
        options.update({
            'partner_id': self.id,
            'followup_line_id': self.followup_line_id,
            'keep_summary': True
        })
        ctx = self.env.context
        if ctx.get('fdate'):
            options['today'] = datetime.datetime.strptime(str(ctx.get('fdate')), "%Y-%m-%d").date()
            return self.env['account.followup.report'].with_context(print_mode=True, lang=self.lang or self.env.user.lang, fdate=ctx.get('fdate')).get_followup_report_html(options)

        return self.env['account.followup.report'].with_context(print_mode=True, lang=self.lang or self.env.user.lang).get_followup_report_html(options)

class MailComposeMessageInherit(models.TransientModel):
    _inherit = 'mail.compose.message'

    follow_up_date = fields.Date(string="Followup Date")

    def action_send_mail(self):
        if self.follow_up_date:
            self.with_context(fdate=self.follow_up_date)._action_send_mail(auto_commit=False)
        else:
            self._action_send_mail(auto_commit=False)
        return {'type': 'ir.actions.act_window_close'}

class ResCompany(models.Model):
    _inherit = 'res.company'
    
    account_number = fields.Char(string="Account Number")

    aging_period_mode = fields.Selection(
        selection=[('7', 'Weekly (7-day buckets)'), ('30', 'Monthly (30-day buckets)')],
        string='Aging Period Mode',
        default='7',
        required=True,
        help="Controls the aging bucket interval used in Aged Receivable/Payable reports and Follow-up statements.\n"
             "• Weekly: 7, 14, 21, 28, 35, 42, 49 days\n"
             "• Monthly: 30, 60, 90, 120, 150, 180, 210 days",
    )

class FollowupManualReminderInherit(models.TransientModel):
    _inherit = 'account_followup.manual_reminder'

    print_follow_up_date = fields.Date(string="Followup Date")

    def process_followup(self):
        """ Method run by pressing the 'Send and Print' button in the wizard.
        It will process the followup for the active partner, taking into account the fields from the wizard.
        Send email/sms and print the followup letter (pdf) depending on which is activated.
        Once the followup has been processed, we simply close the wizard.
        """
        options = self._get_wizard_options()
        options['author_id'] = self.env.user.partner_id.id
        if self.print_follow_up_date:
            action = self.partner_id.with_context(fdate=self.print_follow_up_date).execute_followup(options)
        else:
            action = self.partner_id.execute_followup(options)
        return action or {
            'type': 'ir.actions.act_window_close',
        }
