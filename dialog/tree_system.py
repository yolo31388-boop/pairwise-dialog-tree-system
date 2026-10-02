"""
pairwise-dialog-tree-system - DialogTreeSystem

Branching dialog tree with:

* node traversal that filters options by condition, marks selected options
  and detects cycles in the option graph;
* option selection that enforces preconditions, applies consequences and
  honours one-time options;
* condition evaluation supporting comparisons, and/or/not logic, variable
  references, string expressions and caching;
* dialog events with explicit timing (start/option/end), parameters and a
  FIFO event queue;
* versioned save/load covering the current node, variables and history.
"""

from collections import deque


class DialogTreeSystem:
    SAVE_VERSION = 2

    EVENT_START = "start"
    EVENT_OPTION = "option"
    EVENT_END = "end"

    _COMPARATORS = {
        "==": lambda left, right: left == right,
        "!=": lambda left, right: left != right,
        ">": lambda left, right: left > right,
        "<": lambda left, right: left < right,
        ">=": lambda left, right: left >= right,
        "<=": lambda left, right: left <= right,
    }

    def __init__(self):
        self.state = {}
        self.nodes = {}
        self.current_node = None
        self.variables = {}
        self.option_history = []
        self.used_one_time_options = set()
        self.event_queue = deque()
        self.event_log = []
        self._condition_cache = {}

    # ------------------------------------------------------------------ #
    # Tree construction
    # ------------------------------------------------------------------ #
    def add_node(self, node_id, text="", options=None, condition=None):
        node = {
            "id": node_id,
            "text": text,
            "options": [self._normalize_option(opt) for opt in (options or [])],
            "condition": condition,
            "visited": False,
        }
        self.nodes[node_id] = node
        if self.current_node is None:
            self.current_node = node_id
        return node

    def add_option(self, node_id, option):
        if node_id not in self.nodes:
            self.add_node(node_id)
        option = self._normalize_option(option)
        self.nodes[node_id]["options"].append(option)
        return option

    @staticmethod
    def _normalize_option(option):
        option = dict(option)
        option.setdefault("id", option.get("text"))
        option.setdefault("text", str(option["id"]))
        option.setdefault("target", None)
        option.setdefault("condition", None)
        option.setdefault("consequences", {})
        option.setdefault("one_time", False)
        return option

    # ------------------------------------------------------------------ #
    # Node traversal: condition check, selected marking, cycle detection
    # ------------------------------------------------------------------ #
    def traverse_node(self, node_id=None, _path=None):
        node_id = self.current_node if node_id is None else node_id
        path = [] if _path is None else _path

        if node_id is None:
            return {"node": None, "options": [], "cycle": False}

        if node_id in path:
            return {
                "node": node_id,
                "options": [],
                "cycle": True,
                "cycle_path": path + [node_id],
            }

        node = self.nodes.get(node_id)
        if node is None:
            return {"node": node_id, "options": [], "cycle": False, "missing": True}

        if not self.evaluate_condition(node.get("condition")):
            return {"node": node_id, "options": [], "cycle": False, "hidden": True}

        node["visited"] = True
        visible_options = []
        for option in node["options"]:
            if not self.evaluate_condition(option.get("condition")):
                continue
            one_time_used = (
                option["one_time"] and option["id"] in self.used_one_time_options
            )
            visible_options.append({
                "id": option["id"],
                "text": option["text"],
                "target": option["target"],
                "one_time": option["one_time"],
                "selected": option["id"] in self.option_history,
                "available": not one_time_used,
            })

        return {
            "node": node_id,
            "text": node["text"],
            "options": visible_options,
            "cycle": False,
            "visited": True,
        }

    def traverse_from(self, start=None):
        """Recursive traversal from ``start`` (default: current node)."""
        start = self.current_node if start is None else start

        def walk(node_id, path):
            result = self.traverse_node(node_id, _path=path)
            if result.get("cycle"):
                return result
            children = []
            for option in result.get("options", []):
                target = option["target"]
                children.append({
                    "option": option,
                    "next": walk(target, path + [node_id]) if target is not None else None,
                })
            result["branches"] = children
            return result

        return walk(start, [])

    def detect_cycle(self, start=None):
        """Return the node list forming a cycle, or ``None`` when acyclic."""
        start = self.current_node if start is None else start
        visiting = []
        visited = set()

        def visit(node_id):
            if node_id in visiting:
                return visiting[visiting.index(node_id):] + [node_id]
            if node_id in visited or node_id not in self.nodes:
                return None
            visiting.append(node_id)
            for option in self.nodes[node_id]["options"]:
                target = option.get("target")
                if target is not None:
                    cycle = visit(target)
                    if cycle:
                        return cycle
            visiting.pop()
            visited.add(node_id)
            return None

        return visit(start)

    # ------------------------------------------------------------------ #
    # Option selection: precondition, consequences, one-time
    # ------------------------------------------------------------------ #
    def select_option(self, option_id=None, node_id=None):
        node_id = self.current_node if node_id is None else node_id
        node = self.nodes.get(node_id)
        if node is None:
            return {"success": False, "reason": "no_active_node"}

        option = next(
            (candidate for candidate in node["options"] if candidate["id"] == option_id),
            None,
        )
        if option is None:
            return {"success": False, "reason": "unknown_option"}

        if not self.evaluate_condition(option.get("condition")):
            return {"success": False, "reason": "precondition_failed"}

        if option["one_time"] and option["id"] in self.used_one_time_options:
            return {"success": False, "reason": "one_time_already_used"}

        consequences = dict(option.get("consequences") or {})
        for name, value in consequences.items():
            self.set_variable(name, value)

        self.option_history.append(option["id"])
        if option["one_time"]:
            self.used_one_time_options.add(option["id"])

        target = option.get("target")
        self.trigger_dialog_event(
            self.EVENT_OPTION,
            dialog_id=node_id,
            option_id=option["id"],
            target=target,
        )
        if target is not None:
            self.current_node = target

        return {
            "success": True,
            "option": option["id"],
            "next_node": self.current_node,
            "consequences": consequences,
        }

    # ------------------------------------------------------------------ #
    # Condition evaluation: comparisons, and/or/not, variables, cache
    # ------------------------------------------------------------------ #
    def set_variable(self, name, value):
        self.variables[name] = value
        self._condition_cache.clear()
        return value

    def evaluate_condition(self, condition=None, variables=None):
        if condition is None:
            return True

        namespace = self.variables if variables is None else variables
        cache_key = (
            self._condition_key(condition),
            tuple(sorted((str(key), repr(value)) for key, value in namespace.items())),
        )
        cached = self._condition_cache.get(cache_key)
        if cached is not None:
            return cached["result"]

        result = bool(self._evaluate(condition, namespace))
        self._condition_cache[cache_key] = {"result": result}
        return result

    @staticmethod
    def _condition_key(condition):
        try:
            hash(condition)
        except TypeError:
            return ("repr", repr(condition))
        return ("value", condition)

    def _evaluate(self, condition, variables):
        if callable(condition):
            return bool(condition(variables))
        if isinstance(condition, bool):
            return condition
        if isinstance(condition, (int, float, str)) and not isinstance(condition, bool):
            return condition if isinstance(condition, (int, float)) else self._eval_expression(condition, variables)
        if not isinstance(condition, dict):
            return bool(condition)

        if "and" in condition:
            return all(self._evaluate(child, variables) for child in condition["and"])
        if "or" in condition:
            return any(self._evaluate(child, variables) for child in condition["or"])
        if "not" in condition:
            return not self._evaluate(condition["not"], variables)

        name = condition.get("var")
        actual = self._resolve_value(name, variables)

        if "op" in condition:
            op = condition["op"]
            if op not in self._COMPARATORS:
                raise ValueError(f"unsupported operator: {op}")
            expected = self._resolve_value(condition.get("value"), variables)
            try:
                return self._COMPARATORS[op](actual, expected)
            except TypeError:
                return False

        if "value" in condition:
            return actual == self._resolve_value(condition.get("value"), variables)

        return bool(actual)

    @staticmethod
    def _resolve_value(value, variables):
        if isinstance(value, dict) and "var" in value:
            return variables.get(value["var"])
        if isinstance(value, str) and value in variables:
            return variables.get(value)
        return value

    @staticmethod
    def _eval_expression(expression, variables):
        namespace = dict(variables)
        namespace.update({
            "True": True,
            "False": False,
            "None": None,
            "__builtins__": {},
        })
        return bool(eval(expression, {"__builtins__": {}}, namespace))

    def invalidate_condition_cache(self):
        self._condition_cache.clear()

    # ------------------------------------------------------------------ #
    # Dialog events: timing, parameters, ordered queue
    # ------------------------------------------------------------------ #
    def start_dialog(self, node_id=None):
        if node_id is not None:
            self.current_node = node_id
        self.trigger_dialog_event(self.EVENT_START, dialog_id=self.current_node)
        return self.traverse_node(self.current_node)

    def end_dialog(self):
        dialog_id = self.current_node
        event = self.trigger_dialog_event(self.EVENT_END, dialog_id=dialog_id)
        self.current_node = None
        return event

    def trigger_dialog_event(self, event_type=None, dialog_id=None, **params):
        event = {
            "type": event_type or self.EVENT_START,
            "dialog_id": self.current_node if dialog_id is None else dialog_id,
            "params": params,
            "sequence": len(self.event_log) + len(self.event_queue),
        }
        self.event_queue.append(event)
        return event

    def process_events(self):
        processed = []
        while self.event_queue:
            event = self.event_queue.popleft()
            self.event_log.append(event)
            processed.append(event)
        return processed

    def pending_events(self):
        return list(self.event_queue)

    # ------------------------------------------------------------------ #
    # Save / load: current node, history, versioned format
    # ------------------------------------------------------------------ #
    def save_dialog_state(self):
        return {
            "version": self.SAVE_VERSION,
            "current_node": self.current_node,
            "variables": dict(self.variables),
            "option_history": list(self.option_history),
            "used_one_time_options": sorted(self.used_one_time_options),
            "visited_nodes": sorted(
                node_id for node_id, node in self.nodes.items() if node.get("visited")
            ),
        }

    def load_dialog_state(self, state):
        if not isinstance(state, dict):
            raise ValueError("invalid dialog save data")

        version = state.get("version", 1)
        if isinstance(version, int) and version > self.SAVE_VERSION:
            raise ValueError(f"unsupported save version: {version}")

        state = self._migrate_save(state, version)

        current_node = state.get("current_node")
        if current_node is not None and current_node not in self.nodes:
            current_node = None
        self.current_node = current_node

        self.variables = dict(state.get("variables", {}))
        self.option_history = list(state.get("option_history", []))
        self.used_one_time_options = set(state.get("used_one_time_options", []))
        for node_id in state.get("visited_nodes", []):
            node = self.nodes.get(node_id)
            if node is not None:
                node["visited"] = True

        self._condition_cache.clear()
        self.event_queue.clear()
        return True

    def _migrate_save(self, state, version):
        migrated = dict(state)
        if version == 1:
            migrated["current_node"] = state.get("current_node", state.get("node"))
            migrated.setdefault("option_history", list(state.get("history", [])))
            migrated.setdefault("variables", {})
            migrated.setdefault("used_one_time_options", [])
            migrated.setdefault("visited_nodes", [])
        migrated["version"] = self.SAVE_VERSION
        return migrated
