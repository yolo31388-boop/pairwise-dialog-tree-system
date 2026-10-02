import pytest
from dialog.tree_system import DialogTreeSystem


class TestDialogTreeSystem:

    def test_traverse_node(self):
        """节点遍历不做条件检查，所有选项都显示"""
        obj = DialogTreeSystem()
        result = obj.traverse_node()
        self.assertIsNotNone(result)

    def test_select_option(self):
        """选项选择不做前置条件，等级不够也能选"""
        obj = DialogTreeSystem()
        result = obj.select_option()
        self.assertIsNotNone(result)

    def test_evaluate_condition(self):
        """条件评估只做简单等于，不支持大于小于和与或非"""
        obj = DialogTreeSystem()
        result = obj.evaluate_condition()
        self.assertIsNotNone(result)

    def test_trigger_dialog_event(self):
        """对话事件不做触发时机，开始和结束都触发同一个"""
        obj = DialogTreeSystem()
        result = obj.trigger_dialog_event()
        self.assertIsNotNone(result)

    def test_save_dialog_state(self):
        """对话存档不存当前节点，读档后从头开始"""
        obj = DialogTreeSystem()
        result = obj.save_dialog_state()
        self.assertIsNotNone(result)

