#! /usr/bin/env python3

from pymongo import MongoClient,ASCENDING,DESCENDING
import datetime

TEXT_DOC = {'plaid2text':{
    'tags':            [],
    'payee':           '',
    'posting_account': '',
    'associated_account': '',
    'date_downloaded': datetime.datetime.today(),
    'date_last_pulled': datetime.datetime.today(),
    'pulled_to_file':  False
}}

class StorageManager():
    """
    Handles all Mongo related tasks
    """
    def __init__(self,db,account,posting_account):
        self.mc = MongoClient()
        self.db_name = db
        self.db = self.mc[db]
        self.account = self.db[account]

    def save_transactions(self,transactions):
        """
        Saves the given transactions to the configured db.

        Occurs when using the --download-transactions option
        """
        for t in transactions:
            id = t['_id']
            # t.update(TEXT_DOC)
            #convert datetime
            y,m,d = [int(i) for i in t['date'].split('-')]
            t['date'] = datetime.datetime(y,m,d)
            doc = {'$set':t}
            #add default plaid2text to new inserts
            doc['$setOnInsert'] = TEXT_DOC
            self.account.update_many({'_id': id}, doc, True)

    def get_transactions(self,from_date=None,to_date=None,only_new=True):
        """
        Retrieve transactions for producing text file
        """
        query = {}
        if only_new:
            query['plaid2text.pulled_to_file'] = False

        if from_date and to_date and (from_date < to_date):
            query['date'] = {'$gte':from_date,'$lte':to_date}
        elif from_date and not to_date:
            query['date'] = {'$gte':from_date}
        elif not from_date and to_date:
            query['date'] = {'$lte':to_date}

        transactions = self.account.find(query).sort('date',ASCENDING)

        return transactions


    def update_transaction(self,update):
        id = update.pop('transaction_id')
        doc = {}
        update['pulled_to_file'] = True
        update['date_last_pulled'] = datetime.datetime.today()
        doc['plaid2text'] = update

        self.account.update(
            {'_id':id},
            {'$set':doc}
        )



