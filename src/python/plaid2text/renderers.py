#! /usr/bin/env python3

from abc import ABCMeta, abstractmethod
import csv
import os
import re
import subprocess
import sys

import plaid2text.config_manager as cm
from plaid2text.interact import separator_completer, prompt


class Entry:
    """
    This represents one entry (transaction) from Plaid.
    """

    def __init__(self, transaction, options={}):
        """Parameters:
        transaction: a plaid transaction

        options: from CLI args and config file
        """
        self.options = options

        self.transaction = transaction
        # TODO: document this
        if 'addons' in options:
            self.transaction['addons'] = dict(
                (k, fields[v - 1]) for k, v in options.addons.items()  # NOQA
            )
        else:
            self.transaction['addons'] = {}

        # The id for the transaction
        self.transaction['transaction_id'] = self.transaction['transaction_id']

        # Get the date and convert it into a ledger/beancount formatted date.
        d8 = self.transaction['date']
        d8_format = options.output_date_format if options and 'output_date_format' in options else '%Y-%m-%d'
        self.transaction['transaction_date'] = d8.date().strftime(d8_format)

        self.desc = self.transaction['name']

        # amnt = self.transaction['amount']
        self.transaction['currency'] = options.currency
        # self.transaction['debit_amount'] = amnt
        # self.transaction['debit_currency'] = currency
        # self.transaction['credit_amount'] = ''
        # self.transaction['credit_currency'] = ''

        self.transaction['posting_account'] = options.posting_account
        self.transaction['cleared_character'] = options.cleared_character

        if options.template_file:
            with open(options.template_file, 'r', encoding='utf-8') as f:
                self.transaction['transaction_template'] = f.read()
        else:
            self.transaction['transaction_template'] = ''

    def query(self):
        """
        We print a summary of the record on the screen, and allow you to
        choose the destination account.
        """
        return '{0} {1:<40} {2}'.format(
            self.transaction['date'],
            self.desc,
            self.transaction['amount']
        )

    def journal_entry(self, payee, account, tags):
        """
        Return a formatted journal entry recording this Entry against
        the specified posting account
        """
        if self.options.output_format == 'ledger':
            def_template = cm.DEFAULT_LEDGER_TEMPLATE
        else:
            def_template = cm.DEFAULT_BEANCOUNT_TEMPLATE
        if self.transaction['transaction_template']:
            template = (self.transaction['transaction_template'])
        else:
            template = (def_template)
        if self.options.output_format == 'beancount':
            ret_tags = ' {}'.format(tags) if tags else ''
        else:
            ret_tags = ' ; {}'.format(tags) if tags else ''

        format_data = {
            'associated_account': account,
            'payee': payee,
            'tags': ret_tags
        }
        format_data.update(self.transaction['addons'])
        format_data.update(self.transaction)
        return template.format(**format_data)


