from collections.abc import Mapping
from typing import Any

from sqlalchemy.engine import Connection


def row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    mapping: Mapping[str, Any] = row._mapping
    return dict(mapping)


class BaseRepository:
    def __init__(self, connection: Connection):
        self.connection = connection
