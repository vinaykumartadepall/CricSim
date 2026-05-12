from dataclasses import dataclass
from typing import Optional

@dataclass
class Team:
    name: str
    type: str # 'international', 'club'
    gender: str
    id: Optional[int] = None

    @classmethod
    def builder(cls):
        return cls.Builder()

    class Builder:
        def __init__(self):
            self._name: Optional[str] = None
            self._type: Optional[str] = None
            self._gender: Optional[str] = None
            self._id: Optional[int] = None

        def with_name(self, name: str):
            self._name = name
            return self

        def with_type(self, type: str):
            self._type = type
            return self

        def with_gender(self, gender: str):
            self._gender = gender
            return self

        def with_id(self, id: Optional[int]):
            self._id = id
            return self

        def build(self):
            if any(x is None for x in [self._name, self._type, self._gender]):
                raise ValueError("Missing required fields for Team")
            return Team(
                name=self._name,
                type=self._type,
                gender=self._gender,
                id=self._id
            )
