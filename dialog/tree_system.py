"""DialogTreeSystem - 对话树系统。

提供节点遍历（条件检查 / 选中标记 / 循环检测）、选项选择（前置条件 /
后果 / 一次性）、条件评估（比较逻辑 / 变量引用 / 缓存）、对话事件
（触发时机 / 参数 / 队列）与对话存档（当前节点 / 选项历史 / 版本）。
"""

from collections import deque
from copy import deepcopy


class DialogTreeSystem:
    SAVE_VERSION = 2

    def __init__(self):
        self.state = {}
        self.nodes = {}
        self.current_node = None
        self.variables = {}
        self.option_history = []
        self._one_time_used = set()
        self._condition_cache = {}
        self._event_queue = deque()
        self._event_seq = 0

    # ------------------------------------------------------------------
    # 节点与变量管理
    # ------------------------------------------------------------------
    def add_node(self, node_id, text="", options=None, goto=None, dialog_id=None):
        self.nodes[node_id] = {
            "id": node_id,
            "text": text,
            "options": list(options or []),
            "goto": goto,
            "dialog_id": dialog_id,
        }
        return self.nodes[node_id]

    def set_variable(self, name, value):
        self.variables[name] = value
        self._condition_cache.clear()

    # ------------------------------------------------------------------
    # 条件评估：比较逻辑 + 与或非 + 变量引用 + 缓存
    # ------------------------------------------------------------------
    @staticmethod
    def _compare(op, left, right):
        try:
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == ">":
                return left is not None and right is not None and left > right
            if op == ">=":
                return left is not None and right is not None and left >= right
            if op == "<":
                return left is not None and right is not None and left < right
            if op == "<=":
                return left is not None and right is not None and left <= right
            if op == "in":
                return left in right
            if op == "not in":
                return left not in right
        except TypeError:
            return False
        raise ValueError(f"unsupported condition operator: {op!r}")

    def _resolve_value(self, value, variables):
        if isinstance(value, str) and value.startswith("$"):
            return variables.get(value[1:])
        return value

    def _eval_condition(self, condition, variables):
        if condition is None:
            return True
        if isinstance(condition, bool):
            return condition
        if isinstance(condition, (int, float)):
            return bool(condition)
        if isinstance(condition, str):
            if condition.startswith("!"):
                return not bool(variables.get(condition[1:]))
            return bool(variables.get(condition.lstrip("$")))
        if isinstance(condition, (list, tuple)):
            return all(self._eval_condition(item, variables) for item in condition)
        if isinstance(condition, dict):
            if "and" in condition:
                return all(self._eval_condition(c, variables) for c in condition["and"])
            if "or" in condition:
                return any(self._eval_condition(c, variables) for c in condition["or"])
            if "not" in condition:
                return not self._eval_condition(condition["not"], variables)
            var_name = condition.get("var")
            left = variables.get(var_name)
            op = condition.get("op", "==")
            if "value" in condition:
                right = self._resolve_value(condition["value"], variables)
            else:
                right = True
            return self._compare(op, left, right)
        raise ValueError(f"unsupported condition: {condition!r}")

    def evaluate_condition(self, condition=None, variables=None):
        """评估条件，支持 ==/!=/>/>=/</<=、and/or/not、$变量引用，并缓存结果。"""
        use_cache = variables is None
        variables = self.variables if variables is None else variables
        cache_key = None
        if use_cache:
            cache_key = repr(condition)
            if cache_key in self._condition_cache:
                return self._condition_cache[cache_key]
        result = bool(self._eval_condition(condition, variables))
        if use_cache:
            self._condition_cache[cache_key] = result
        return result

    # ------------------------------------------------------------------
    # 节点遍历：条件检查 + 选中标记 + 循环检测
    # ------------------------------------------------------------------
    def traverse_node(self, node_id=None, _visited=None):
        """遍历节点：按条件过滤选项、标记已选/已用一次性选项、检测环。"""
        node_id = node_id if node_id is not None else self.current_node
        visited = _visited if _visited is not None else set()
        if node_id in visited:
            return {"node": node_id, "exists": node_id in self.nodes,
                    "cycle": True, "options": []}
        visited.add(node_id)
        node = self.nodes.get(node_id)
        if node is None:
            return {"node": node_id, "exists": False, "cycle": False, "options": []}
        if not node.get("options") and node.get("goto") is not None:
            return self.traverse_node(node["goto"], visited)
        options = []
        for option in node.get("options", []):
            condition = option.get("condition")
            if condition is not None and not self.evaluate_condition(condition):
                continue
            key = (node_id, option.get("id"))
            used = key in self._one_time_used
            options.append({
                "id": option.get("id"),
                "text": option.get("text", ""),
                "next": option.get("next"),
                "selected": any(h["node"] == node_id and h["option"] == option.get("id")
                                for h in self.option_history),
                "one_time": bool(option.get("one_time")),
                "used": used,
            })
        return {
            "node": node_id,
            "exists": True,
            "cycle": False,
            "text": node.get("text", ""),
            "dialog_id": node.get("dialog_id"),
            "options": options,
        }

    def detect_cycles(self):
        """对整棵对话树做 DFS，返回检测到的环（节点路径列表）。"""
        cycles = []
        stack, done = [], set()

        def visit(node_id):
            if node_id in stack:
                cycles.append(stack[stack.index(node_id):] + [node_id])
                return
            if node_id in done or node_id not in self.nodes:
                return
            stack.append(node_id)
            node = self.nodes[node_id]
            targets = [o.get("next") for o in node.get("options", [])]
            if node.get("goto") is not None:
                targets.append(node["goto"])
            for target in targets:
                if target is not None:
                    visit(target)
            stack.pop()
            done.add(node_id)

        for node_id in list(self.nodes):
            visit(node_id)
        return cycles

    # ------------------------------------------------------------------
    # 选项选择：前置条件 + 后果 + 一次性
    # ------------------------------------------------------------------
    def _apply_effects(self, effects):
        if not effects:
            return
        if isinstance(effects, dict):
            effects = [{"var": k, "op": "set", "value": v} for k, v in effects.items()]
        for effect in effects:
            name = effect.get("var")
            op = effect.get("op", "set")
            value = self._resolve_value(effect.get("value"), self.variables)
            if op == "set":
                self.variables[name] = value
            elif op == "add":
                self.variables[name] = (self.variables.get(name) or 0) + value
            elif op == "sub":
                self.variables[name] = (self.variables.get(name) or 0) - value
            elif op == "mul":
                self.variables[name] = (self.variables.get(name) or 0) * value
            else:
                raise ValueError(f"unsupported effect op: {op!r}")
        self._condition_cache.clear()

    def select_option(self, option_id=None, node_id=None):
        """选择选项：校验前置条件与一次性限制，应用后果并推进对话。"""
        node_id = node_id if node_id is not None else self.current_node
        node = self.nodes.get(node_id)
        if node is None or option_id is None:
            return {"success": False, "reason": "invalid_option",
                    "node": node_id, "option": option_id}
        option = next((o for o in node.get("options", [])
                       if o.get("id") == option_id), None)
        if option is None:
            return {"success": False, "reason": "option_not_found",
                    "node": node_id, "option": option_id}
        key = (node_id, option_id)
        if option.get("one_time") and key in self._one_time_used:
            return {"success": False, "reason": "one_time_used",
                    "node": node_id, "option": option_id}
        condition = option.get("condition")
        if condition is not None and not self.evaluate_condition(condition):
            return {"success": False, "reason": "condition_not_met",
                    "node": node_id, "option": option_id}
        self._apply_effects(option.get("effects"))
        if option.get("one_time"):
            self._one_time_used.add(key)
        self.option_history.append({"node": node_id, "option": option_id})
        next_node = option.get("next")
        if next_node is not None:
            self.current_node = next_node
        if option.get("ends_dialog") or (next_node is None and option.get("end")):
            self.trigger_dialog_event("dialog", dialog_id=node.get("dialog_id"),
                                      timing="end", node=node_id, option=option_id)
        return {"success": True, "node": node_id, "option": option_id,
                "next": next_node}

    # ------------------------------------------------------------------
    # 对话事件：触发时机 + 参数 + 队列
    # ------------------------------------------------------------------
    def trigger_dialog_event(self, event_type="dialog", dialog_id=None,
                             timing="start", **params):
        """触发对话事件：区分 start/end 时机，携带参数，按序入队。"""
        if timing not in ("start", "end"):
            raise ValueError(f"invalid event timing: {timing!r}")
        self._event_seq += 1
        event = {
            "seq": self._event_seq,
            "name": f"{event_type}_{timing}",
            "type": event_type,
            "timing": timing,
            "dialog_id": dialog_id,
            "params": dict(params),
        }
        self._event_queue.append(event)
        return event

    def next_event(self):
        """按 FIFO 顺序取出一个待处理事件，空队列返回 None。"""
        return self._event_queue.popleft() if self._event_queue else None

    def drain_events(self):
        """按触发顺序取出全部待处理事件。"""
        events = list(self._event_queue)
        self._event_queue.clear()
        return events

    @property
    def pending_event_count(self):
        return len(self._event_queue)

    def start_dialog(self, node_id, dialog_id=None):
        self.current_node = node_id
        node = self.nodes.get(node_id, {})
        self.trigger_dialog_event("dialog",
                                  dialog_id=dialog_id or node.get("dialog_id"),
                                  timing="start", node=node_id)
        return self.traverse_node(node_id)

    def end_dialog(self, dialog_id=None):
        node = self.nodes.get(self.current_node, {})
        event = self.trigger_dialog_event(
            "dialog", dialog_id=dialog_id or node.get("dialog_id"),
            timing="end", node=self.current_node)
        self.current_node = None
        return event

    # ------------------------------------------------------------------
    # 对话存档：当前节点 + 选项历史 + 版本
    # ------------------------------------------------------------------
    def save_dialog_state(self):
        """保存对话状态：当前节点、选项历史、一次性记录、变量与版本号。"""
        return {
            "version": self.SAVE_VERSION,
            "current_node": self.current_node,
            "variables": deepcopy(self.variables),
            "option_history": deepcopy(self.option_history),
            "one_time_used": [list(k) for k in self._one_time_used],
        }

    def load_dialog_state(self, save):
        """加载对话状态；版本缺失或不兼容时返回 False 而不是崩溃。"""
        if not isinstance(save, dict):
            return False
        if save.get("version") != self.SAVE_VERSION:
            return False
        self.current_node = save.get("current_node")
        self.variables = deepcopy(save.get("variables") or {})
        self.option_history = deepcopy(save.get("option_history") or [])
        self._one_time_used = {tuple(k) for k in save.get("one_time_used") or []}
        self._condition_cache.clear()
        return True
