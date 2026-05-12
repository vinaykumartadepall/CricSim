from dataclasses import dataclass
from typing import Optional

@dataclass
class Tournament:
    name: str
    season: str
    id: Optional[int] = None

    @classmethod
    def builder(cls):
        return cls.Builder()

    class Builder:
        def __init__(self):
            self._name: Optional[str] = None
            self._season: Optional[str] = None
            self._id: Optional[int] = None

        def with_name(self, name: str):
            self._name = name
            return self

        def with_season(self, season: str):
            self._season = season
            return self

        def with_id(self, id: Optional[int]):
            self._id = id
            return self

        def build(self):
            if any(x is None for x in [self._name, self._season]):
                raise ValueError("Missing required fields for Tournament")
            return Tournament(
                name=self._name,
                season=self._season,
                id=self._id
            )
