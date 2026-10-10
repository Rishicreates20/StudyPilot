"""Write the API's OpenAPI document to packages/contracts/openapi.json.

The document is the single source of truth for the HTTP contract; the web app's TypeScript types
are generated from it. The output is deterministic (fixed configuration, sorted keys) so CI can
regenerate it and fail on any difference.

    uv run --directory services/api python -m scripts.export_openapi
"""

import json
from pathlib import Path

from app.core.config import Settings
from app.main import create_app

OUTPUT = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi.json"


def build_document() -> dict[str, object]:
    # model_validate never reads the environment or .env files, so the result cannot depend on
    # whatever the developer (or CI) has configured.
    settings = Settings.model_validate({"app_env": "test"})
    return create_app(settings).openapi()


def main() -> None:
    document = build_document()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": the same bytes on every platform, so the CI drift check cannot trip over
    # Windows line endings.
    OUTPUT.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
