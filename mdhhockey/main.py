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
  _K, AZURE_AUTHORITY, AZURE_CLIENT_ID, AZURE_SCOPES, AZURE_TOKEN_CACHE, AZURE_USER, CACHE_DIR,
  CAPFRIENDLY_GRAPH_URL_ROOT, FANTRAX_EXPORT_FP, FANTRAX_EXPORT_URL, FANTRAX_LOGIN_COOKIE,
  INPUTS_DIR, NHL_API_BASE_URL, NHL_API_SEARCH_URL
)


curr_year = datetime.today().year
curr_month = datetime.today().month
if curr_month < 5:
  # Consider pre-May to be in-season still (e.g. May 2022 should start with 21-22, not 22-23)
  # TODO: We should probably just get this from somewhere in Fantrax. IE when we create the new league CapFriendly will automatically adjust
  curr_year = curr_year - 1
season_headers = [ f'{curr_year+i}-{curr_year+(i+1)}' for i in range(0, 8) ]


def _replace_special_chars(name):
  """
    Replaces special unicode characters with English alternatives (e.g. replacing
    the accented u with an English "u").
  """
  replacements = [('\u00fc', 'u'), ('\u00e8', 'e')]
  for r in replacements:
    name = name.replace(r[0], r[1])
  return name


def match_fantrax_player_to_nhl_player(row):
  """
    Attempt to match the Fantrax player (`row`) to 1 (and only 1) player object
    from the NHL API.
  """
  ft_name = row[_K.PLAYER].strip()
  ft_last_name = ' '.join(ft_name.split()[1:])  # handle last names that are multiple words
  ft_team = row[_K.TEAM].strip()

  search = requests.get(f"{NHL_API_SEARCH_URL}{ft_name}").json()
  if len(search) == 0:
    print(f"Search for {ft_name} returned empty list.")
    return "0"

  matches = []
  for player in search:
    nhl_name = _replace_special_chars(player[_K.NAME])
    nhl_last_name = ' '.join(nhl_name.split()[1:])
    nhl_team = player[_K.TEAM_ABBREV]
    if nhl_team == None:
      nhl_team = "(N/A)"

    # TODO: These are the names that this missed and why
    # Elias Pettersson -- Two Elias Pettersons who play for the same team
    # Calen Addison -- Recently traded from MIN to SJ
    # Matthew Savoie -- Is Matt Savoie in NHL.com
    # Will Smith -- Is William Smith in NHL.com
    # Daniil But -- Is Danil But in NHL.com
    # Casey DeSmith -- Incorrect team
    # Nikita Okhotyuk -- Is Nikita Okhotiuk in NHL.com
    # Ivan Prosvetov -- Team not updated from offseason trade
    # Anthony Beauvilier -- Team not updated from in-season trade
    # Vasili  Ponomarev -- Is Vasily Ponomarev on NHL.com

    confidence = 0.0

    # If the full name and the team matches, we're highly confident
    if nhl_name == ft_name and nhl_team == ft_team:
      confidence = 1.0

    # If the full name is right, we're pretty confident even if the team is wrong
    # NHL.com seems to take some time to update the backend after trades
    elif nhl_name == ft_name:
      confidence = 0.7

    # If last name and the team match, we're partially confident
    elif nhl_last_name == ft_last_name and nhl_team == ft_team:
      confidence = 0.5

    # If just the last name matches, we're least confident
    elif nhl_last_name == ft_last_name:
      confidence = 0.3

    matches.append((player, confidence))

  # If we only have one match, return it
  if len(matches) == 1:
    return matches[0][0]
  
  # Or if we have one match greater than the others
  matches = sorted(matches, key=lambda x: x[1], reverse=True)
  if len(matches) > 1 and matches[0][1] > matches[1][1]:
    return matches[0][0]

  # If we get here, we need help disambiguating
  print(f"Trouble finding matches for {ft_name}.")

  return None


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

  exp_year = season_headers[num_years].split("-")[0]
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


def merge_data(fantrax_data, fantrax_to_nhl):
  """
    For each player in `fantrax_data`, generate an output object containing
    supplemental data from the NHL players' data.
  """
  merged_data = []
  for row in fantrax_data:
    ft_id = row["ID"]
    if ft_id not in fantrax_to_nhl:
      continue

    output_obj = {
      **row,
      **{
        # Rename these below few keys
        _K.DOB: fantrax_to_nhl[ft_id]["DOB"],
        _K.POSITION: row['Position'].replace(',', '/'),
        _K.TEAM: row['Status'],
      }
    }
  
    # Set IR status, but not over the summer
    if output_obj['Roster Status'] == 'Inj Res' and (curr_month <= 4 or curr_month >= 10):
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
    elif output_obj[_K.CONTRACT] == 'Expire':
      num_years_to_set = 0 # Stream from last year, 0 years
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


def _load_ids_file():
  try:
    with open(f"{CACHE_DIR}/player_ids.json", "r") as f:
      try:
        return json.load(f)
      except:
        return {}
  except:
    print("Cache datafile not found")
    return {}


def _write_updated_ids_file(ids):
  try:
    with open(f"{CACHE_DIR}/player_ids.json", "w") as f:
      json.dump(ids, f)
  except:
    print("Cache datafile not found")


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
    result = app.acquire_token_interactive(scopes=AZURE_SCOPES)

  return result


def generate_data_for_capfriendly():
  # 1. get fantrax CSV
  download_fantrax_csv()
  fantrax_data = load_fantrax_data_from_file()

  # 2. Step through each Fantrax player and match them to their NHL.com ID, which is cached
  fantrax_id_to_nhl_id = _load_ids_file()
  for row in fantrax_data:
    fantrax_id = row[_K.ID]
    if fantrax_id not in fantrax_id_to_nhl_id:
      matched_player = match_fantrax_player_to_nhl_player(row)
      if matched_player:
        dob = requests.get(f"{NHL_API_BASE_URL}player/{matched_player[_K.PLAYER_ID]}/landing").json()["birthDate"]
        print(f"FOUND: {row[_K.PLAYER]} {matched_player[_K.NAME]} {dob}")
        fantrax_id_to_nhl_id[fantrax_id] = { "nhl_id" : matched_player[_K.PLAYER_ID], "name" : row[_K.PLAYER], "DOB" : dob }

  _write_updated_ids_file(fantrax_id_to_nhl_id)

  # 3. merge together
  merged_data = merge_data(fantrax_data, fantrax_id_to_nhl_id)
  if len(merged_data) == 0:
    print('Failed to get any data from Fantrax. Aborting.')

  headers = [_K.PLAYER, _K.IR, _K.TEAM, _K.DOB, _K.AGE, _K.POSITION, _K.CONTRACT] + season_headers
  data = list(list(player[k] for k in headers) for player in merged_data)

  # 4. Update the CapFriendly on OneDrive.
  result = _acquire_azure_token()
  if 'access_token' in result:
    # Get the range of the existing contracts to delete later
    resp = requests.get(
      f'{CAPFRIENDLY_GRAPH_URL_ROOT}/worksheets/All Contracts/tables/Players/range',
      headers={
        'Authorization': f'Bearer {result["access_token"]}'
      }
    ).json()
    addr_to_delete = resp['address']
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
