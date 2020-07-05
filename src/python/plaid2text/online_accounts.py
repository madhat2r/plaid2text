#! /usr/bin/env python3

from collections import OrderedDict
import datetime
import os
import sys
import textwrap

from plaid import Client
from plaid import errors as plaid_errors

import plaid2text.config_manager as cm
from plaid2text.interact import prompt, clear_screen, NullValidator
from plaid2text.interact import NumberValidator, NumLengthValidator, YesNoValidator, PATH_COMPLETER


class PlaidAccess():
    def __init__(self, client_id=None, secret=None):
        if client_id and secret:
            self.client_id = client_id
            self.secret = secret
        else:
            self.client_id, self.secret = cm.get_plaid_config()

        self.client = Client(self.client_id, self.secret, "development", suppress_warnings=True)

    def get_transactions(self,
                         access_token,
                         start_date,
                         end_date,
                         account_ids=None):
        """Get transaction for a given account for the given dates"""

        ret = []
        total_transactions = None
        page = 0
        while True:
            page += 1 
            if total_transactions:
                print("Fetching page %d, already fetched %d/%d transactions" % ( page, len(ret), total_transactions))
            else:
                print("Fetching page 1")

            try:
                response = self.client.Transactions.get(
                                access_token,
                                start_date.strftime("%Y-%m-%d"),
                                end_date.strftime("%Y-%m-%d"),
                                account_ids=account_ids,
                                offset=len(ret))
            except plaid_errors.ItemError as ex:
                print("Unable to update plaid account [%s] due to: " % account_ids, file=sys.stderr)
                print("    %s" % ex, file=sys.stderr )
                sys.exit(1)

            total_transactions = response['total_transactions']

            ret.extend(response['transactions'])

            if len(ret) >= total_transactions: break

        print("Downloaded %d transactions for %s - %s" % ( len(ret), start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")))

        return ret
