"""Write the API's OpenAPI document, the source of web/src/api/schema.d.ts. No database needed."""

import json
import sys
from pathlib import Path

from pydantic import SecretStr

from lumen.api.app import create_app
from lumen.config import Settings


def main(target: Path) -> None:
    settings = Settings(_env_file=None, secret_key=SecretStr("x" * 32), web_dist=None)
    document = create_app(settings).openapi()
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
