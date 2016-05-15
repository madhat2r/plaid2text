#!/usr/bin/env python3

"""
A program to setup Plaid accounts, and download account transactions then
export them to a plain text account format. Currently this programs
provides exports in beancount and ledger syntax formats.
"""

__author__ = "Micah Duke <MaDhAt2r@dukfeoo.com>"
# Check the version requirements.
import sys
if (sys.version_info.major, sys.version_info.minor) < (3, 5):
    raise ImportError("Python 3.5 or above is required")
