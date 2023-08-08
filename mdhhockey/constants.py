# Directories to cache GET requests in
CACHE_DIR = 'response_cache'
PLAYERS_CACHE_SUBDIR = 'players'

# Directory to output the CSV into
OUTPUTS_DIR = 'outputs'

# NHL API documentation: https://gitlab.com/dword4/nhlapi/-/blob/master/stats-api.md
NHL_API_BASE_URL = 'https://statsapi.web.nhl.com/api/v1'
FANTRAX_EXPORT_FP = 'inputs/fantrax_export_latest.csv'

# Number of years to retrieve draft results + team rosters history for.
NUM_YEARS_DATA_TO_FETCH = 10

# These players are not on ANY draft results or teams page. I believe this
# is because they are A) undrafted, B) haven't played an NHL game, and C)
# rostered in Fantrax.
# TODO: Hardcode their information into here instead of skipping.
MISSING_PLAYERS = set([ 'Brandon Bussi', 'Ryan McAllister'])


class _K:
  BDAY = 'birthDate'
  CURR_AGE = 'currentAge'
  CURR_TEAM = 'currentTeam'
  NAME_FULL = 'fullName'
  NAME_LAST = 'lastName'

  AAV = 'Salary'
  AGE = 'Age'
  CONTRACT = 'Contract'
  DOB = 'DOB'
  IR = 'IR?'
  PLAYER = 'Player'
  POSITION = 'Pos'
  TEAM = 'Team'
