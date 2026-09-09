# football-data.org competition codes for the leagues we support.
LEAGUES = {
    "PD": {"name": "La Liga", "country": "Spain"},
    "PL": {"name": "Premier League", "country": "England"},
    "SA": {"name": "Serie A", "country": "Italy"},
    "BL1": {"name": "Bundesliga", "country": "Germany"},
    "FL1": {"name": "Ligue 1", "country": "France"},
}

DEFAULT_LEAGUE = "PD"


def get_league(code):
    return LEAGUES.get(code)
