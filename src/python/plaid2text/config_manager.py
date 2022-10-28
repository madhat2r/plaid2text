#! /usr/bin/env python3

from collections import OrderedDict
import configparser
import os
import sys
import re

from plaid2text.interact import prompt, NullValidator, YesNoValidator
from plaid import Client
from plaid import errors as plaid_errors

import json


class dotdict(dict):
    """
    Enables dict.item syntax (instead of dict['item'])
    See http://stackoverflow.com/questions/224026
    """
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def get_locale_currency_symbol():
    """
    Get currency symbol from locale
    """
    import locale
    locale.setlocale(locale.LC_ALL, '')
    conv = locale.localeconv()
    return conv['int_curr_symbol']

DEFAULT_CONFIG_DIR = os.path.expanduser('~/.config/plaid2text')

CONFIG_DEFAULTS = dotdict({
    # For configparser, int must be converted to str
    # For configparser, boolean must be set to False
    'create_account': False,
    'posting_account': 'Assets:Bank:Checking',
    'output_format': 'beancount',
    'clear_screen': False,
    'cleared_character': '*',
    'currency': get_locale_currency_symbol(),
    'default_expense': 'Expenses:Unknown',
    'encoding': 'utf-8',
    'output_date_format': '%Y/%m/%d',
    'quiet': False,
    'tags': False,
    'dbtype': 'mongodb',
    'mongo_db': 'plaid2text',
    'mongo_db_uri': 'mongodb://localhost:27017',
    'sqlite_db': os.path.join(DEFAULT_CONFIG_DIR, 'transactions.db')
})

FILE_DEFAULTS = dotdict({
    'config_file': os.path.join(DEFAULT_CONFIG_DIR, 'config'),
    'accounts_file': os.path.join(DEFAULT_CONFIG_DIR, 'accounts'),
    'journal_file': os.path.join(DEFAULT_CONFIG_DIR, 'journal'),
    'mapping_file': os.path.join(DEFAULT_CONFIG_DIR, 'mapping'),
    'headers_file': os.path.join(DEFAULT_CONFIG_DIR, 'headers'),
    'template_file': os.path.join(DEFAULT_CONFIG_DIR, 'template'),
    'auth_file': os.path.join(DEFAULT_CONFIG_DIR, 'auth.html')})

DEFAULT_LEDGER_TEMPLATE = """\
{transaction_date} {cleared_character} {payee} {tags}
    ; plaid_name: {name}
    ; _id: {transaction_id}
    {associated_account:<60}   {currency} {amount}
    {posting_account:<60}
"""

DEFAULT_BEANCOUNT_TEMPLATE = """\
{transaction_date} {cleared_character} "{payee}" ""{tags}
    plaid_name: "{name}"
    plaid_id: "{transaction_id}"
    {associated_account:<60}   {amount} {currency}
    {posting_account}
"""


def touch(fname, mode=0o666, dir_fd=None, **kwargs):
    """
    Implementation of coreutils touch
    http://stackoverflow.com/a/1160227
    """
    flags = os.O_CREAT | os.O_APPEND
    with os.fdopen(os.open(fname, flags=flags, mode=mode, dir_fd=dir_fd)) as f:
        os.utime(f.fileno() if os.utime in os.supports_fd else fname,
                 dir_fd=None if os.supports_fd else dir_fd, **kwargs)


def get_custom_file_path(nickname, file_type, create_file=False):
    f = os.path.join(DEFAULT_CONFIG_DIR, nickname, file_type)
    if create_file:
        if not os.path.exists(f):
            _create_directory_tree(f)
        touch(f)
        if file_type == 'template':
            with open(f, mode='w') as temp:
                temp.write(DEFAULT_BEANCOUNT_TEMPLATE)
    return f


def config_exists():
    if not os.path.isfile(FILE_DEFAULTS.config_file):
        print('No configuration file found.')
        create = prompt(
            'Do you want to create one now [Y/n]: ',
            validator=YesNoValidator()
        ).lower()
        if not bool(create) or create.startswith('y'):
            return init_config()
        elif create.startswith('n'):
            raise Exception('No configuration file found')
    else:
        return True


def _get_config_parser():
    config = configparser.ConfigParser(CONFIG_DEFAULTS, interpolation=None)
    config.read(FILE_DEFAULTS.config_file)
    return config


def get_config(account):
    config = _get_config_parser()
    if not config.has_section(account):
        print(
            'Config file {0} does not contain section for account: {1}\n\n'
            'To create this account: run plaid2text {1} --create-account'.format(
                FILE_DEFAULTS.config_file,
                account
            ),
            file=sys.stderr
        )
        sys.exit(1)
    defaults = OrderedDict(config.items(account))
    defaults['plaid_account'] = account
    defaults['config_file'] = FILE_DEFAULTS.config_file
    defaults['addons'] = OrderedDict()
    for f in ['template_file', 'mapping_file', 'headers_file', 'journal_file', 'accounts_file']:
        if f in defaults:
            defaults[f] = os.path.expanduser(defaults[f])
    if config.has_section(account + '_addons'):
        for item in config.items(account + '_addons'):
            if item not in config.defaults().items():
                defaults['addons']['addon_' + item[0]] = int(item[1])
    return defaults


def get_configured_accounts():
    config = _get_config_parser()
    accts = config.sections()
    accts.remove('PLAID')  # Remove Plaid specific
    return accts


def account_exists(account):
    config = _get_config_parser()
    if not config.has_section(account):
        return False
    return True


def get_plaid_config():
    config = _get_config_parser()
    plaid_section = config['PLAID']
    return plaid_section['client_id'], plaid_section['secret']


