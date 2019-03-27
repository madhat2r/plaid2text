#! /usr/bin/env python3

from prompt_toolkit import prompt  # NOQA: F401
from prompt_toolkit.validation import ValidationError, Validator
from prompt_toolkit.completion.filesystem import PathCompleter
from prompt_toolkit.completion.base import Completer, Completion
from six import string_types


PATH_COMPLETER = PathCompleter(expanduser=True)


def separator_completer(words, sep=' '):
    return SeparatorCompleter(words, sep=sep)


class SeparatorCompleter(Completer):
    """
    Simple autocompletion on a list of accounts. i.e. "Expenses:Unknown"

    :param words: List of words.
    :param sep: The separator to use
    :param ignore_case: If True, case-insensitive completion.
    """
    def __init__(self, words, ignore_case=True, sep=" "):
        self.words = list(words)
        self.ignore_case = ignore_case
        assert all(isinstance(w, string_types) for w in self.words)

    def get_completions(self, document, complete_event):
        # Get word/text before cursor.
        text_before_cursor = document.text_before_cursor
        if self.ignore_case:
            text_before_cursor = text_before_cursor.lower()

        text_len = len(text_before_cursor)
        if text_len < 1:
            return

        if self.ignore_case:
            text_before_cursor = text_before_cursor.lower()

        add_hyphen = False
        if text_before_cursor[0] == '-':
            text_before_cursor = text_before_cursor[1:]
            add_hyphen = True

        def word_matches(word):
            """ True when the word before the cursor matches. """
            if self.ignore_case:
                word = word.lower()

            return word.startswith(text_before_cursor)

        word_parts = set()
        for w in self.words:
            if word_matches(w):
                last_colon = text_before_cursor.rfind(':') + 1  # Pos of last colon in text
                last_pos = last_colon if last_colon > 0 else 0
                next_colon = w.find(':', last_pos)
                next_pos = next_colon
                if next_colon < 0:
                    next_pos = len(w) - 1
                next_colon = w.find(':', text_len)
                if text_len == next_colon:  # Next char is colon
                    next_colon = w.find(':', next_colon + 1)
                    if next_colon < 0:
                        next_colon = len(w)
                    ret = (w[0:next_colon], w[text_len:next_colon])
                elif next_colon < 0:  # Next char is not colon
                    last_word = text_before_cursor[last_colon:]
                    display_word = w[last_colon:]
                    if last_word == display_word.lower():
                        continue
                    ret = (w, display_word)
                else:
                    ret = (w[0:next_pos], w[last_pos:next_pos])
                word_parts.add(ret)

        word_parts = sorted(list(word_parts), key=lambda x: x[1])
        for c, d in list(word_parts):
            comp = '-' + c if add_hyphen else c
            yield Completion(comp, -text_len, display=d)


class YesNoValidator(Validator):
    def validate(self, document):
        text = document.text.lower()
        # Assumes that there is a default for empty
        if not bool(text):
            return
        if not (text.startswith('y') or text.startswith('n')):
            raise ValidationError(message='Please enter y[es] or n[o]')


class NullValidator(Validator):
    def __init__(self, message='You must enter a value', allow_quit=False):
        Validator.__init__(self)
        self.message = message if not allow_quit else message + ' or q to quit'
        self.allow_quit = allow_quit

    def validate(self, document):
        text = document.text
        if not text:
            raise ValidationError(message=self.message)
        elif self.allow_quit and text.lower() == 'q':
            return


class NumberValidator(NullValidator):
    def __init__(self,
                 message='You must enter a number',
                 allow_quit=False,
                 max_number=None):
        NullValidator.__init__(self, allow_quit=allow_quit)
        self.message = message if not allow_quit else message + ' or q to quit'
        self.max_number = max_number

    def validate(self, document):
        NullValidator.validate(self, document)
        text = document.text
        if self.allow_quit and text.lower() == 'q':
            return
        if not text.isdigit():
            i = 0
            for i, c in enumerate(text):
                if not c.isdigit():
                    break
            raise ValidationError(message=self.message, cursor_position=i)

        if not bool(self.max_number):
            return
        valid = int(text) <= int(self.max_number) and not int(text) == 0
        if not valid:
                range_message = 'You must enter a number between 1 and {}'.format(self.max_number)
                raise ValidationError(message=range_message)


class NumLengthValidator(NumberValidator):
    def __init__(self,
                 message='You must enter at least {} characters',
                 allow_quit=False,
                 min_number=4):
        NumberValidator.__init__(self, allow_quit=allow_quit)
        message = message.format(min_number)
        self.message = message if not allow_quit else message + ' or q to quit'
        self.min_number = min_number

    def validate(self, document):
        NumberValidator.validate(self, document)
        text = document.text
        if self.allow_quit and text.lower() == 'q':
            return
        text_length = len(text)
        if not text_length >= self.min_number:
            raise ValidationError(message=self.message, cursor_position=text_length)


def clear_screen():
    print('\033[2J\033[;H')
