from db.database import get_db_connection
from db.entities import Player, Team, Venue, Tournament, Match, Delivery
import psycopg2.extras
import logging

class CricketRepository:
    def __init__(self):
        self.conn = get_db_connection(autocommit=False) # Manage transactions manually for batches
        self.cur = self.conn.cursor()
        
        # In-memory caches to reduce DB round-trips
        self._players_cache = {} # code -> id
        self._teams_cache = {}   # name -> id
        self._venues_cache = {}  # name -> id
        self._tournaments_cache = {} # (name, season) -> id
        
    def commit(self):
        self.conn.commit()
        
    def rollback(self):
        self.conn.rollback()
        
    def close(self):
        self.cur.close()
        self.conn.close()

    def exists_match(self, original_id):
        self.cur.execute("SELECT 1 FROM history.matches WHERE original_match_id = %s", (original_id,))
        return self.cur.fetchone() is not None

    def get_or_create_player(self, player: Player) -> Player:
        if player.code in self._players_cache:
            player.id = self._players_cache[player.code]
            return player
            
        self.cur.execute("SELECT player_id FROM history.players WHERE code = %s", (player.code,))
        res = self.cur.fetchone()
        if res:
            player.id = res[0]
            self._players_cache[player.code] = player.id
            return player
            
        self.cur.execute(
            "INSERT INTO history.players (code, name, original_name, gender) VALUES (%s, %s, %s, %s) RETURNING player_id",
            (player.code, player.name, player.original_name, player.gender)
        )
        player.id = self.cur.fetchone()[0]
        self._players_cache[player.code] = player.id
        return player

    def get_or_create_team(self, team: Team) -> Team:
        if team.name in self._teams_cache:
            team.id = self._teams_cache[team.name]
            return team

        self.cur.execute("SELECT team_id FROM history.teams WHERE name = %s", (team.name,))
        res = self.cur.fetchone()
        if res:
            team.id = res[0]
            self._teams_cache[team.name] = team.id
            return team
            
        self.cur.execute(
            "INSERT INTO history.teams (name, type, gender) VALUES (%s, %s, %s) RETURNING team_id",
            (team.name, team.type, team.gender)
        )
        team.id = self.cur.fetchone()[0]
        self._teams_cache[team.name] = team.id
        return team

    def get_or_create_venue(self, venue: Venue) -> Venue:
        if venue.name in self._venues_cache:
            venue.id = self._venues_cache[venue.name]
            return venue

        self.cur.execute("SELECT venue_id FROM history.venues WHERE name = %s", (venue.name,))
        res = self.cur.fetchone()
        if res:
            venue.id = res[0]
            self._venues_cache[venue.name] = venue.id
            return venue
            
        self.cur.execute(
            "INSERT INTO history.venues (name, city) VALUES (%s, %s) RETURNING venue_id",
            (venue.name, venue.city)
        )
        venue.id = self.cur.fetchone()[0]
        self._venues_cache[venue.name] = venue.id
        return venue

    def get_or_create_tournament(self, tournament: Tournament) -> Tournament:
        key = (tournament.name, tournament.season)
        if key in self._tournaments_cache:
            tournament.id = self._tournaments_cache[key]
            return tournament
            
        self.cur.execute(
            "SELECT tournament_id FROM history.tournaments WHERE tournament_name = %s AND season = %s",
            (tournament.name, tournament.season)
        )
        res = self.cur.fetchone()
        if res:
            tournament.id = res[0]
            self._tournaments_cache[key] = tournament.id
            return tournament
            
        self.cur.execute(
            "INSERT INTO history.tournaments (tournament_name, season) VALUES (%s, %s) RETURNING tournament_id",
            (tournament.name, tournament.season)
        )
        tournament.id = self.cur.fetchone()[0]
        self._tournaments_cache[key] = tournament.id
        return tournament

    def add_tournament_team(self, tournament: Tournament, team: Team):
        # Junction table insert (ignore duplicates)
        self.cur.execute("""
            INSERT INTO history.tournament_teams (tournament_id, team_id) 
            VALUES (%s, %s) 
            ON CONFLICT DO NOTHING
        """, (tournament.id, team.id))

    def add_match_player(self, match: Match, team: Team, player: Player):
        self.cur.execute("""
            INSERT INTO history.match_players (match_id, team_id, player_id) 
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
        """, (match.id, team.id, player.id))

    def save_match(self, match: Match):
        # Assumes dependencies (Tournament, Venue, Teams, Players/Winner/TossWinner) already have IDs set
        # matches table
        self.cur.execute("""
            INSERT INTO history.matches 
            (original_match_id, name, venue_id, home_team_id, away_team_id, 
             tournament_id, gender, match_format, match_type, 
             balls_per_over, overs_per_innings, innings_per_match,
             result, result_type, winner_id, win_type, win_by, 
             player_of_match_id, toss_winner_id, toss_decision, season, date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING match_id
        """, (
            match.original_match_id, match.name, match.venue.id, match.home_team.id, match.away_team.id,
            match.tournament.id, match.gender, match.match_format, match.match_type,
            match.balls_per_over, match.overs_per_innings, match.innings_per_match,
            match.result, match.result_type, match.winner.id if match.winner else None,
            match.win_type, match.win_by, 
            match.player_of_match.id if match.player_of_match else None,
            match.toss_winner.id if match.toss_winner else None, match.toss_decision,
            match.season, match.date
        ))
        match.id = self.cur.fetchone()[0]
        
        # Save deliveries
        if match.deliveries:
            delivery_tuples = []
            for d in match.deliveries:
                delivery_tuples.append((
                    match.id, d.inning_number, d.over_number, d.ball_number,
                    d.batter.id, d.bowler.id, d.non_striker.id,
                    d.batting_team.id, d.bowling_team.id,
                    d.runs_batter, d.runs_extras, d.outcome_type, d.outcome_kind, d.outcome_player
                ))
            
            psycopg2.extras.execute_batch(self.cur, """
                INSERT INTO history.deliveries (
                    match_id, inning_number, over_number, ball_number,
                    batter_id, bowler_id, non_striker_id,
                    batting_team_id, bowling_team_id,
                    runs_batter, runs_extras, outcome_type, outcome_kind, outcome_player_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, delivery_tuples)

    def save_full_match_context(self, match: Match):
        """
        Orchestrates saving the match and its junction data (Match Players).
        Note: Teams/TournamentTeams handled during ingestion loop usually, but matches players need match_id.
        """
        self.save_match(match)
        
        # We need to map which player belongs to which team for MATCH_PLAYERS
        # Only simple way is if we stored team info on the Player object or passed it in.
        # But `match.players` is a flat list. 
        # For this implementation, we might skip saving MATCH_PLAYERS here if we don't know the team easily.
        # User requirement: "list of player in a match". 
        # I will update MatchBuilder to store players as a dict {Team: [Players]} or similar to handle this.
        pass
