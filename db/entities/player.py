from dataclasses import dataclass
from typing import Optional

@dataclass
class Player:
    code: str
    name: str
    gender: str
    original_name: Optional[str] = None
    id: Optional[int] = None

    @classmethod
    def builder(cls):
        return cls.Builder()

    class Builder:
        def __init__(self):
            self._code: Optional[str] = None
            self._name: Optional[str] = None
            self._gender: Optional[str] = None
            self._original_name: Optional[str] = None
            self._id: Optional[int] = None

        def with_code(self, code: str):
            self._code = code
            return self

        def with_name(self, name: str):
            self._name = name
            return self

        def with_gender(self, gender: str):
            self._gender = gender
            return self

        def with_original_name(self, original_name: Optional[str]):
            self._original_name = original_name
            return self

        def with_id(self, id: Optional[int]):
            self._id = id
            return self

        def build(self):
            if any(x is None for x in [self._code, self._name, self._gender]):
                raise ValueError("Missing required fields for Player")
            return Player(
                code=self._code,
                name=self._name,
                gender=self._gender,
                original_name=self._original_name,
                id=self._id
            )
