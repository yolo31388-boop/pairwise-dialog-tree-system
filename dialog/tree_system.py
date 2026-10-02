"""
pairwise-dialog-tree-system - DialogTreeSystem

This module contains a deliberately broken implementation.
Fix all bugs so that tests pass.
"""


class DialogTreeSystem:
    def __init__(self):
        self.state = {}

    def traverse_node(self, *args, **kwargs):
        """BUG: 节点遍历不做条件检查，所有选项都显示"""
        return None

    def select_option(self, *args, **kwargs):
        """BUG: 选项选择不做前置条件，等级不够也能选"""
        return None

    def evaluate_condition(self, *args, **kwargs):
        """BUG: 条件评估只做简单等于，不支持大于小于和与或非"""
        return None

    def trigger_dialog_event(self, *args, **kwargs):
        """BUG: 对话事件不做触发时机，开始和结束都触发同一个"""
        return None

    def save_dialog_state(self, *args, **kwargs):
        """BUG: 对话存档不存当前节点，读档后从头开始"""
        return None

