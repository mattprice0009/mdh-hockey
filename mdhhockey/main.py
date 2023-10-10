import atexit
import csv
import json
import os
import re
from datetime import date, datetime

import msal
import requests
from dateutil.relativedelta import relativedelta

from mdhhockey.constants import (
  _K, AZURE_AUTHORITY, AZURE_CLIENT_ID, AZURE_SCOPES, AZURE_TOKEN_CACHE, AZURE_USER,
  CAPFRIENDLY_GRAPH_URL_ROOT, FANTRAX_EXPORT_FP, FANTRAX_EXPORT_URL, FANTRAX_LOGIN_COOKIE,
  INPUTS_DIR, MISSING_PLAYERS, NHL_API_BASE_URL, NUM_YEARS_DATA_TO_FETCH, OUTPUTS_DIR
)
from mdhhockey.helpers import (_get_nhl, _pid, _replace_special_chars, calculate_age)


curr_year = datetime.today().year
curr_month = datetime.today().year
if curr_month < 7:
  # Consider pre-July to be in-season still (e.g. May 2022 should start with 21-22, not 22-23)
  # TODO: We should probably just get this from somewhere in Fantrax. IE when we create the new league CapFriendly will automatically adjust
  curr_year = curr_year - 1
season_headers = [ f'{curr_year+i}-{curr_year+(i+1)}' for i in range(0, 8) ]


def _get_all_team_players(team_id):
  """
    Get all roster players over the past N years, for a given team.
  """
  all_player_ids = set()

  # Get all roster player IDs, for all players on roster over last n years
  for year in [curr_year - i for i in range(NUM_YEARS_DATA_TO_FETCH)]:
    season_str = f'{year-1}{year}'
    response = _get_nhl(f'{NHL_API_BASE_URL}/teams/{team_id}/roster?season={season_str}')
    if response.get('message', '') == 'Object not found':
      # Expansion team that didn't exist during this season
      break
    all_player_ids.update([p['person']['id'] for p in response['roster']])

  # For each player ID, get their detailed data
  all_player_objs = []
  for player_id in all_player_ids:
    player_obj = _get_nhl(f'{NHL_API_BASE_URL}/people/{player_id}')['people'][0]
    all_player_objs.append(player_obj)
  return all_player_objs


def _get_drafted_prospects():
  """
    Get players data directly from draft results, by draft year.
  """
  all_player_objs = []
  for year in [curr_year - i for i in range(NUM_YEARS_DATA_TO_FETCH)]:
    draft_data = _get_nhl(f'{NHL_API_BASE_URL}/draft/{year}')['drafts'][0]['rounds']
    for round in draft_data:
      for p in round['picks']:
        # Retrieve the Prospect object
        if p['prospect'][_K.NAME_FULL] == 'Void':
          continue  # This is how the NHL API seems to label "bad data"

        prospect_id = p['prospect']['id']
        prospect = _get_nhl(f'{NHL_API_BASE_URL}/draft/prospects/{prospect_id}'
                            )['prospects'][0]
        if 'nhlPlayerId' not in prospect:
          # Player isn't signed with NHL team yet
          prospect['id'] = 'prospect' + _pid(prospect['id'])
          all_player_objs.append({ **prospect, **{_K.CURR_TEAM: p['team']} })
        else:
          # Retrieve the Player object, given the nhlPlayerId
          prospect_player_id = prospect['nhlPlayerId']
          player_obj = _get_nhl(f'{NHL_API_BASE_URL}/people/{prospect_player_id}'
                                )['people'][0]
          player_obj['prospect_data'] = prospect
          all_player_objs.append(player_obj)
  return all_player_objs


