import configparser

# Config File (for vars that shouldn't be uploaded to GitHub)
config = configparser.ConfigParser()
config.read(['config.cfg'])

# Azure variables
AZURE_CLIENT_ID = config['azure']['client_id']
AZURE_SCOPE = ['https://graph.microsoft.com/.default']

# Directories to cache GET requests in
PROJECT_ROOT = config['project']['root']
CACHE_DIR = f'{PROJECT_ROOT}/response_cache'
PLAYERS_CACHE_SUBDIR = 'players'
INPUTS_DIR = f'{PROJECT_ROOT}/inputs'
FANTRAX_EXPORT_FP = f'{INPUTS_DIR}/fantrax_export_latest.csv'

# Fantrax Variables
# This is the request sent when clicking the "download as CSV" button on the Fantrax Players page
# We'll have to update the leagueId every year
FANTRAX_LEAGUE_ID = 'y4o6od4vlgo113rd'
FANTRAX_EXPORT_URL = f'https://www.fantrax.com/fxpa/downloadPlayerStats?leagueId={FANTRAX_LEAGUE_ID}&pageNumber=1&view=STATS&positionOrGroup=ALL&seasonOrProjection=PROJECTION_0_31h_SEASON&timeframeTypeCode=YEAR_TO_DATE&transactionPeriod=1&miscDisplayType=1&sortType=SCORE&maxResultsPerPage=100&statusOrTeamFilter=ALL_TAKEN&scoringCategoryType=5&timeStartType=PERIOD_ONLY&schedulePageAdj=0&searchName=&datePlaying=ALL&startDate=2023-10-10&endDate=2023-08-12&teamId=0abd3q87lgo113s6&'
FANTRAX_LOGIN_COOKIE = config['fantrax']['cookie']

# Directory to output the CSV into
OUTPUTS_DIR = f'{PROJECT_ROOT}/outputs'

# NHL API documentation: https://gitlab.com/dword4/nhlapi/-/blob/master/stats-api.md
NHL_API_BASE_URL = 'https://statsapi.web.nhl.com/api/v1'

# Number of years to retrieve draft results + team rosters history for.
NUM_YEARS_DATA_TO_FETCH = 10

# These players are not on ANY draft results or teams page. I believe this
# is because they are A) undrafted, B) haven't played an NHL game, and C)
# rostered in Fantrax.
# TODO: Hardcode their information into here instead of skipping.
MISSING_PLAYERS = set(['Brandon Bussi', 'Ryan McAllister'])

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
