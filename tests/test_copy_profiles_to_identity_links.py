"""
db/copy_profiles_to_identity_links.py - the one-time simulation.profiles ->
simulation.identity_links copy script. Only _dedupe_usernames is pure logic
worth unit testing; the rest is direct DB I/O exercised manually per the
project's migration convention (see db/dedup_venues.py).
"""
from db.copy_profiles_to_identity_links import _dedupe_usernames


class TestDedupeUsernames:
    def test_no_collisions_keeps_names_as_is(self):
        profiles = [
            {"user_id": "u1", "display_name": "Alice"},
            {"user_id": "u2", "display_name": "Bob"},
        ]
        out = _dedupe_usernames(profiles, taken_lower=set())
        assert [p["final_username"] for p in out] == ["Alice", "Bob"]

    def test_collision_against_existing_identity_links_row_is_suffixed(self):
        profiles = [{"user_id": "u1", "display_name": "Alice"}]
        out = _dedupe_usernames(profiles, taken_lower={"alice"})
        assert out[0]["final_username"] == "Alice_2"

    def test_collision_within_batch_orders_by_input_order(self):
        """profiles is expected pre-sorted by created_at ASC by the caller -
        the earliest account keeps the unsuffixed name."""
        profiles = [
            {"user_id": "u1", "display_name": "Alice"},
            {"user_id": "u2", "display_name": "Alice"},
            {"user_id": "u3", "display_name": "Alice"},
        ]
        out = _dedupe_usernames(profiles, taken_lower=set())
        assert [p["final_username"] for p in out] == ["Alice", "Alice_2", "Alice_3"]

    def test_collision_is_case_insensitive(self):
        profiles = [
            {"user_id": "u1", "display_name": "Alice"},
            {"user_id": "u2", "display_name": "ALICE"},
        ]
        out = _dedupe_usernames(profiles, taken_lower=set())
        assert [p["final_username"] for p in out] == ["Alice", "ALICE_2"]

    def test_taken_lower_set_is_mutated_so_later_batches_see_earlier_renames(self):
        taken: set = set()
        first = _dedupe_usernames([{"user_id": "u1", "display_name": "Alice"}], taken)
        second = _dedupe_usernames([{"user_id": "u2", "display_name": "Alice"}], taken)
        assert first[0]["final_username"] == "Alice"
        assert second[0]["final_username"] == "Alice_2"
