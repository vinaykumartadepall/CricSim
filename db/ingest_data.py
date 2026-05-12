import os
import glob
from db.repository import CricketRepository
from parser import CricsheetParser

DATA_DIR = os.path.join(os.getcwd(), 'data/all_json')

def ingest_data(limit=None):
    repo = CricketRepository()
    
    files = glob.glob(os.path.join(DATA_DIR, '*.json'))
    if limit:
        files = files[:limit]
        
    print(f"Found {len(files)} files. Starting ingestion...")

    count = 0
    skipped = 0
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
            print(f"Error parsing {file_path}: {e}")
            continue

        if parsed_context is None:
            continue
            
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

        count += 1
        if count % 10 == 0:
            print(f"Processed {count} matches...")
            
        if count % COMMIT_BATCH_SIZE == 0:
            repo.commit()
            print(f"Checkpoint: Committed {count} matches.")
            
    # Final Commit
    repo.commit()
    repo.close()
    print("Ingestion Complete.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, help='Limit number of files to ingest')
    args = parser.parse_args()
    
    ingest_data(limit=args.limit)
