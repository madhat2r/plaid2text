#! /usr/bin/env python3

import datetime
from dateutil import parser as date_parser
import sqlite3
import json

from abc import ABCMeta, abstractmethod
from pymongo import MongoClient, ASCENDING, DESCENDING

from .renderers import Entry

TEXT_DOC = {
    'plaid2text': {
        'tags': [],
        'payee': '',
        'posting_account': '',
        'associated_account': '',
        'date_downloaded': datetime.datetime.today(),
        'date_last_pulled': '',
        'pulled_to_file':  False
    }
}

class StorageManager(metaclass=ABCMeta):
    @abstractmethod
    def save_transactions(self, transactions):
        """
        Saves the given transactions to the configured db.

        Occurs when using the --download-transactions option.
        """
        pass

    @abstractmethod
    def get_transactions(self, from_date=None, to_date=None, only_new=True):    
        """
        Retrieve transactions for producing text file.
        """
        pass

    @abstractmethod
    def update_transaction(self, update):
        pass

class MongoDBStorage(StorageManager):
    """
    Handles all Mongo related tasks
    """
    def __init__(self, db, uri, account, posting_account):
        self.mc = MongoClient(uri)
        self.db_name = db
        self.db = self.mc[db]
        self.account = self.db[account]

    def save_transactions(self, transactions):
        for t in transactions:
            if not t['pending']:
                id = t['transaction_id']
                # t.update(TEXT_DOC)
                # Convert datetime
                y, m, d = [int(i) for i in t['date'].split('-')]
                t['date'] = datetime.datetime(y, m, d)
                doc = {'$set': t}
                # Add default plaid2text to new inserts
                doc['$setOnInsert'] = TEXT_DOC
                self.account.update_many({'_id': id}, doc, True)

    def get_transactions(self, from_date=None, to_date=None, only_new=True):
        query = {}
        if only_new:
            query['plaid2text.pulled_to_file'] = {"$ne": True}

        if from_date and to_date and (from_date <= to_date):
            query['date'] = {'$gte': from_date, '$lte': to_date}
        elif from_date and not to_date:
            query['date'] = {'$gte': from_date}
        elif not from_date and to_date:
            query['date'] = {'$lte': to_date}

        transactions = self.account.find(query).sort('date', ASCENDING)
        return list(transactions)

    def update_transaction(self, update, mark_pulled=None):
        id = update.pop('transaction_id')
        update['pulled_to_file'] = mark_pulled
        if mark_pulled:
            update['date_last_pulled'] = datetime.datetime.now()

        self.account.update_one(
            {'_id': id},
            {'$set': {"plaid2text": update}}
        )

    def get_latest_transaction_date(self):
        latest = list(self.account.find().sort("date", DESCENDING).limit(1))[0]['date']
        return latest
    
    # check if an account has unpulled transactions
    def check_pending(self):
        query = {'plaid2text.pulled_to_file':{"$ne": True}}
        unpulled = list(self.account.find(query))
        pending = len(unpulled) > 0
        return pending

class SQLiteStorage():
    def __init__(self, dbpath, account, posting_account):
        self.conn = sqlite3.connect(dbpath) 

        c = self.conn.cursor()
        c.execute("""
            create table if not exists transactions
                (account_id, transaction_id, created, updated, plaid_json, metadata)
            """)
        c.execute("""
            create unique index if not exists transactions_idx
                ON transactions(account_id, transaction_id)
            """)
        self.conn.commit()

        # This might be needed if there's not consistent support for json_extract in sqlite3 installations
        # this will need to be modified to support the "$.prop" syntax
        #def json_extract(json_str, prop):
        #    ret = json.loads(json_str).get(prop, None)
        #    return ret
        #self.conn.create_function("json_extract", 2, json_extract)

    def save_transactions(self, transactions):
        """
        Saves the given transactions to the configured db.

        Occurs when using the --download-transactions option.
        """
        for t in transactions:
            trans_id = t['transaction_id']
            act_id   = t['account_id'] 

            metadata = t.get('plaid2text', None)
            if metadata is not None:
                metadata = json.dumps(metadata)

            c = self.conn.cursor()
            c.execute("""
                insert into 
                    transactions(account_id, transaction_id, created, updated, plaid_json, metadata)
                    values(?,?,strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),?,?)
                    on conflict(account_id, transaction_id) DO UPDATE
                        set updated = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                            plaid_json = excluded.plaid_json,
                            metadata   = excluded.metadata
                """, [act_id, trans_id, json.dumps(t), metadata])
            self.conn.commit()

    def get_transactions(self, from_date=None, to_date=None, only_new=True):
        query = "select plaid_json, metadata from transactions";

        conditions = []
        if only_new: 
            conditions.append("coalesce(json_extract(plaid_json, '$.pulled_to_file'), false) = false")

        params  = []
        if from_date and to_date and (from_date <= to_date):
            conditions.append("json_extract(plaid_json, '$.date') between ? and ?")
            params += [from_date.strftime("%Y-%m-%d"), to_date.strftime("%Y-%m-%d")]
        elif from_date and not to_date:
            conditions.append("json_extract(plaid_json, '$.date') >= ?")
            params += [from_date]
        elif not from_date and to_date:
            conditions.append("json_extract(plaid_json, '$.date') <= ?")
            params += [to_date]

        if len(conditions) > 0:
            query = "%s where %s" % ( query, " AND ".join( conditions ) )

        transactions = self.conn.cursor().execute(query, params).fetchall()

        ret = []
        for row in transactions:
            t = json.loads(row[0])
            if row[1]:
                t['plaid2text'] = json.loads(row[1])
            else:
                t['plaid2text'] = {}

            if ( len(t['plaid2text']) == 0 ):
                # set empty objects ({}) to None to account for assumptions that None means not processed
                t['plaid2text'] = None

            t['date'] = date_parser.parse( t['date'] )        

            ret.append(t)

        return ret

    def update_transaction(self, update, mark_pulled=None):
        trans_id = update.pop('transaction_id')
        update['pulled_to_file'] = mark_pulled
        if mark_pulled:            
            update['date_last_pulled'] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        update['archived'] = null

        c = self.conn.cursor()
        c.execute("""
            update transactions set metadata = json_patch(coalesce(metadata, '{}'), ?) 
            where transaction_id = ?
        """, [json.dumps(update), trans_id] )
        self.conn.commit()
