"""Expression engine — safe Jinja2 sandbox for ``{{node.field}}`` variable resolution.

Uses ``jinja2.sandbox.SandboxedEnvironment`` to prevent arbitrary code execution.
Expressions are evaluated against the Task's variable pool.

Expression syntax: ``{{ node_id.field_path }}``
- ``node_id``: ID of a workflow node (or ``input`` for Task input)
- ``field_path``: Dot-separated path to the field value

Safety:
- No access to Python builtins or modules
- No I/O operations
- No ``__`` dunder access
- Undefined variables resolve to ``None`` (never raise)
- Template syntax errors are caught and return ``None``
"""
from __future__ import annotations

import ast
import json
import re
from typing import Any

from jinja2 import BaseLoader, ChainableUndefined
from jinja2.sandbox import SandboxedEnvironment
from loguru import logger

# Regex to find all ``{{...}}`` expressions in a string
_EXPRESSION_PATTERN = re.compile(r"\{\{(.+?)\}\}")

# Regex to detect JSON-like strings (starts with { or [)
_JSON_PATTERN = re.compile(r"^\s*[\[{]")

# Regex to strip markdown code blocks
_MARKDOWN_CODE_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _try_parse_json(value: Any) -> Any:
    """Try to parse a string as JSON. Returns the original value if parsing fails."""
    if not isinstance(value, str):
        return value

    # Strip markdown code blocks if present
    match = _MARKDOWN_CODE_BLOCK.search(value)
    if match:
        value = match.group(1).strip()

    # Quick check: does it look like JSON?
    if not _JSON_PATTERN.match(value):
        return value

    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def _deep_parse_json_strings(obj: Any) -> Any:
    """Recursively parse JSON strings in a dict/list structure."""
    if isinstance(obj, dict):
        return {k: _deep_parse_json_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_deep_parse_json_strings(item) for item in obj]
    elif isinstance(obj, str):
        parsed = _try_parse_json(obj)
        if isinstance(parsed, (dict, list)):
            return _deep_parse_json_strings(parsed)
        return parsed
    return obj


