#!/usr/bin/env python3
"""
Install script for plaid2text.
"""
__author__ = "Micah Duke <MaDhAt2r@dukfeoo.com>"

import os
from os import path
import runpy
import sys
import warnings


# Check if the version is sufficient.
if sys.version_info[:2] < (3,5):
    raise SystemExit("ERROR: Insufficient Python version; you need v3.5 or higher.")


# Import setup().
setup_extra_kwargs = {}
try:
    from setuptools import setup, Extension
    setup_extra_kwargs.update(install_requires = [
        # used for working with MongoDB
        'pymongo==3.10.1',
        
        # used in console prompts/autocompletion
        'prompt_toolkit',
        
        # the heart of the program
        'plaid-python==7.1.0',
        'beancount==2.2.1',
    ])

except ImportError:
    warnings.warn("Setuptools not installed; falling back on distutils. "
                    "You will have to install dependencies explicitly.")
    from distutils.core import setup, Extension


# Explicitly list the scripts to install.
install_scripts = [path.join('bin', x) for x in """
plaid2text
""".split() if x and not x.startswith('#')]


# Create a setup.
setup(
    name="plaid2text",
    version='0.1.2',
    description="Plaid API to ledger/beancount download/conversion",

    long_description=
    """
    A program to setup Plaid accounts, and download account transactions then
    export them to a plain text account format. Currently this programs
    provides exports in beancount and ledger syntax formats.
    """,

    license="GPL",
    author="Micah Duke",
    author_email="MaDhAt2r@dukefoo.com",
    url="https://github.com/madhat2r/plaid2text",

    package_dir = {'': 'src/python',},
    packages = ['plaid2text'],

    scripts=install_scripts,
    # Add optional arguments that only work with some variants of setup().
    **setup_extra_kwargs
)