class OutputRenderer(metaclass=ABCMeta):
    """
    Base class for output rendering.
    """
    def __init__(self, transactions, options):
        self.transactions = transactions
        self.possible_accounts = set([])
        self.possible_payees = set([])
        self.possible_tags = set([])
        self.mappings = []
        self.map_file = options.mapping_file
        self.read_mapping_file()
        self.journal_file = options.journal_file
        self.journal_lines = []
        self.options = options
        self.get_possible_accounts_and_payees()
        # Add payees/accounts/tags from mappings
        for m in self.mappings:
            self.possible_payees.add(m[1])
            self.possible_accounts.add(m[2])
            if m[3]:
                if options.output_format == 'ledger':
                    self.possible_tags.update(set(m[3][0].split(':')))
                else:
                    self.possible_tags.update([t.replace('#', '') for t in m[3][0].split(' ')])

    def read_mapping_file(self):
        """
        Mappings are simply a CSV file with three columns.
        The first is a string to be matched against an entry description.
        The second is the payee against which such entries should be posted.
        The third is the account against which such entries should be posted.

        If the match string begins and ends with '/' it is taken to be a
        regular expression.
        """
        if not self.map_file:
            return

        with open(self.map_file, 'r', encoding='utf-8', newline='') as f:
            map_reader = csv.reader(f)
            for row in map_reader:
                if len(row) > 1:
                    pattern = row[0].strip()
                    payee = row[1].strip()
                    account = row[2].strip()
                    tags = row[3:]
                    if pattern.startswith('/') and pattern.endswith('/'):
                        try:
                            pattern = re.compile(pattern[1:-1], re.I)
                        except re.error as e:
                            print(
                                "Invalid regex '{0}' in '{1}': {2}"
                                .format(pattern, self.map_file, e),
                                file=sys.stderr)
                            sys.exit(1)
                    self.mappings.append((pattern, payee, account, tags))

    def append_mapping_file(self, desc, payee, account, tags):
        if self.map_file:
            with open(self.map_file, 'a', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                ret_tags = tags if len(tags) > 0 else ''
                writer.writerow([desc, payee, account, ret_tags])

    def process_transactions(self, callback=None):
        """
        Read transactions from Mongo (Plaid) and
        process them. Writes Ledger/Beancount formatted
        lines either to out_file or stdout.

        Parameters:
        callback: A function taking a single transaction update object to store
                  in the DB immediately after collecting the information from the user.
        """
        out = self._process_plaid_transactions(callback=callback)

        if self.options.headers_file:
            headers = ''.join(open(self.options.headers_file, mode='r').readlines())
            print(headers, file=self.options.outfile)
        print(*self.journal_lines, sep='\n', file=self.options.outfile)
        return out 

    def _process_plaid_transactions(self, callback=None):
        """Process plaid transaction and return beancount/ledger formatted
        lines.
        """
        out = []
        for t in self.transactions:
            entry = Entry(t, self.options)
            payee, account, tags = self.get_payee_and_account(entry)
            dic = {}
            dic['transaction_id'] = t['transaction_id']
            dic['tags'] = tags
            dic['associated_account'] = account
            dic['payee'] = payee
            dic['posting_account'] = self.options.posting_account
            out.append(dic)

            # save the transactions into the database as they are processed
            if callback: callback(dic)

            self.journal_lines.append(entry.journal_entry(payee, account, tags))
        return out

    def prompt_for_value(self, text_prompt, values, default):
        sep = ':' if text_prompt == 'Payee' else ' '
        a = prompt(
            '{} [{}]: '.format(text_prompt, default),
            completer=separator_completer(values, sep=sep)
        )
        # Handle tag returning none if accepting
        return a if (a or text_prompt == 'Tag') else default

    def get_payee_and_account(self, entry):
        payee = entry.desc
        account = self.options.default_expense
        tags = ''
        found = False
        # Try to match entry desc with mappings patterns
        for m in self.mappings:
            pattern = m[0]
            if isinstance(pattern, str):
                if entry.desc == pattern:
                    payee, account, tags = m[1], m[2], m[3]
                    found = True  # do not break here, later mapping must win
            else:
                # If the pattern isn't a string it's a regex
                if m[0].match(entry.desc):
                    payee, account, tags = m[1], m[2], m[3]
                    found = True
        # Tags gets read in as a list, but just contains one string
        if tags:
            tags = tags[0]

        modified = False
        if self.options.quiet and found:
            pass
        else:
            if self.options.clear_screen:
                print('\033[2J\033[;H')
            print('\n' + entry.query())

            value = self.prompt_for_value('Payee', self.possible_payees, payee)
            if value:
                modified = modified if modified else value != payee
                payee = value

            value = self.prompt_for_value('Account', self.possible_accounts, account)
            if value:
                modified = modified if modified else value != account
                account = value

            if self.options.tags:
                value = self.prompt_for_tags('Tag', self.possible_tags, tags)
                if value:
                    modified = modified if modified else value != tags
                    tags = value

        if not found or (found and modified):
            # Add new or changed mapping to mappings and append to file
            self.mappings.append((entry.desc, payee, account, tags))
            self.append_mapping_file(entry.desc, payee, account, tags)

            # Add new possible_values to possible values lists
            self.possible_payees.add(payee)
            self.possible_accounts.add(account)

        return (payee, account, tags)

    @abstractmethod
    def tagify(self, value):
        pass

    @abstractmethod
    def get_possible_accounts_and_payees(self):
        pass

    @abstractmethod
    def prompt_for_tags(self, prompt, values, default):
        pass


class LedgerRenderer(OutputRenderer):
    def tagify(self, value):
        if value.find(':') < 0 and value[0] != '[' and value[-1] != ']':
            value = ':{0}:'.format(value.replace(' ', '-').replace(',', ''))
            return value

    def get_possible_accounts_and_payees(self):
        if self.journal_file:
            self.possible_payees = self._payees_from_ledger()
            self.possible_accounts = self._accounts_from_ledger()
        self.read_accounts_file()

    def prompt_for_tags(self, prompt, values, default):
        # tags = list(default[0].split(':'))
        tags = [':{}:'.format(t) for t in default.split(':') if t] if default else []
        value = self.prompt_for_value(prompt, values, ''.join(tags).replace('::', ':'))
        while value:
            if value[0] == '-':
                value = self.tagify(value[1:])
                if value in tags:
                    tags.remove(value)
            else:
                value = self.tagify(value)
                if value not in tags:
                    tags.append(value)
            value = self.prompt_for_value(prompt, values, ''.join(tags).replace('::', ':'))
        return ''.join(tags).replace('::', ':')

    def _payees_from_ledger(self):
        return self._from_ledger('payees')

    def _accounts_from_ledger(self):
        return self._from_ledger('accounts')

    def _from_ledger(self, command):
        ledger = 'ledger'
        for f in ['/usr/bin/ledger', '/usr/local/bin/ledger']:
            if os.path.exists(f):
                ledger = f
                break

        cmd = [ledger, '-f', self.journal_file, command]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout_data, stderr_data) = p.communicate()
        items = set()
        for item in stdout_data.decode('utf-8').splitlines():
            items.add(item)
        return items

    def read_accounts_file(self):
        """ Process each line in the specified account file looking for account
            definitions. An account definition is a line containing the word
            'account' followed by a valid account name, e.g:

                account Expenses
                account Expenses:Utilities

            All other lines are ignored.
        """
        if not self.options.accounts_file:
            return
        accounts = []
        pattern = re.compile('^\s*account\s+([:A-Za-z0-9-_ ]+)$')
        with open(self.options.accounts_file, 'r', encoding='utf-8') as f:
            for line in f.readlines():
                mo = pattern.match(line)
                if mo:
                    accounts.append(mo.group(1))

        self.possible_accounts.update(accounts)


