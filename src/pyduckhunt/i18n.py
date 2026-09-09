"""Presentation-only localization; no language is stored in game events.

French source messages are gettext-style keys. Contexts are scoped to a render
or one instance callback, never process-wide: simultaneous FR/EN instances and
background publishers cannot change one another's language.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from pyduckhunt.messages_en import EN

_LANGUAGE: ContextVar[str] = ContextVar('pyduckhunt_language', default='fr')
SUPPORTED_LANGUAGES = ('fr', 'en')


def validate_language(value: str) -> str:
    if type(value) is not str or value not in SUPPORTED_LANGUAGES:
        raise ValueError('language must be fr or en')
    return value


def current_language() -> str:
    return _LANGUAGE.get()


@contextmanager
def language_context(language: str):
    token = _LANGUAGE.set(validate_language(language))
    try:
        yield
    finally:
        _LANGUAGE.reset(token)


def tr(source: str, *values: object) -> str:
    """Translate a template before formatting its untouched dynamic values."""
    text = EN.get(source, source) if current_language() == 'en' else source
    return text.format(*values) if values else text


def localized(function):
    """Add an optional language keyword; nested renders inherit their caller."""
    @wraps(function)
    def render(*args, language=None, **kwargs):
        if language is None:
            return function(*args, **kwargs)
        with language_context(language):
            return function(*args, **kwargs)
    return render


def localized_method(function):
    """Use the owning runtime's language for the complete synchronous callback."""
    @wraps(function)
    def call(self, *args, **kwargs):
        with language_context(self.language):
            return function(self, *args, **kwargs)
    return call


class LocalizedMapping(Mapping):
    """Translate immutable presentation labels at lookup time, never import time."""
    def __init__(self, source):
        self._source = dict(source)

    def __iter__(self):
        return iter(self._source)

    def __len__(self):
        return len(self._source)

    def __getitem__(self, key):
        value = self._source[key]
        if isinstance(value, tuple):
            return tuple(tr(part) if isinstance(part, str) else part for part in value)
        return tr(value) if isinstance(value, str) else value
