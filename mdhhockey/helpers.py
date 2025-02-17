import atexit
import configparser
import msal
import os

# Config File (for vars that shouldn't be uploaded to GitHub)
config = configparser.ConfigParser()
config.read(['/home/jeremy/mdh-hockey/mdhhockey/config.cfg'])

# Root of the project to ensure absolute paths
PROJECT_ROOT = config['project']['root']

# Directories to cache GET requests in
CACHE_DIR = f'{PROJECT_ROOT}/response_cache'

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

# Map of fantrax page IDs to team abbreviations
FANTRAX_TEAM_MAP = {
  "51monkaolv9svu32": "0&Power",
  "ccseaq80lv9svu32": "BAR",
  "i9qis4mzlv9svu32": "BJS",
  "72to8ve3lv9svu32": "CCHT",
  "eetpluhdlv9svu32": "CTU",
  "ksumuhcwlv9svu32": "DWM",
  "6fq1ao06lv9svu32": "DZI",
  "y1onc1wklv9svu32": "GetRekt",
  "utrs5w3xlv9svu32": "CHZ",
  "htpjxvbelv9svu32": "BR0KE",
  "rccexq4mlv9svu32": "KINTO",
  "fj3etrbdlv9svu32": "KSP",
  "m4g260wilv9svu32": "HOGS",
  "59ymxbedlv9svu32": "SSKL",
  "wamzjyndlv9svu32": "EXP",
  "ta515279lv9svu32": "WTM",
  "5bafma0wlv9svu32": "WRINGS",
  "br0cbbq0lv9svu32": "2PRO"
}

# Directory to output the CSV into
OUTPUTS_DIR = f'{PROJECT_ROOT}/outputs'

# NHL API documentation: https://gitlab.com/dword4/nhlapi/-/blob/master/stats-api.md
# Some of the new nhle API documentation is best found in the Issues discussions
NHL_API_BASE_URL = 'https://api-web.nhle.com/v1/'
NHL_API_SEARCH_URL = 'https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=500&q='

# Helper methods that don't directly have to do with MDH
def _replace_special_chars(name):
  """
    Replaces special unicode characters with English alternatives (e.g. replacing
    the accented u with an English "u").
  """
  replacements = [('\u00fc', 'u'), ('\u00e8', 'e')]
  for r in replacements:
    name = name.replace(r[0], r[1])
  return name

# Azure/OneDrive variables and helpers
AZURE_CLIENT_ID = config['azure']['client_id']
AZURE_SCOPES = ["Files.ReadWrite.All", "User.Read"]
AZURE_AUTHORITY = 'https://login.microsoftonline.com/consumers'
AZURE_TOKEN_CACHE = f'{CACHE_DIR}/cache.bin'
AZURE_USER = config['azure']['user']
CAPFRIENDLY_GRAPH_URL_ROOT = "https://graph.microsoft.com/v1.0/drives/56555516577eabf8/items/56555516577EABF8!64168/workbook"

def _acquire_azure_token():
  cache = msal.SerializableTokenCache()
  if os.path.exists(AZURE_TOKEN_CACHE):
    cache.deserialize(open(AZURE_TOKEN_CACHE, "r").read())

  atexit.register(
    lambda: open(AZURE_TOKEN_CACHE, "w").write(cache.serialize())
    if cache.has_state_changed else None
  )

  app = msal.PublicClientApplication(
    AZURE_CLIENT_ID, authority=AZURE_AUTHORITY, token_cache=cache
  )

  result = None
  accounts = app.get_accounts(username=AZURE_USER)
  if accounts:
    result = app.acquire_token_silent(AZURE_SCOPES, account=accounts[0])

  if not result:
    print("Could not renew token, need interactive acquisition.")
    result = app.acquire_token_interactive(scopes=AZURE_SCOPES)

  return result

# Helper class
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
