# TODO
# - Add validation/retries for Excel operations
# - Split helpers.py into nhl_helpers, fantrax_helpers, and azure_helpers
# - Get Offseason/in-season IR from Fantrax settings
# - Better buyout/retention handling, and warnings for OTHER category

# Location of this app: https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps

import csv
import json
import os
import re
import requests
import time
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from bs4 import BeautifulSoup

from mdhhockey.helpers import (_replace_special_chars, _acquire_azure_token)
from mdhhockey.helpers import (
  _K, CACHE_DIR, CAPFRIENDLY_GRAPH_URL_ROOT, FANTRAX_EXPORT_FP, FANTRAX_LEAGUE_URL, FANTRAX_EXPORT_URL, FANTRAX_CAP_HITS_URL,
  FANTRAX_LOGIN_COOKIE, INPUTS_DIR, NHL_API_BASE_URL, NHL_API_SEARCH_URL, FANTRAX_TEAM_MAP
)

# Get basic league data from Fantrax that is used globally
payload = {"msgs": [{"method": "getFantasyLeagueInfo", "data": {}}]}
league_data = requests.post(FANTRAX_LEAGUE_URL, json=payload).json()
curr_year = int(league_data["responses"][0]["data"]["fantasySettings"]["season"]["displayYear"].split("-")[0])
season_headers = [ f'{curr_year+i}-{curr_year+(i+1)}' for i in range(0, 8) ]

is_offseason = (curr_year == datetime.today().year) and datetime.today().month < 9

#region Fantrax methods

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
    if output_obj['Roster Status'] == 'Inj Res' and not is_offseason:
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

def get_fantrax_to_nhl_ids_map(fantrax_data):
  # Load from cached IDs file
  try:
    with open(f"{CACHE_DIR}/player_ids.json", "r") as f:
      try:
        fantrax_id_to_nhl_id = json.load(f)
      except:
        print("Could not read cached json ids file")
        return {}
  except:
    print("Cache datafile not found")
    return {}

  for row in fantrax_data:
    fantrax_id = row[_K.ID]
    if fantrax_id not in fantrax_id_to_nhl_id:
      matched_player = match_fantrax_player_to_nhl_player(row)
      if matched_player:
        dob = requests.get(f"{NHL_API_BASE_URL}player/{matched_player[_K.PLAYER_ID]}/landing").json()["birthDate"]
        print(f"FOUND: {row[_K.PLAYER]} {matched_player[_K.NAME]} {dob}")
        fantrax_id_to_nhl_id[fantrax_id] = { "nhl_id" : matched_player[_K.PLAYER_ID], "name" : row[_K.PLAYER], "DOB" : dob }

  # Write the updated cache file
  try:
    with open(f"{CACHE_DIR}/player_ids.json", "w") as f:
      json.dump(fantrax_id_to_nhl_id, f)
  except:
    print("Cache datafile not found")

  return fantrax_id_to_nhl_id

def get_contract_data():
  # 1. get fantrax CSV
  try:
    download_fantrax_csv()
    fantrax_data = load_fantrax_data_from_file()
  except:
    print("Failed to download data from Fantrax. Aborting.")
    quit()

  # 2. Step through each Fantrax player and match them to their NHL.com ID, which is cached
  fantrax_id_to_nhl_id = get_fantrax_to_nhl_ids_map(fantrax_data)
  if fantrax_id_to_nhl_id == {}:
    print("Failed to get NHL IDs. Aborting.")
    quit()

  # 3. merge together
  merged_data = merge_data(fantrax_data, fantrax_id_to_nhl_id)
  if len(merged_data) == 0:
    print('Failed to get any data from Fantrax. Aborting.')
    quit()

  headers = [_K.PLAYER, _K.IR, _K.TEAM, _K.DOB, _K.AGE, _K.POSITION, _K.CONTRACT] + season_headers
  contract_data = list(list(player[k] for k in headers) for player in merged_data)

  return contract_data

