from dataclasses import dataclass
from typing import Optional

@dataclass
class Venue:
    name: str
    city: Optional[str] = None
    id: Optional[int] = None
    country: Optional[str] = None

    @classmethod
    def builder(cls):
        return cls.Builder()

    class Builder:
        def __init__(self):
            self._name: Optional[str] = None
            self._city: Optional[str] = None
            self._id: Optional[int] = None
            self._country: Optional[str] = None

        def with_name(self, name: str):
            self._name = name
            return self

        def with_city(self, city: Optional[str]):
            self._city = city
            return self

        def with_id(self, id: Optional[int]):
            self._id = id
            return self

        def with_country(self, country: Optional[str]):
            self._country = country
            return self

        def build(self):
            if self._name is None:
                raise ValueError("Missing required fields for Venue")
            return Venue(
                name=self._name,
                city=self._city,
                id=self._id,
                country=self._country,
            )