class ExpressionEngine:
    """Safe expression resolver for ``{{node.field}}`` syntax.

    Usage::

        engine = ExpressionEngine(variable_pool)
        result = engine.resolve("{{input.user_name}} is {{node1.result.status}}")
        # Returns: "Alice is success"
    """

    def __init__(self, variables: dict[str, Any]) -> None:
        # Pre-parse JSON strings in variables to enable nested field access
        self._variables = _deep_parse_json_strings(variables)
        self._env = self._build_env()

    @staticmethod
    def _build_env() -> SandboxedEnvironment:
        """Build a sandboxed Jinja2 environment with no dangerous globals."""
        env = SandboxedEnvironment(
            loader=BaseLoader(),
            autoescape=False,
            undefined=ChainableUndefined,
        )
        # Remove all builtins to prevent code execution
        env.globals.clear()
        return env

    def resolve(self, template: str) -> Any:
        """Resolve all ``{{...}}`` expressions in *template* against the variable pool.

        Args:
            template: A string that may contain ``{{node.field}}`` expressions.

        Returns:
            The resolved value. If *template* contains only a single expression,
            returns the resolved value directly (not wrapped in a string).
            If the resolved string contains comparison operators (==, !=, >, <, etc.),
            evaluates the comparison and returns a boolean.
            Otherwise, returns the string with expressions substituted.
        """
        if not template or not _EXPRESSION_PATTERN.search(template):
            # No {{...}} expressions — check if it's a plain comparison
            return self._try_eval_comparison(template)

        stripped = template.strip()

        # Fast path: entire string is a single expression — preserve original type
        if _EXPRESSION_PATTERN.fullmatch(stripped) and stripped.count("{{") == 1:
            expr = _EXPRESSION_PATTERN.match(stripped).group(1).strip()  # type: ignore[union-attr]
            return self._eval_expression_typed(expr)

        # General path: substitute all expressions within the string
        try:
            jinja_template = self._env.from_string(template)
            rendered = jinja_template.render(self._variables)
        except Exception:
            logger.warning("expression_render_failed", template=template[:100])
            return template

        # After substitution, check if result contains comparison operators
        return self._try_eval_comparison(rendered)

    def _try_eval_comparison(self, expr: str) -> Any:
        """Try to evaluate a string as a comparison expression.

        Supports: ==, !=, >=, <=, >, <
        Returns the boolean result if it's a comparison, otherwise returns the original string.
        """
        if not isinstance(expr, str):
            return expr

        # Comparison operators in order of precedence (longer operators first)
        operators = ["==", "!=", ">=", "<=", ">", "<"]

        for op in operators:
            if op in expr:
                parts = expr.split(op, 1)
                if len(parts) == 2:
                    left = parts[0].strip()
                    right = parts[1].strip()

                    # Try to parse both sides as Python literals
                    left_val = self._parse_value(left)
                    right_val = self._parse_value(right)

                    # Evaluate the comparison
                    try:
                        if op == "==":
                            return left_val == right_val
                        elif op == "!=":
                            return left_val != right_val
                        elif op == ">=":
                            return left_val >= right_val
                        elif op == "<=":
                            return left_val <= right_val
                        elif op == ">":
                            return left_val > right_val
                        elif op == "<":
                            return left_val < right_val
                    except TypeError:
                        # Type mismatch in comparison, return original
                        pass

                # Only evaluate the first matching operator
                break

        return expr

    def _parse_value(self, s: str) -> Any:
        """Parse a string value into its Python type.

        Handles: strings (quoted), numbers, booleans, null/None.
        """
        s = s.strip()

        # Quoted string
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]

        # Boolean
        if s.lower() == "true":
            return True
        if s.lower() == "false":
            return False

        # Null/None
        if s.lower() in ("null", "none"):
            return None

        # Number
        try:
            if "." in s:
                return float(s)
            return int(s)
        except ValueError:
            pass

        # Return as string (unquoted)
        return s

    def resolve_bool(self, template: str) -> bool:
        """Resolve an expression and coerce the result to bool.

        Returns ``False`` for undefined/missing variables (fail-safe).
        """
        result = self.resolve(template)
        if result is None:
            return False
        if isinstance(result, str):
            # Jinja2 renders ``{{ False }}`` as the string "False"
            if result.lower() == "false":
                return False
            if result.lower() == "true":
                return True
            return bool(result)
        return bool(result)

    def resolve_dict(
        self,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Recursively resolve all expression values in a dict."""
        resolved: dict[str, Any] = {}
        for key, value in config.items():
            if isinstance(value, str):
                resolved[key] = self.resolve(value)
            elif isinstance(value, dict):
                resolved[key] = self.resolve_dict(value)
            elif isinstance(value, list):
                resolved[key] = [self.resolve(item) if isinstance(item, str) else item for item in value]
            else:
                resolved[key] = value
        return resolved

    def _eval_expression(self, expression: str) -> Any:
        """Evaluate a single expression string against the variable pool.

        Returns ``None`` on any error (undefined variable, syntax error, etc.).
        """
        try:
            jinja_template = self._env.from_string("{{ " + expression + " }}")
            return jinja_template.render(self._variables)
        except Exception:
            logger.debug("expression_eval_failed", expression=expression[:100])
            return None

    def _eval_expression_typed(self, expression: str) -> Any:
        """Evaluate a single expression and preserve the original Python type.

        ``_eval_expression`` always returns a string (Jinja2 render result).
        This method attempts to restore the original type via ``ast.literal_eval``.
        Falls back to the raw string if parsing fails.
        """
        raw = self._eval_expression(expression)
        if raw is None or not isinstance(raw, str):
            return raw
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return raw


