"""
`sudo systemctl kill -s USR1 cricsim-api` clears the API's in-memory stats
cache (db.stats_repository._PRECOMPUTED_CACHE) so a data refresh is picked up
without a restart. No live DB connection required.
"""
import os
import signal

import pytest

import api.main as main_mod
import db.stats_repository as sr_mod


@pytest.fixture
def populated_cache(monkeypatch):
    cache = {("ts", 1): {"x": 1.0}, ("cs", "India", "T20", "male"): {"y": 2.0}}
    monkeypatch.setattr(sr_mod, "_PRECOMPUTED_CACHE", cache)
    return cache


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="no SIGUSR1 on this platform")
class TestCacheClearSignal:
    def test_handler_is_installed_on_import(self):
        assert signal.getsignal(signal.SIGUSR1) is main_mod._clear_stats_cache_on_signal

    def test_sigusr1_clears_the_stats_cache(self, populated_cache):
        os.kill(os.getpid(), signal.SIGUSR1)
        assert populated_cache == {}

    def test_handler_logs_how_many_entries_were_cleared(self, populated_cache, monkeypatch):
        logged = []
        monkeypatch.setattr(main_mod, "get_logger",
                            lambda: type("L", (), {"warning": lambda self, *a: logged.append(a)})())
        main_mod._clear_stats_cache_on_signal(signal.SIGUSR1, None)
        assert populated_cache == {}
        assert logged and logged[0][1] == 2