def write_section(section_dict):
    config = _get_config_parser()
    try:
        config.read_dict(section_dict)
    except Exception as e:
        raise
    else:
        with open(FILE_DEFAULTS.config_file, mode='w') as f:
            config.write(f)


def init_config():
    try:
        _create_directory_tree(FILE_DEFAULTS.config_file)
        config = configparser.ConfigParser(interpolation=None)
        config['PLAID'] = OrderedDict()
        plaid = config['PLAID']
        client_id = prompt('Enter your Plaid client_id: ', validator=NullValidator())
        plaid['client_id'] = client_id
        secret = prompt('Enter your Plaid secret: ', validator=NullValidator())
        plaid['secret'] = secret
    except Exception as e:
        return False
    else:
        with open(FILE_DEFAULTS.config_file, mode='w') as f:
            config.write(f)
    return True


def _create_directory_tree(filename):
    """
    This will create the entire directory path for the config file
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)


def find_first_file(arg_file, alternatives):
    """Because of http://stackoverflow.com/questions/12397681,
    parser.add_argument(type= or action=) on a file can not be used
    """
    found = None
    file_locs = [arg_file] + [alternatives]
    for loc in file_locs:
        if loc is not None and os.access(loc, os.F_OK | os.R_OK):
            found = loc  # existing and readable
            break
    return found


def create_account(account):
    try:
        _create_directory_tree(FILE_DEFAULTS.config_file)
        config = configparser.ConfigParser(interpolation=None)
        config[account] = OrderedDict()
        plaid = config[account]
        client_id, secret = get_plaid_config()
        # client_id = prompt('Enter your Plaid client_id: ', validator=NullValidator())
        # plaid['client_id'] = client_id
        # secret = prompt('Enter your Plaid secret: ', validator=NullValidator())
        # plaid['secret'] = secret
        
        configs = {
            'user': {
                'client_user_id': '123-test-user-id',
            },
            'products': ['transactions'],
            'client_name': "Plaid Test App",
            'country_codes': ['US'],
            'language': 'en',
        }

        # create link token
        client = Client(client_id, secret, "development", suppress_warnings=True)
        response = client.LinkToken.create(configs)
        link_token = response['link_token']

        generate_auth_page(link_token)
        print("\n\nPlease open " + FILE_DEFAULTS.auth_file + " to authenticate your account with Plaid")
        public_token = prompt('Enter your public_token from the auth page: ', validator=NullValidator())
        # plaid['public_token'] = public_token

        response = client.Item.public_token.exchange(public_token)
        access_token = response['access_token']
        plaid['access_token'] = access_token
        item_id = response['item_id']
        plaid['item_id'] = item_id

        response = client.Accounts.get(access_token)

        accounts = response['accounts']

        print("\n\nAccounts:\n")
        for item in accounts:
            print(item['name'] + ":")
            print(item['account_id'])
        account_id = prompt('\nEnter account_id of desired account: ', validator=NullValidator())
        plaid['account'] = account_id

    except plaid_errors.ItemError as ex:
        print("    %s" % ex, file=sys.stderr )
        sys.exit(1)
    else:
        with open(FILE_DEFAULTS.config_file, mode='a') as f:
            config.write(f)
    return True

def generate_auth_page(link_token):
    page = """<html>
    <body>
    <button id='linkButton'>Open Link - Institution Select</button>
    <p id="results"></p>
    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
    <script>
    var linkHandler = Plaid.create({
    token: '""" + link_token + """',
    onLoad: function() {
    // The Link module finished loading.
    },
    onSuccess: function(public_token, metadata) {
    // Send the public_token to your app server here.
    // The metadata object contains info about the institution the
    // user selected and the account ID, if selectAccount is enabled.
    console.log('public_token: '+public_token+', metadata: '+JSON.stringify(metadata));
    document.getElementById("results").innerHTML = "public_token: " + public_token + "<br>metadata: " + metadata;
    },
    onExit: function(err, metadata) {
    // The user exited the Link flow.
    if (err != null) {
    // The user encountered a Plaid API error prior to exiting.
    }
    // metadata contains information about the institution
    // that the user selected and the most recent API request IDs.
    // Storing this information can be helpful for support.
    }
    });

    // Trigger the standard institution select view
    document.getElementById('linkButton').onclick = function() {
    linkHandler.open();
    };
    </script>
    </body>
    </html>
    """

    f = open(FILE_DEFAULTS.auth_file, mode='w')
    f.write(page)
    f.close()

def update_link_token(access_token):
    print ("Trying to update Plaid Link token")

    # Obtain new link token
    client_id, secret = get_plaid_config()
    configs = {
    'user': {
        'client_user_id': '123-test-user-id',
    },
    'client_name': "Plaid Test App",
    'country_codes': ['US'],
    'language': 'en',
    'access_token': access_token
    }
    client = Client(client_id, secret, "development", suppress_warnings=True)
    response = client.LinkToken.create(configs)
    link_token = response['link_token']

    # Update auth.html file with new link token

    with open (FILE_DEFAULTS['auth_file'], "r") as f:
        data = f.read()
        oldText = re.search("token: '.*'", data)[0]
        newText = "token: '" + link_token + "'"
        data = data.replace (oldText, newText)
    
    with open (FILE_DEFAULTS['auth_file'], "w") as f:
        f.write(data)

    print('Link token updated.\nRun \'python3 -m http.server\' from ',DEFAULT_CONFIG_DIR,' and then visit \'localhost:8200\' in your browser to complete authentication with Plaid. Then, start downloading transactions again.')
    sys.exit(0)

if __name__ == '__main__':
    get_locale_currency_symbol()
