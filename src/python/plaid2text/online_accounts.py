#! /usr/bin/env python3

import sys
import datetime
from plaid import Client
from plaid import errors as plaid_errors
from pymongo import MongoClient
from collections import OrderedDict
import textwrap
import plaid2text.storage_manager
import plaid2text.config_manager as cm
from plaid2text.interact import prompt,clear_screen,NullValidator,NumberValidator,NumLengthValidator,YesNoValidator, PATH_COMPLETER


class PlaidAccess():
    def __init__(self, client_id=None, secret=None,account_id=None,access_token=None):
        if client_id and secret:
            self.client_id=client_id
            self.secret=secret
        else:
            self.client_id, self.secret = cm.get_plaid_config()
        self.client = Client(client_id=self.client_id,
                             secret=self.secret)
        # if access_token: self.acceess_token = access_token
        # if account_id: self.account_id = account_id

    def get_transactions(self,
                         access_token,
                         account_id,
                         start_date=None,
                         end_date=None):
        """Get transaction for a given account for the given dates"""
        self.client.access_token = access_token
        options = {}
        options["account"] = account_id
        #get all transaction up to and including today
        options['lte'] = datetime.date.today().strftime('%Y-%m-%d')
        self.connect_response = self.client.connect_get(options).json()
        return self.connect_response['transactions']

    def add_account(self,nickname):
        try:
            self._get_available_institutions()
        except Exception as e:
            raise Exception(
                "There was a problem obtaining a list of institutions. Try again later.") from e

        selected_institution = self._get_institution()
        if selected_institution is None:
            print("Quitting, no account added",file=sys.stdout)
            sys.exit(0)
        self.active_institution = self.available_institutions[
            selected_institution][1]
        self.account_type = self.active_institution["type"]
        un, pwd, pin = self._get_needed_creds()
        # self.client.client_id = "test_id"
        # self.client.secret = "test_secret"
        # un = "plaid_test"
        # pwd = "plaid_good"
        login = {'username': un, 'password': pwd}
        if pin: login['pin'] = pin
        try:
            self.connect_response = self.client.connect(self.account_type, login)
        except plaid_errors.PlaidError as e:
            print(e.message)
            return
        else:
            cont = True
            try:
                while not self._check_status():
                    cont = self._process_mfa(self.connect_response.json())
                    if not cont: break
            except plaid_errors.PlaidError as e:
                print("The following error has occurred, no account added:\n{}".format(e.message),
                        file=sys.stderr)
                sys.exit(1)
            else:
                if not cont:
                    print("Quitting, no account added",file=sys.stderr)
                    sys.exit(1)

                accts = self.connect_response.json()['accounts']
                if not self._present_accounts(accts):
                    print("Quitting, no account added",file=sys.stderr)
                    sys.exit(1)

                self._save_account_section(nickname)


    def _save_account_section(self,nickname):
        acct_section= OrderedDict()
        acct_section[nickname] = OrderedDict()
        section = acct_section[nickname]
        section['access_token'] = self.client.access_token
        section['account'] = self.selected_account['_id']
        a = prompt("What account is used for posting transactions [{}]: ".format(cm.CONFIG_DEFAULTS.posting_account))
        if a:
            section['posting_account'] = a
        else:
            section['posting_account'] = cm.CONFIG_DEFAULTS.posting_account

        a = prompt("What currency does this account use for posting transactions [{}]: ".format(cm.CONFIG_DEFAULTS.currency))
        if a:
            section['currency'] = a
        else:
            section['currency'] = cm.CONFIG_DEFAULTS.currency

        a = self._present_file_options(nickname,'mapping',cm.FILE_DEFAULTS.mapping_file)
        if a:
            section['mapping_file'] = a

        a = self._present_file_options(nickname,'journal',cm.FILE_DEFAULTS.journal_file)
        if a:
            section['journal_file'] = a

        a = self._present_file_options(nickname,'accounts',cm.FILE_DEFAULTS.accounts_file)
        if a:
            section['accounts_file'] = a

        a = self._present_file_options(nickname,'template',cm.FILE_DEFAULTS.template_file)
        if a:
            section['template_file'] = a

        cm.write_section(acct_section)


    def _present_file_options(self,nickname,file_type,default_file):
        a = prompt("Create a separate {} file configuration setting for this account [Y/n]: ".format(file_type)
                   ,validator=YesNoValidator()).lower()
        if not bool(a) or create.startswith("y"):
            cont = True
            while cont:
                path = prompt("Enter the path for the {} file used for this account [{}]: ".format(file_type,default_file),
                            completer=PATH_COMPLETER)
                if path:
                    cont = not os.path.isfile(os.path.expanduser(path))
                if cont:
                    print("Invalid path {}. Please enter a valid path.".format(path))
                else:
                    cont = false

            if not path:
                path = cm.get_custom_file_path(nickname,file_type,create_file=True)
            return f
        elif create.startswith("n"):
            return None


    def _process_mfa(self, data):
        type = data['type']
        mfa = data['mfa']
        if type == 'questions':
            return self._present_question([q['question'] for q in mfa])
        elif type == 'list':
            return self._present_list(mfa)
        elif type == 'selection':
            return self._present_selection(mfa)
        else:
            raise Exception("Unknown mfa type from Plaid")

    def _present_question(self, question):
        clear_screen()
        print(question[0])
        answer = prompt(
            "Answer: ",
            validator=NullValidator(message="You must enter your answer",
                                    allow_quit=True))
        if answer.lower() == "q": return False  #we have abandoned ship
        self.connect_response = self.client.connect_step(self.account_type, answer)
        return True

    def _present_accounts(self, data):
        clear_screen()
        accounts = list(enumerate(data, start=1))
        message = ["Which account do you want to add:\n"]
        for i, d in accounts:
            a = {}
            a['choice'] = str(i)
            a['name'] = d['meta']['name']
            a['type'] = d['subtype'] if 'subtype' in d else d['type']
            message.append("{choice:<2}. {name:<40}  {type}\n".format(**a))

        message.append("\nEnter your selection: ")
        answer = prompt("".join(message), validator=NumberValidator(
            message="Enter the NUMBER of the account you want to add",allow_quit=True,max_number=len(accounts)))
        if answer.lower() == "q": return False  #we have abandoned ship
        self.selected_account = accounts[int(answer) - 1][1]
        return True

    def _present_list(self, data):
        clear_screen()
        devices = list(enumerate(data, start=1))
        message = ["Where do you want to send the verification code:\n"]
        for i, d in devices:
            message.append("{:<4}{}\n".format(i, d["mask"]))
        message.append("\nEnter your selection: ")
        answer = prompt("".join(message), validator=NumberValidator(
            message="Enter the NUMBER where you want to send verification code",allow_quit=True,max_number=len(devices)))
        if answer.lower() == "q": return False  #we have abandoned ship
        dev = devices[int(answer) - 1][1]
        print("Code will be sent to: {}".format(dev["mask"]))
        self.connect_response = self.client.connect_step(
            self.account_type,
            None,
            options={'send_method': {'type': dev['type']}})
        code = prompt("Enter the code you received: ",
                      validator=NumberValidator())
        self.connect_response =  self.client.connect_step(self.account_type,code)
        return True


    def _present_selection(self, data):
        """
        Could not test: needs implementation
        """
        clear_screen()
        raise NotImplementedError("MFA selections are not yet implemented, sorry.")

    def _get_needed_creds(self):
        credentials = self.active_institution["credentials"]
        clear_screen()
        print("Enter the required credentials for {}\n".format(
            self.active_institution["name"]))
        user_prompt = "Username ({}): ".format(credentials["username"])
        pass_prompt = "Password ({}): ".format(credentials["password"])
        pin = None
        username = prompt(
            user_prompt,
            validator=NullValidator(message="Please enter your username"))
        password = prompt(
            pass_prompt,
            is_password=True,
            validator=NullValidator(message="You must enter your password"))
        if "pin" in credentials:
            pin = prompt("PIN: ",
                         validator=NumLengthValidator(
                             message="Pin must be at least {} characters long"))
            if not bool(pin) or pin.lower() == "q":
                pin = None  #make sure we have something
        return username, password, pin

    def _get_available_institutions(self):
        # limit to just those institutions that have connect abilities,
        # as that is the service we will be using to get transactions
        institutions = self.client.institutions().json()
        self.available_institutions = list(enumerate(
            [i for i in institutions if 'connect' in i['products']],
            start=1))

    def _get_institution(self):
        accounts = []
        total_institutions = len(self.available_institutions)
        for account in self.available_institutions:
            num, info = account
            accounts.append("{num:<4}{inst}".format(num=num,
                                                    inst=info['name']))

        institution_prompt = textwrap.dedent(
            """What bank is this account going to be for? \n{}\n\nEnter Number [q to quit]:""".format(
                '\n'.join(accounts)))

        clear_screen()

        res = prompt(
            institution_prompt,
            validator = NumberValidator(message="You must enter the chosen number",
                            allow_quit=True,max_number=total_institutions))
        if res.isdigit():
            choice = int(res) - 1
        elif res.lower() == "q":
            choice = None

        return choice

    def _check_status(self):
        status = self.connect_response.status_code
        if status == 200:
            # good, user connected
            return True
        elif status == 201:
            # MFA required
            return False
        else:
            return False





