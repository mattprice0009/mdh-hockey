import configparser

# Config File (for vars that shouldn't be uploaded to GitHub)
config = configparser.ConfigParser()
config.read(['/home/jeremy/mdh-hockey/mdhhockey/config.cfg'])

# Root of the project to ensure absolute paths
PROJECT_ROOT = config['project']['root']

# Directories to cache GET requests in
CACHE_DIR = f'{PROJECT_ROOT}/response_cache'

# Azure/OneDrive variables
AZURE_CLIENT_ID = config['azure']['client_id']
AZURE_SCOPES = ['https://graph.microsoft.com/.default']
AZURE_AUTHORITY = 'https://login.microsoftonline.com/consumers'
AZURE_TOKEN_CACHE = f'{CACHE_DIR}/cache.bin'
AZURE_USER = config['azure']['user']
CAPFRIENDLY_GRAPH_URL_ROOT = "https://graph.microsoft.com/v1.0/drives/56555516577eabf8/items/56555516577EABF8!64168/workbook"

# Directory to store the Fantrax input CSV
INPUTS_DIR = f'{PROJECT_ROOT}/inputs'
FANTRAX_EXPORT_FP = f'{INPUTS_DIR}/fantrax_export_latest.csv'

# Fantrax Variables
# This is the request sent when clicking the "download as CSV" button on the Fantrax Players page
# We'll have to update the leagueId every year
FANTRAX_LEAGUE_ID = 'zc9e2jnblv9svu2t'
FANTRAX_LEAGUE_URL = f"https://www.fantrax.com/fxpa/req?leagueId={FANTRAX_LEAGUE_ID}"
FANTRAX_EXPORT_URL = f'https://www.fantrax.com/fxpa/downloadPlayerStats?leagueId={FANTRAX_LEAGUE_ID}&pageNumber=1&view=STATS&positionOrGroup=ALL&sortType=SALARY&statusOrTeamFilter=ALL_TAKEN'
FANTRAX_CAP_HITS_URL = f'https://www.fantrax.com/newui/fantasy/capHitPenaltyAdmin.go?leagueId={FANTRAX_LEAGUE_ID}'
FANTRAX_LOGIN_COOKIE = config['fantrax']['cookie']

# Directory to output the CSV into
OUTPUTS_DIR = f'{PROJECT_ROOT}/outputs'

# NHL API documentation: https://gitlab.com/dword4/nhlapi/-/blob/master/stats-api.md
# Some of the new nhle API documentation is best found in the Issues discussions
NHL_API_BASE_URL = 'https://api-web.nhle.com/v1/'
NHL_API_SEARCH_URL = 'https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=500&q='

class _K:
  BDAY = 'birthDate'
  CURR_AGE = 'currentAge'
  CURR_TEAM = 'currentTeam'
  NAME = 'name'
  NAME_FULL = 'fullName'
  NAME_LAST = 'lastName'
  PLAYER_ID = 'playerId'
  TEAM_ABBREV = 'teamAbbrev'

  AAV = 'Salary'
  AGE = 'Age'
  CONTRACT = 'Contract'
  DOB = 'DOB'
  ID = 'ID'
  IR = 'IR?'
  PLAYER = 'Player'
  POSITION = 'Pos'
  TEAM = 'Team'