def match_fantrax_player_to_nhl_player(row, nhl_players_dict):
  """
    Attempt to match the Fantrax player (`row`) to 1 (and only 1) player object
    from the NHL API.
  """
  name = row[_K.PLAYER].strip()
  last_name = ' '.join(name.split()[1:])  # handle last names that are multiple words
  curr_age = int(row[_K.AGE])
  team = row[_K.TEAM].strip()

  # Apply arbitrary matching logic that will match (in order of pref):
  # 1. Full name + age + team
  # 2. Full name + age
  # 3. Full name + team
  # 4. Last name + age + team
  # 5. Last name + age
  matches = []
  for item in nhl_players_dict.values():
    item_matches = []
    if item[_K.NAME_FULL].strip() == name:
      item_matches.append({ **item, **{ '_score': 1.0} })
    elif _K.NAME_LAST in item and item[_K.NAME_LAST].strip() == last_name:
      item_matches.append({ **item, **{ '_score': 0.4} })
    for m in item_matches:
      if m.get(_K.CURR_AGE, 0) == curr_age:
        m['_score'] += 0.3
      if m.get('team_abbrev', '') == team:
        m['_score'] += 0.2
      if m['_score'] >= 0.7:
        matches.append(m)

  matches = sorted(matches, key=lambda x: x['_score'], reverse=True)
  if len(matches) == 1:
    return matches[0]
  if len(matches) > 1 and matches[0]['_score'] > matches[1]['_score']:
    return matches[0]

  if name in MISSING_PLAYERS:
    if name == "Daniel Vladar":
      return nhl_players_dict["8478435"]
    elif name == "Brandon Bussi":
      bussi = {_K.BDAY: "1998-06-25"}
      return bussi
    elif name == "Ryan McAllister":
      mcallister = {_K.BDAY: "2001-12-19"}
      return mcallister
    elif name == 'Georgi Merkulov':
      return {_K.BDAY: '2000-10-10'}

    print(f'Missing player override for {name} not found.')

  print('NO SINGLE MATCHES!!')
  print(json.dumps(matches, sort_keys=True, indent=2, default=str))
  print(json.dumps(row, sort_keys=True, indent=2, default=str))
  print(f'Continuing without {name}')


def get_nhl_players_data():
  """
    Get a giant object containing player data from the NHL API
  """
  teams_data = _get_nhl(f'{NHL_API_BASE_URL}/teams')['teams']
  team_abbrevs = {t['name']: t['abbreviation'] for t in teams_data}
  players_map = {}

  # Get roster players for each team
  for team_obj in teams_data:
    team_players = _get_all_team_players(team_obj['id'])
    for player_obj in team_players:
      players_map[_pid(player_obj['id'])] = player_obj

  # Get all draftees
  prospect_players = _get_drafted_prospects()
  for player_obj in prospect_players:
    players_map[_pid(player_obj['id'])] = player_obj

  for k, player_obj in players_map.items():
    if _K.CURR_TEAM in player_obj:
      player_obj['team_abbrev'] = team_abbrevs[player_obj[_K.CURR_TEAM]['name']]
    if _K.CURR_AGE not in player_obj and _K.BDAY in player_obj:
      player_obj[_K.CURR_AGE] = calculate_age(player_obj[_K.BDAY])
    # Replace special characters (unicode characters)
    player_obj[_K.NAME_FULL] = _replace_special_chars(player_obj[_K.NAME_FULL])
    player_obj[_K.NAME_LAST] = _replace_special_chars(player_obj[_K.NAME_LAST])
  return players_map


def download_fantrax_csv():
  headers = { 'Cookie': FANTRAX_LOGIN_COOKIE}
  player_data = requests.get(FANTRAX_EXPORT_URL, headers=headers).text

  if not os.path.exists(INPUTS_DIR):
    os.mkdir(INPUTS_DIR)  # init directory
  with open(FANTRAX_EXPORT_FP, 'w') as csvfile:
    csvfile.write(player_data)


def load_fantrax_data_from_file():
  player_objs = []
  with open(FANTRAX_EXPORT_FP, 'r') as csvfile:
    csvreader = csv.DictReader(csvfile, delimiter=',')
    for row in csvreader:
      row[_K.AAV] = int(re.sub(r'\D', '', row[_K.AAV]))  # remove commas rom AAV
      player_objs.append(row)
  return player_objs


def calculate_expiry_status(output_obj, num_years):
  dob = date.fromisoformat(output_obj[_K.DOB])

  exp_year = season_headers[num_years].split("-")[1]
  exp_date = date.fromisoformat(
    f"{exp_year}-09-15"
  )  # Season rollover date. Also Defined in the Summary!Q10

  difference_in_years = relativedelta(exp_date, dob).years

  extensions = [line.rstrip() for line in open(f"{INPUTS_DIR}/extensions.csv", "r")]

  if "ELC" in output_obj[_K.CONTRACT]:
    return f"RFA ({difference_in_years}*)"
  elif output_obj[_K.PLAYER] not in extensions and (
    (difference_in_years < 26 and output_obj[_K.POSITION] != "G") or
    (difference_in_years < 28 and output_obj[_K.POSITION] == "G")):
    return f"RFA ({difference_in_years})"
  else:
    return f"UFA ({difference_in_years})"


