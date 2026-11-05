"""Tests for LLM thinking parameter adaptation.

The pure thinking-kwargs logic now lives in ``agent_flow_harness.llm.thinking``.
These tests validate it via the harness public API to ensure the delegate
in ``app.engine.llm_factory`` is wired correctly.
"""

from agent_flow_harness import build_thinking_kwargs, supports_thinking


class TestBuildThinkingKwargs:
    """Test build_thinking_kwargs returns correct params per provider."""

    def test_thinking_disabled_returns_empty(self):
        result = build_thinking_kwargs("gpt-4o", "openai", False, None)
        assert result == {"extra_body": {"thinking": {"type": "disabled"}}}

    def test_anthropic_thinking_enabled(self):
        result = build_thinking_kwargs("claude-sonnet-4", "anthropic", True, None)
        assert "thinking" in result
        assert result["thinking"]["type"] == "enabled"
        assert result["thinking"]["budget_tokens"] > 0
        # Should auto-set max_tokens since none provided
        assert "max_tokens" in result

    def test_anthropic_thinking_with_sufficient_max_tokens(self):
        result = build_thinking_kwargs(
            "claude-sonnet-4", "anthropic", True, max_tokens=16000
        )
        assert "thinking" in result
        assert result["thinking"]["type"] == "enabled"

    def test_anthropic_thinking_insufficient_max_tokens(self):
        """max_tokens below the floor (< 2048): thinking is explicitly disabled
        so gateways that default it on don't duplicate reasoning in text."""
        result = build_thinking_kwargs(
            "claude-sonnet-4", "anthropic", True, max_tokens=1000
        )
        assert result == {"thinking": {"type": "disabled"}}

    def test_anthropic_thinking_budget_adapts_to_max_tokens(self):
        """max_tokens above the floor but below the default budget: the
        budget adapts to half the window instead of dropping thinking."""
        result = build_thinking_kwargs(
            "claude-sonnet-4", "anthropic", True, max_tokens=4096
        )
        assert result["thinking"] == {"type": "enabled", "budget_tokens": 2048}

    def test_openai_reasoning_model(self):
        result = build_thinking_kwargs("o3-mini", "openai", True, None)
        assert result == {"reasoning_effort": "high"}

    def test_openai_o1_reasoning(self):
        result = build_thinking_kwargs("o1-preview", "openai", True, None)
        assert result == {"reasoning_effort": "high"}

    def test_openai_o4_reasoning(self):
        result = build_thinking_kwargs("o4-mini", "openai", True, None)
        assert result == {"reasoning_effort": "high"}

    def test_openai_non_reasoning_model_ignored(self):
        """GPT-4o does not support reasoning_effort."""
        result = build_thinking_kwargs("gpt-4o", "openai", True, None)
        assert result == {}

    def test_openai_non_reasoning_model_with_prefix(self):
        """gpt-o1 should not match (it starts with gpt-, not o1-)."""
        result = build_thinking_kwargs("gpt-o1", "openai", True, None)
        assert result == {}

    def test_unknown_provider_ignored(self):
        result = build_thinking_kwargs("some-model", "custom", True, None)
        assert result == {}


class TestSupportsThinking:
    """Test supports_thinking helper for UI pre-validation."""

    def test_anthropic_supported(self):
        assert supports_thinking("claude-sonnet-4", "anthropic") is True

    def test_openai_o_series_supported(self):
        assert supports_thinking("o3-mini", "openai") is True
        assert supports_thinking("o1-preview", "openai") is True
        assert supports_thinking("o4-mini", "openai") is True

    def test_openai_gpt_not_supported(self):
        assert supports_thinking("gpt-4o", "openai") is False

    def test_unknown_provider_not_supported(self):
        assert supports_thinking("some-model", "custom") is False


class TestThinkingLevel:
    """档位路径（thinking_level 优先于旧布尔 enable_thinking）。

    档位映射：o-series reasoning_effort 直传；Anthropic budget
    low/medium/high = 2048/8192/16384；Qwen·GLM off 关、其余开。
    """

    def test_glm_off_disables(self):
        result = build_thinking_kwargs("glm-5.2", "openai", False, None,
                                       thinking_level="off")
        assert result == {"extra_body": {"thinking": {"type": "disabled"}}}

    def test_glm_high_enables(self):
        result = build_thinking_kwargs("glm-5.2", "openai", False, None,
                                       thinking_level="high")
        assert result == {"extra_body": {"thinking": {"type": "enabled"}}}

    def test_qwen_low_enables(self):
        result = build_thinking_kwargs("qwen3.7-plus", "openai", False, None,
                                       thinking_level="low")
        assert result == {"extra_body": {"enable_thinking": True}}

    def test_qwen_off_disables(self):
        result = build_thinking_kwargs("qwen3.7-plus", "openai", False, None,
                                       thinking_level="off")
        assert result == {"extra_body": {"enable_thinking": False}}

    def test_anthropic_level_budgets(self):
        for level, budget in (("low", 2048), ("medium", 8192), ("high", 16384)):
            result = build_thinking_kwargs("claude-sonnet-4", "anthropic", False,
                                           None, thinking_level=level)
            assert result["thinking"] == {"type": "enabled", "budget_tokens": budget}

    def test_anthropic_level_budget_capped_by_max_tokens(self):
        """max_tokens 约束在档位路径同样生效（budget ≤ max_tokens/2）。"""
        result = build_thinking_kwargs("claude-sonnet-4", "anthropic", False,
                                       max_tokens=4096, thinking_level="high")
        assert result["thinking"]["budget_tokens"] == 2048

    def test_o_series_level_passthrough(self):
        for level in ("low", "medium", "high"):
            result = build_thinking_kwargs("o3-mini", "openai", False, None,
                                           thinking_level=level)
            assert result == {"reasoning_effort": level}

    def test_level_overrides_legacy_bool(self):
        """thinking_level 显式给出时忽略 enable_thinking 布尔。"""
        result = build_thinking_kwargs("glm-5.2", "openai", True, None,
                                       thinking_level="off")
        assert result == {"extra_body": {"thinking": {"type": "disabled"}}}

    def test_legacy_bool_keeps_legacy_behavior(self):
        """旧调用（无 thinking_level）零行为变化：anthropic 用模型默认预算
        5000、o-series 保持写死 high——旧行为不因档位化而漂移。"""
        result = build_thinking_kwargs("claude-sonnet-4", "anthropic", True, None,
                                       thinking_level="")
        assert result["thinking"]["budget_tokens"] == 5000
        result = build_thinking_kwargs("o3-mini", "openai", True, None,
                                       thinking_level="")
        assert result == {"reasoning_effort": "high"}
