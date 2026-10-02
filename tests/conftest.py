"""测试辅助：为未继承 unittest.TestCase 的测试类补齐 assert 方法。"""

import unittest

from tests.test_dialog_tree import TestDialogTreeSystem

for _name in dir(unittest.TestCase):
    if _name.startswith("assert") and not hasattr(TestDialogTreeSystem, _name):
        setattr(TestDialogTreeSystem, _name, getattr(unittest.TestCase, _name))
