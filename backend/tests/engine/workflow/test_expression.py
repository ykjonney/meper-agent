"""ExpressionEngine unit tests — type preservation, resolve, resolve_bool, resolve_dict."""
from __future__ import annotations

from app.engine.workflow.expression import ExpressionEngine

# ── resolve ──


class TestResolve:
    """Tests for ExpressionEngine.resolve()."""

    def test_single_expression_returns_raw_value(self) -> None:
        engine = ExpressionEngine({"node1": {"status": "ok"}})
        assert engine.resolve("{{ node1.status }}") == "ok"

    def test_multiple_expressions_string_substitution(self) -> None:
        engine = ExpressionEngine({"a": "hello", "b": "world"})
        result = engine.resolve("{{ a }} plus {{ b }}")
        assert "hello" in result
        assert "world" in result

    def test_no_expression_returns_template(self) -> None:
        engine = ExpressionEngine({})
        assert engine.resolve("plain text") == "plain text"

    def test_mixed_text_expression(self) -> None:
        engine = ExpressionEngine({"name": "Alice"})
        assert engine.resolve("Hello {{ name }}!") == "Hello Alice!"

    def test_empty_string_returns_empty(self) -> None:
        engine = ExpressionEngine({})
        assert engine.resolve("") == ""

    def test_none_template_returns_none(self) -> None:
        engine = ExpressionEngine({})
        assert engine.resolve(None) is None  # type: ignore[arg-type]


# ── type preservation ──


class TestTypePreservation:
    """Tests that _eval_expression_typed preserves Python types."""

    def test_int_preserved(self) -> None:
        engine = ExpressionEngine({"count": 42})
        result = engine.resolve("{{ count }}")
        assert result == 42
        assert isinstance(result, int)

    def test_float_preserved(self) -> None:
        engine = ExpressionEngine({"score": 3.14})
        result = engine.resolve("{{ score }}")
        assert result == 3.14
        assert isinstance(result, float)

    def test_bool_true_preserved(self) -> None:
        engine = ExpressionEngine({"flag": True})
        result = engine.resolve("{{ flag }}")
        assert result is True

    def test_bool_false_preserved(self) -> None:
        engine = ExpressionEngine({"flag": False})
        result = engine.resolve("{{ flag }}")
        assert result is False

    def test_none_preserved(self) -> None:
        engine = ExpressionEngine({"value": None})
        # Jinja2 renders None as "None" string, then ast.literal_eval restores it
        result = engine.resolve("{{ value }}")
        assert result is None

    def test_list_preserved(self) -> None:
        engine = ExpressionEngine({"items": [1, 2, 3]})
        result = engine.resolve("{{ items }}")
        assert result == [1, 2, 3]

    def test_dict_preserved(self) -> None:
        engine = ExpressionEngine({"data": {"key": "val"}})
        result = engine.resolve("{{ data }}")
        assert result == {"key": "val"}

    def test_string_stays_string(self) -> None:
        engine = ExpressionEngine({"name": "hello world"})
        result = engine.resolve("{{ name }}")
        assert result == "hello world"
        assert isinstance(result, str)


# ── resolve_bool ──


class TestResolveBool:
    """Tests for ExpressionEngine.resolve_bool()."""

    def test_python_true(self) -> None:
        engine = ExpressionEngine({"flag": True})
        assert engine.resolve_bool("{{ flag }}") is True

    def test_python_false(self) -> None:
        engine = ExpressionEngine({"flag": False})
        assert engine.resolve_bool("{{ flag }}") is False

    def test_string_true(self) -> None:
        engine = ExpressionEngine({"v": "true"})
        assert engine.resolve_bool("{{ v }}") is True

    def test_string_false(self) -> None:
        engine = ExpressionEngine({"v": "false"})
        assert engine.resolve_bool("{{ v }}") is False

    def test_nonexistent_expression_returns_false(self) -> None:
        engine = ExpressionEngine({})
        # Undefined variable renders to empty string in ChainableUndefined
        assert engine.resolve_bool("{{ nonexistent_var }}") is False

    def test_nonzero_int(self) -> None:
        engine = ExpressionEngine({"n": 1})
        assert engine.resolve_bool("{{ n }}") is True

    def test_zero_int(self) -> None:
        engine = ExpressionEngine({"n": 0})
        assert engine.resolve_bool("{{ n }}") is False

    def test_nonzero_float(self) -> None:
        engine = ExpressionEngine({"n": 0.5})
        assert engine.resolve_bool("{{ n }}") is True

    def test_empty_string_resolved(self) -> None:
        engine = ExpressionEngine({"v": ""})
        assert engine.resolve_bool("{{ v }}") is False


# ── resolve_dict ──


class TestResolveDict:
    """Tests for ExpressionEngine.resolve_dict()."""

    def test_nested_dict_resolution(self) -> None:
        engine = ExpressionEngine({"node1": {"result": "ok"}})
        config = {"outer": {"inner": "{{ node1.result }}"}}
        result = engine.resolve_dict(config)
        assert result == {"outer": {"inner": "ok"}}

    def test_list_expression_resolution(self) -> None:
        engine = ExpressionEngine({"a": "x", "b": "y"})
        config = {"items": ["{{ a }}", "{{ b }}", "plain"]}
        result = engine.resolve_dict(config)
        assert result == {"items": ["x", "y", "plain"]}

    def test_non_string_values_preserved(self) -> None:
        engine = ExpressionEngine({})
        config = {"count": 42, "flag": True, "data": [1, 2]}
        result = engine.resolve_dict(config)
        assert result == {"count": 42, "flag": True, "data": [1, 2]}

    def test_empty_dict(self) -> None:
        engine = ExpressionEngine({})
        assert engine.resolve_dict({}) == {}

    def test_mixed_types_in_dict(self) -> None:
        engine = ExpressionEngine({"name": "Alice", "age": 30})
        config = {
            "greeting": "Hello {{ name }}",
            "raw_number": 42,
            "nested": {"key": "{{ name }}"},
        }
        result = engine.resolve_dict(config)
        assert result["greeting"] == "Hello Alice"
        assert result["raw_number"] == 42
        assert result["nested"]["key"] == "Alice"


# ── _eval_expression_typed ──


class TestEvalExpressionTyped:
    """Tests for ExpressionEngine._eval_expression_typed()."""

    def test_int_type_restore(self) -> None:
        engine = ExpressionEngine({"n": 42})
        assert engine._eval_expression_typed("n") == 42

    def test_float_type_restore(self) -> None:
        engine = ExpressionEngine({"n": 3.14})
        assert engine._eval_expression_typed("n") == 3.14

    def test_bool_true_restore(self) -> None:
        engine = ExpressionEngine({"f": True})
        assert engine._eval_expression_typed("f") is True

    def test_bool_false_restore(self) -> None:
        engine = ExpressionEngine({"f": False})
        assert engine._eval_expression_typed("f") is False

    def test_none_restore(self) -> None:
        engine = ExpressionEngine({"v": None})
        assert engine._eval_expression_typed("v") is None

    def test_string_no_conversion(self) -> None:
        engine = ExpressionEngine({"s": "hello world"})
        result = engine._eval_expression_typed("s")
        assert result == "hello world"
        assert isinstance(result, str)

    def test_undefined_returns_empty_string(self) -> None:
        engine = ExpressionEngine({})
        # Undefined variable → ChainableUndefined renders to ""
        result = engine._eval_expression_typed("nonexistent")
        assert result == ""