class BeancountRenderer(OutputRenderer):
    import beancount

    def tagify(self, value):
        # No spaces or commas allowed
        return value.replace(' ', '-').replace(',', '')

    def get_possible_accounts_and_payees(self):
        if self.journal_file:
            self._payees_and_accounts_from_beancount()

    def _payees_and_accounts_from_beancount(self):
        try:
            payees = set()
            accounts = set()
            tags = set()
            from beancount import loader
            from beancount.core.data import Transaction, Open
            import sys
            entries, errors, options = loader.load_file(self.journal_file)

        except Exception as e:
            print(e.message, file=sys.stderr)
            sys.exit(1)
        else:
            for e in entries:
                if type(e) is Transaction:
                    if e.payee:
                        payees.add(e.payee)
                    if e.tags:
                        for t in e.tags:
                            tags.add(t)
                    if e.postings:
                        for p in e.postings:
                            accounts.add(p.account)
                elif type(e) is Open:
                    accounts.add(e.account)

        self.possible_accounts.update(accounts)
        self.possible_tags.update(tags)
        self.possible_payees.update(payees)

    def prompt_for_tags(self, prompt, values, default):
        tags = ' '.join(['#{}'.format(t) for t in default.split() if t]) if default else []
        value = self.prompt_for_value(prompt, values, ' '.join(['#{}'.format(t) for t in tags]))
        while value:
            if value[0] == '-':
                value = self.tagify(value[1:])
                if value in tags:
                    tags.remove(value)
            else:
                value = self.tagify(value)
                if value not in tags:
                    tags.append(value)
            value = self.prompt_for_value(
                prompt,
                values,
                ' '.join(['#{}'.format(t) for t in tags])
            )
        return ' '.join(['#{}'.format(t) for t in tags])
