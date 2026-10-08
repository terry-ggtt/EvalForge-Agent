import json
from pathlib import Path
from typing import Any

from app.datasets.loader import (
    DatasetLoader,
)


class JsonlDatasetLoader(
    DatasetLoader
):

    def load(
        self,
        source: str | Path,
    ) -> list[dict[str, Any]]:

        path = Path(source)

        cases = []

        with path.open(
            "r",
            encoding="utf-8",
        ) as f:

            for line in f:

                line = line.strip()

                if not line:
                    continue

                cases.append(
                    json.loads(line)
                )

        return cases