def merge_data(fantrax_data, nhl_players_dict):
  """
    For each player in `fantrax_data`, generate an output object containing
    supplemental data from the NHL players' data.
  """
  merged_data = []
  for row in fantrax_data:
    matched_nhl_player = match_fantrax_player_to_nhl_player(row, nhl_players_dict)
    if not matched_nhl_player:
      continue
    output_obj = {
      **row,
      **{
        # Rename these below few keys
        _K.DOB: matched_nhl_player[_K.BDAY],
        _K.POSITION: row['Position'].replace(',', '/'),
        _K.TEAM: row['Status'],
      }
    }
    # Set IR status
    if output_obj['Roster Status'] == 'Inj Res':
      output_obj[_K.IR] = 'Y'
    else:
      output_obj[_K.IR] = ''

    # Copy salary values into each separate year.
    #   Ex: If current season is 23-24 and contract is "07/2026", copy AAV value
    #   into "2023-2024", "2024-2025", and "2025-2026" keys. Set other future,
    #   non-contract years to empty strings.
    num_years_to_set = 0
    if 'ELC' in output_obj[_K.CONTRACT]:
      num_years_to_set = 3  # ELC is 3 years
    elif output_obj[_K.CONTRACT] == 'Stream':
      num_years_to_set = 1  # Stream is 1 year
    else:
      output_obj[_K.CONTRACT
                 ] = f"'0{output_obj[_K.CONTRACT]}"  # Escape for Excel formatting
      # Calculate number of years based off standard contract label (e.g. "07/2027")
      expire_year = output_obj[_K.CONTRACT].split('/')[1]
      for i, header in enumerate(season_headers):
        if header.split('-')[1] == expire_year:
          num_years_to_set = i + 1
    for i, header in enumerate(season_headers):
      if i < num_years_to_set:
        output_obj[header] = output_obj[_K.AAV]
      elif i == num_years_to_set:
        output_obj[header] = calculate_expiry_status(output_obj, num_years_to_set)
      else:
        output_obj[header] = ''
    merged_data.append(output_obj)
  return merged_data


def generate_data_for_capfriendly():

  # 1. get fantrax CSV
  download_fantrax_csv()
  fantrax_data = load_fantrax_data_from_file()

  # 2. get players/prospects data from NHL api
  nhl_players_dict = get_nhl_players_data()

  # 3. merge together
  merged_data = merge_data(fantrax_data, nhl_players_dict)

  # 4. write to csv export
  if not os.path.exists(OUTPUTS_DIR):
    os.mkdir(OUTPUTS_DIR)  # init directory
  with open(f'{OUTPUTS_DIR}/processed_data_for_cf.csv', 'w') as csvfile:
    headers = [
      _K.PLAYER, _K.IR, _K.TEAM, _K.DOB, _K.AGE, _K.POSITION, _K.CONTRACT
    ] + season_headers
    writer = csv.DictWriter(csvfile, fieldnames=headers, extrasaction='ignore')
    writer.writeheader()
    for player_obj in merged_data:
      writer.writerow(player_obj)

  # 5. Test access to the CapFriendly on OneDrive.
  # TODO: Put the output in here instead of the output CSV
  # TODO: This could stand to be cleaned up a bit too.
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
    result = app.acquire_token_interactive(scopes=AZURE_SCOPES)

  if 'access_token' in result:
    # Read the data from our processed CSV into a payload for the POST
    data = []
    with open(f'{OUTPUTS_DIR}/processed_data_for_cf.csv', 'r') as csvfile:
      for line in csvfile.readlines()[1:]:  # skip headers
        line = line.replace('\n', '').split(",")
        data.append(line)

    # TODO: Add some sanity checks here and bail if necessary
    if len(data) == 0:
      print('Failed to get any data from Fantrax. Aborting.')

    # Get the range of the existing contracts to delete later
    resp = requests.get(
      f'{CAPFRIENDLY_GRAPH_URL_ROOT}/worksheets/All Contracts/tables/Players/range',
      headers={
        'Authorization': f'Bearer {result["access_token"]}'
      }
    ).json()
    addr_to_delete = resp["address"]
    addr_to_delete = addr_to_delete.replace("A1", "A2")
    addr_to_delete = addr_to_delete.split("!")[1]

    # TODO: Check to ensure we get a response and a valid address

    # Then add the players from our new object
    print('Adding to Players table from CSV...')
    resp = requests.post(
      f'{CAPFRIENDLY_GRAPH_URL_ROOT}/worksheets/All Contracts/tables/Players/rows',
      json={
        'values': data,
        'index': None
      },
      headers={ 'Authorization': f'Bearer {result["access_token"]}'}
    )

    # TODO: Add a check to ensure this worked and bail or try again if not

    # Finally delete all the previous rows
    print('Deleting existing Players table...')
    resp = requests.post(
      f"{CAPFRIENDLY_GRAPH_URL_ROOT}/worksheets/All Contracts/range(address='{addr_to_delete}')/delete",
      json={ 'shift': 'Up'},
      headers={ 'Authorization': f'Bearer {result["access_token"]}'}
    )

    # TODO: Add a check to ensure this was successful and try again if not


if __name__ == '__main__':
  generate_data_for_capfriendly()
