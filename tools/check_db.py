from db.stats_repository import StatsRepository
import sys

repo = StatsRepository()
print("Batter dist ODI:", len(repo.get_batters_distribution([], "ODI", "male")))
print("Innings dist ODI:", len(repo.get_innings_distribution("ODI", "male")))