def get_caphit_data():
  headers = { 'Cookie': FANTRAX_LOGIN_COOKIE}
  response_text = requests.get(FANTRAX_CAP_HITS_URL, headers=headers).text

  soup = BeautifulSoup(response_text, 'html.parser')
  caphit_data = soup.find('table', {'id': 'tblPenalties'})
  hit_data = [] # Output array
  for tr in caphit_data.find_all('tr')[1:]: # skip the header row
    tds = tr.find_all('td')

    team_id = FANTRAX_TEAM_MAP[tr['teamid']]
    num_years = 0 if tds[2].text == "" else int(tds[2].text) - curr_year + 1
    note = tds[5].text.lower()

    # Skip penalties that are just streamer drops
    if num_years == 0 and "penalty is 0%" in note:
      continue

    hit_val = int(tds[3].text.replace(",", ""))
    player = tds[4].find("a").text if tds[4].find("a") else tds[5].text
    if " drop " in note or " dropped " in note or " dropping " in note or " dump budget " in note or "buyout" in note:
      hit_type = "Buyout"
    else:
      hit_type = "Retention"

    row = [player, "", team_id, "", "", "", hit_type]
    for n in range(8):
      if n < num_years:
        row.append(hit_val)
      else:
        row.append("")
    hit_data.append(row)

  return hit_data

#endregion
#region azure/excel functions
def get_existing_range(table, token):
  # I have no clue why, but hitting this endpoint before the one I want to hit fixes my auth issues. I think it's a security bug, but /shrug
  resp = requests.get(f"https://graph.microsoft.com/v1.0/me/drive/items/56555516577EABF8!64168/content", headers={"Authorization": f"Bearer {token}"})

  resp = requests.get(f"{table}/range", headers={'Authorization': f'Bearer {token}'})
  print(resp.status_code)

  if resp.status_code == 401:
    print(resp.text)

  addr_range = resp.json()['address']
  addr_range = addr_range.replace("A1", "A2")
  addr_range = addr_range.split("!")[1]

  return addr_range

def add_data_to_table(table, data, token):
  print(f'Adding to {table.split("/")[-1]} table from CSV...')
  resp = requests.post(
    f"{table}/rows",
    json={'values': data, 'index': None},
    headers={'Authorization': f'Bearer {token}'}
  )

def delete_old_range(sheet, range, token):
  print(f'Deleting existing {sheet} table...')
  resp = requests.post(
    f"{CAPFRIENDLY_GRAPH_URL_ROOT}/worksheets/{sheet}/range(address='{range}')/delete",
    json={'shift': 'Up'},
    headers={'Authorization': f'Bearer {token}'}
  )

#endregion

def generate_data_for_capfriendly():
  contract_data = get_contract_data()
  caphit_data = get_caphit_data()

  result = _acquire_azure_token()
  if "access_token" not in result:
    print("Unable to get Azure access_token. Aboritng.")
    quit()

  token = result["access_token"]

  CONTRACTS_TABLE = f'{CAPFRIENDLY_GRAPH_URL_ROOT}/worksheets/All Contracts/tables/Players'
  HITS_TABLE = f'{CAPFRIENDLY_GRAPH_URL_ROOT}/worksheets/All Penalties/tables/Hits'

  # TODO: Ensure we validate after these operations and retry if necessary
  contracts_range = get_existing_range(CONTRACTS_TABLE, token) # Get the range of the existing contracts to delete later
  add_data_to_table(CONTRACTS_TABLE, contract_data, token) # Add the players from our new object
  delete_old_range("All Contracts", contracts_range, token) # Finally delete all the previous rows

  hits_range = get_existing_range(HITS_TABLE, token) # Get the range of the existing contracts to delete later
  add_data_to_table(HITS_TABLE, caphit_data, token) # Add the players from our new object
  delete_old_range("All Penalties", hits_range, token) # Finally delete all the previous rows
  # END TODO

if __name__ == '__main__':
  generate_data_for_capfriendly()
