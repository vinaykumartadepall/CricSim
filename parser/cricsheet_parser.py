import json
import os
from datetime import datetime
from db.entities import Player, Delivery, Tournament, Team, Venue, Match
from enums.constants import ExtraType

class ParsedMatchContext:
    match: Match
    tournament: Tournament
    teams: list[Team]
    venue: Venue
    players: list[Player]
    players_dict: object
    teams_list: list[str]
    def __init__(self, match, tournament, teams, venue, players, players_dict, teams_list):
        self.match = match
        self.tournament = tournament
        self.teams = teams  # dict: name -> Team
        self.venue = venue
        self.players = players # dict: name -> Player
        self.players_dict = players_dict # dict: team_name -> [player_name]
        self.teams_list = teams_list # list of team names

class CricsheetParser:
    @staticmethod
    def parse(file_path: str) -> ParsedMatchContext:
        original_id = os.path.basename(file_path)
        
        with open(file_path, 'r') as f:
            data = json.load(f)
            
        info = data.get('info', {})
        
        match_gender = info.get('gender')
        team_type = info.get('team_type')
        
        event = info.get('event', {})
        season = info.get('season')
        name = event.get('name')
        if not name:
             name = f"{team_type or match_gender} {info.get('match_type')} Tournament {season}" if season else "Unknown Tournament"

        tournament = (
            Tournament.builder()
            .with_name(name)
            .with_season(str(season) if season else None)
            .build()
        )
        
        teams_list = info.get('teams', [])
        saved_teams = {} 
        
        for t_name in teams_list:
            team = (
                Team.builder()
                .with_name(t_name)
                .with_type(team_type or "Unknown")
                .with_gender(match_gender or "Unknown")
                .build()
            )
            saved_teams[t_name] = team
            
        venue_name = info.get('venue') or "Unknown Venue"
        venue = (
            Venue.builder()
            .with_name(venue_name)
            .with_city(info.get('city'))
            .build()
        )

        players_dict = info.get('players', {})
        registry = info.get('registry', {}).get('people', {})
        
        saved_players = {} 
        
        for team_name, p_list in players_dict.items():
            current_team = saved_teams.get(team_name)
            if not current_team: 
                continue 
                
            for p_name in p_list:
                p_code = registry.get(p_name, "missing_code") 
                player = (
                    Player.builder()
                    .with_code(p_code)
                    .with_name(p_name)
                    .with_gender(match_gender)
                    .with_original_name(p_name)
                    .build()
                )
                saved_players[p_name] = player
                
        home_team = saved_teams.get(teams_list[0]) if len(teams_list) > 0 else None
        away_team = saved_teams.get(teams_list[1]) if len(teams_list) > 1 else None
        
        if not (home_team and away_team):
            return None
            
        match_format = info.get('match_type')
        if match_format == 'Test':
            innings_per_match = 4
            overs_per_innings = None
        else:
            innings_per_match = 2
            overs_per_innings = info.get('overs', 20)

        dates = info.get('dates', [])
        match_date = None
        if dates and isinstance(dates[0], str):
            try:
                match_date = datetime.strptime(dates[0], '%Y-%m-%d').date()
            except:
                pass

        base_match_name = f"{home_team.name} vs {away_team.name} - {tournament.name} {tournament.season}"
        match_number = event.get('match_number')
        match_name = f"Match {match_number}, {base_match_name}" if match_number else base_match_name

        outcome = info.get('outcome', {})
        winner_name = outcome.get('winner')
        winner_team = saved_teams.get(winner_name)
        
        match_result = outcome.get('result', 'normal' if winner_team else 'no result')
        win_type = None
        win_by = None
        if outcome.get('by', {}).get('runs') is not None:
             win_type = 'Runs'
             win_by = outcome.get('by', {}).get('runs')
        elif outcome.get('by', {}).get('wickets') is not None:
             win_type = 'Wickets'
             win_by = outcome.get('by', {}).get('wickets')

        toss = info.get('toss', {})
        toss_winner_name = toss.get('winner')
        toss_winner_team = saved_teams.get(toss_winner_name)
        
        pom_name = info.get('player_of_match', [None])[0]
        pom_player = saved_players.get(pom_name)
        
        match = (
            Match.builder()
            .with_original_match_id(original_id)
            .with_name(match_name)
            .with_tournament(tournament)
            .with_venue(venue)
            .with_home_team(home_team)
            .with_away_team(away_team)
            .with_date(match_date)
            .with_gender(match_gender)
            .with_match_format(match_format)
            .with_match_type(team_type)
            .with_balls_per_over(info.get('balls_per_over', 6))
            .with_overs_per_innings(overs_per_innings)
            .with_innings_per_match(innings_per_match)
            .with_result(match_result)
            .with_result_type(outcome.get('method'))
            .with_winner(winner_team)
            .with_win_type(win_type)
            .with_win_by(win_by)
            .with_player_of_match(pom_player)
            .with_toss_winner(toss_winner_team)
            .with_toss_decision(toss.get('decision'))
            .with_season(info.get('season'))
            .build()
        )

        innings = data.get('innings', [])
        for inning_idx, inning in enumerate(innings):
            batting_team_name = inning.get('team')
            batting_team = saved_teams.get(batting_team_name)
            bowling_team_name = next((t for t in teams_list if t != batting_team_name), None)
            bowling_team = saved_teams.get(bowling_team_name)
            
            if not (batting_team and bowling_team): continue
            
            for over_data in inning.get('overs', []):
                over_num = over_data.get('over')
                current_legal_ball = 0
                
                for delivery in over_data.get('deliveries', []):
                    batter = saved_players.get(delivery.get('batter'))
                    bowler = saved_players.get(delivery.get('bowler'))
                    non_striker = saved_players.get(delivery.get('non_striker'))
                    
                    if not (batter and bowler): 
                        continue

                    runs = delivery.get('runs', {})
                    extras = delivery.get('extras', {})
                    wickets = delivery.get('wickets', [])
                    
                    is_wide = 'wides' in extras
                    is_noball = 'noballs' in extras
                    if not (is_wide or is_noball):
                        current_legal_ball += 1
                        
                    ball_num = current_legal_ball + 1 if (is_wide or is_noball) else current_legal_ball
                    
                    outcome_type = 'Dot'
                    outcome_kind = None
                    outcome_player = None
                    
                    if wickets:
                        outcome_type = 'Wicket'
                        w = wickets[0]
                        outcome_kind = w.get('kind')
                        if w.get('fielders'):
                            outcome_player = w['fielders'][0].get('name')
                    elif runs.get('extras', 0) > 0:
                        outcome_type = 'Extras'
                    elif runs.get('batter', 0) > 0:
                        outcome_type = 'Runs'
                        
                    if not outcome_kind:
                         if is_wide: outcome_kind = ExtraType.WIDE.value
                         elif is_noball: outcome_kind = ExtraType.NOBALL.value
                         elif 'byes' in extras: outcome_kind = ExtraType.BYES.value
                         elif 'legbyes' in extras: outcome_kind = ExtraType.LEGBYES.value

                    d_obj = (
                        Delivery.builder()
                        .with_inning_number(inning_idx + 1)
                        .with_over_number(over_num)
                        .with_ball_number(ball_num)
                        .with_batter(batter)
                        .with_bowler(bowler)
                        .with_non_striker(non_striker)
                        .with_batting_team(batting_team)
                        .with_bowling_team(bowling_team)
                        .with_runs_batter(runs.get('batter', 0))
                        .with_runs_extras(runs.get('extras', 0))
                        .with_outcome_type(outcome_type)
                        .with_outcome_kind(outcome_kind)
                        .with_outcome_player(outcome_player)
                        .build()
                    )
                    match.add_delivery(d_obj)

        return ParsedMatchContext(
            match=match,
            tournament=tournament,
            teams=saved_teams,
            venue=venue,
            players=saved_players,
            players_dict=players_dict,
            teams_list=teams_list
        )
