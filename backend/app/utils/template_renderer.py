"""Template renderer for trigger default_input values."""
from datetime import UTC, datetime
from typing import Any

from jinja2 import Template, TemplateError
from loguru import logger


def render_default_input(default_input: dict[str, Any]) -> dict[str, Any]:
    """Render default input parameters with Jinja2 template syntax.

    Supported built-in variables:
    - {{ now() }}: Current UTC time (ISO format)
    - {{ today() }}: Current date (YYYY-MM-DD)

    Args:
        default_input: Default input parameters dict, values can be template strings.

    Returns:
        Rendered parameters dict.
    """
    context = {
        "now": lambda: datetime.now(UTC).isoformat(),
        "today": lambda: datetime.now(UTC).strftime("%Y-%m-%d"),
    }

    rendered = {}
    for key, value in default_input.items():
        if isinstance(value, str) and "{{" in value:
            try:
                template = Template(value)
                rendered[key] = template.render(**context)
            except TemplateError as e:
                logger.warning(
                    "template_render_failed",
                    key=key,
                    template=value,
                    error=str(e),
                )
                # Fallback: return original string
                rendered[key] = value
        else:
            rendered[key] = value

    return rendered
