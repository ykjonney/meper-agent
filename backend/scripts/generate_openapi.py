"""Script to export the FastAPI OpenAPI schema to openapi.json for client generation."""
import json
from pathlib import Path

from app.main import app


def main() -> None:
    """Dump the OpenAPI schema to backend/openapi.json."""
    schema = app.openapi()
    out = Path("openapi.json")
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OpenAPI schema exported to {out.resolve()}")


if __name__ == "__main__":
    main()
