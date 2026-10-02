"""Pytest bootstrap.

The tests in ``tests/`` use ``unittest``-style assertions (``assertIsNotNone``)
on plain classes that do not inherit from ``unittest.TestCase``. Attach the
assertion helpers at collection time so those tests can run unmodified.
"""

import unittest


def pytest_collection_modifyitems(items):
    for item in items:
        cls = getattr(item, "cls", None)
        if cls is None or issubclass(cls, unittest.TestCase):
            continue
        for name in dir(unittest.TestCase):
            if name.startswith("assert") and not hasattr(cls, name):
                setattr(cls, name, getattr(unittest.TestCase, name))
