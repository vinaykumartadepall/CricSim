import os
import glob
from db.repository import CricketRepository
from parser import CricsheetParser
from simulator.logger import get_logger

DATA_DIR = os.path.join(os.getcwd(), 'data/all_json')


def _save_match(repo, parsed_context):
    # 1. Update/Save Tournament
    parsed_context.tournament = repo.get_or_create_tournament(parsed_context.tournament)

    # 2. Update/Save Teams & TournamentTeams
    for t_name, team in parsed_context.teams.items():
        parsed_context.teams[t_name] = repo.get_or_create_team(team)
        repo.add_tournament_team(parsed_context.tournament, parsed_context.teams[t_name])

    # 3. Update/Save Venue
    parsed_context.venue = repo.get_or_create_venue(parsed_context.venue)

    # 4. Update/Save Players
    for p_name, player in parsed_context.players.items():
        parsed_context.players[p_name] = repo.get_or_create_player(player)

    # 5. Save Match (Deliveries are also saved here)
    repo.save_match(parsed_context.match)

    # 6. Save JOIN Tables (MATCH_PLAYERS)
    for team_name, p_list in parsed_context.players_dict.items():
        tm = parsed_context.teams.get(team_name)
        for p_name in p_list:
            pl = parsed_context.players.get(p_name)
            if tm and pl:
                repo.add_match_player(parsed_context.match, tm, pl)


def ingest_data(limit=None) -> dict:
    """Ingest every not-yet-ingested Cricsheet JSON file in DATA_DIR.

    Each match is saved inside its own savepoint: a match that fails to parse
    or save is rolled back on its own, logged to errors.log with its file
    name, and ingestion continues. Failed matches are never half-saved, so a
    re-run picks them up once the cause is fixed. Returns
    {"ingested": int, "already_present": int, "failed": [(file, stage, error)]}
    so callers (db/refresh.py) can stop on failures instead of missing them.
    """
    log = get_logger()
    repo = CricketRepository()

    files = glob.glob(os.path.join(DATA_DIR, '*.json'))
    if limit:
        files = files[:limit]

    print(f"Found {len(files)} files. Starting ingestion...")

    count = 0
    skipped = 0
    failed = []
    COMMIT_BATCH_SIZE = 100

    for file_path in files:
        original_id = os.path.basename(file_path)

        # Checkpoint: Skip if exists
        if repo.exists_match(original_id):
            skipped += 1
            if skipped % 1000 == 0:
                print(f"Skipped {skipped} existing matches...")
            continue

        try:
            parsed_context = CricsheetParser.parse(file_path)
        except Exception as e:
            log.exception("Ingest: failed to parse %s", original_id)
            print(f"Error parsing {file_path}: {e}")
            failed.append((original_id, "parse", str(e)))
            continue

        if parsed_context is None:
            continue

        repo.cur.execute("SAVEPOINT ingest_match")
        try:
            _save_match(repo, parsed_context)
        except Exception as e:
            repo.cur.execute("ROLLBACK TO SAVEPOINT ingest_match")
            repo.forget_cached_ids()
            log.exception("Ingest: failed to save %s - match skipped", original_id)
            print(f"Error saving {original_id} - skipped: {e}")
            failed.append((original_id, "save", str(e)))
            continue
        repo.cur.execute("RELEASE SAVEPOINT ingest_match")

        count += 1
        if count % 10 == 0:
            print(f"Processed {count} matches...")

        if count % COMMIT_BATCH_SIZE == 0:
            repo.commit()
            print(f"Checkpoint: Committed {count} matches.")

    # Final Commit
    repo.commit()
    repo.close()
    print(f"Ingestion Complete. Ingested {count}, already present {skipped}, failed {len(failed)}.")
    for name, stage, err in failed:
        print(f"  FAILED ({stage}) {name}: {err.splitlines()[0] if err else ''}")
    return {"ingested": count, "already_present": skipped, "failed": failed}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, help='Limit number of files to ingest')
    args = parser.parse_args()

    ingest_data(limit=args.limit)
