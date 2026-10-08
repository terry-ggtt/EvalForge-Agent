import json
from pathlib import Path
from typing import Any

from app.datasets.loader import (
    DatasetLoader,
)


class JsonDatasetLoader(
    DatasetLoader
):

    def load(
        self,
        source: str | Path,
    ) -> list[dict[str, Any]]:

        path = Path(source)

        with path.open(
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if not isinstance(
            data,
            list,
        ):
            raise ValueError(
                "JSON dataset must be a list"
            )

        return data