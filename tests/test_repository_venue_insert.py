"""
Ingestion's venue insert (db/repository.py::CricketRepository.get_or_create_venue)
and the shared country-name -> country_id lookup (db/venue_resolver.py::
get_or_create_country_id). history.venues has no `country` column - a new
venue must be written with country_id. No live DB connection required: a
scripted fake cursor stands in for psycopg2.
"""
from db.entities import Venue
from db.repository import CricketRepository
from db.venue_resolver import get_or_create_country_id, load_overrides


class _ScriptedCursor:
    """Records every execute; fetchone() pops the next scripted result."""

    def __init__(self, results):
        self.executed = []
        self._results = list(results)

    def execute(self, query, params=None):
        self.executed.append((" ".join(query.split()), params))

    def fetchone(self):
        return self._results.pop(0)


def _repo(cursor):
    repo = CricketRepository.__new__(CricketRepository)
    repo.cur = cursor
    repo._venues_cache = {}
    repo._country_ids = {}
    repo._venue_overrides = load_overrides()
    return repo


def _venue_insert(cursor):
    return next((q, p) for q, p in cursor.executed if q.startswith("INSERT INTO history.venues"))


class TestGetOrCreateCountryId:
    def test_new_country_is_inserted(self):
        cur = _ScriptedCursor([(77,)])
        cache = {}
        assert get_or_create_country_id(cur, "Narnia", cache) == 77
        assert cache == {"Narnia": 77}
        assert len(cur.executed) == 1

    def test_existing_country_is_looked_up_after_conflict(self):
        cur = _ScriptedCursor([None, (5,)])
        assert get_or_create_country_id(cur, "Bangladesh", {}) == 5
        assert cur.executed[1] == ("SELECT country_id FROM history.countries WHERE name = %s", ("Bangladesh",))

    def test_cached_country_skips_the_database(self):
        cur = _ScriptedCursor([])
        assert get_or_create_country_id(cur, "India", {"India": 1}) == 1
        assert cur.executed == []


class TestNewVenueInsert:
    def test_new_venue_is_written_with_country_id(self):
        # SELECT venue -> not found; country insert -> conflict; country SELECT -> 5; venue INSERT -> 9001
        cur = _ScriptedCursor([None, None, (5,), (9001,)])
        venue = _repo(cur).get_or_create_venue(Venue(name="Brand New Ground", city="Mirpur"))

        query, params = _venue_insert(cur)
        assert query == "INSERT INTO history.venues (name, city, country_id) VALUES (%s, %s, %s) RETURNING venue_id"
        assert params == ("Brand New Ground", "Mirpur", 5)
        assert venue.id == 9001
        assert venue.country == "Bangladesh"

    def test_unresolvable_country_inserts_null_country_id(self):
        # SELECT venue -> not found; venue INSERT -> 9002. No country lookup at all.
        cur = _ScriptedCursor([None, (9002,)])
        venue = _repo(cur).get_or_create_venue(Venue(name="Nowhere Oval", city="Atlantis"))

        query, params = _venue_insert(cur)
        assert "(name, city, country_id)" in query
        assert params == ("Nowhere Oval", "Atlantis", None)
        assert not any("history.countries" in q for q, _ in cur.executed)
        assert venue.id == 9002

    def test_second_new_venue_in_same_country_reuses_cached_country_id(self):
        cur = _ScriptedCursor([None, None, (5,), (9001,), None, (9003,)])
        repo = _repo(cur)
        repo.get_or_create_venue(Venue(name="Brand New Ground", city="Mirpur"))
        repo.get_or_create_venue(Venue(name="Another New Ground", city="Mirpur"))

        country_queries = [q for q, _ in cur.executed if "history.countries" in q]
        assert len(country_queries) == 2  # one insert + one select, for the first venue only
        assert [p[2] for q, p in cur.executed if q.startswith("INSERT INTO history.venues")] == [5, 5]
