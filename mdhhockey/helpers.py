import json
import os
import requests
import traceback
from datetime import date, datetime

from mdhhockey.constants import (CACHE_DIR, NHL_API_BASE_URL, PLAYERS_CACHE_SUBDIR)


def calculate_age(dob):
  """ Calculate current age given a DOB in YYYY-mm-dd format"""
  today = date.today()
  dob = datetime.strptime(dob.replace('-', ' '), '%Y %m %d')
  return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _get_nhl(url):
  """
    Make API call to NHL API and return results as json. Utilizes a local cache and
    will avoid making duplicate API calls across application executions.
  """
  cache_key = url.replace(f'{NHL_API_BASE_URL}/',
                          '').replace('/', '_').replace('?', '_').replace('=', '_')
  if not os.path.exists(CACHE_DIR):
    os.mkdir(CACHE_DIR)  # init directory
  if 'people' in cache_key or 'draft_prospects' in cache_key:
    # Cache player responses in a nested dir to keep the main cache dir uncluttered
    cache_fp = f'{CACHE_DIR}/{PLAYERS_CACHE_SUBDIR}/{cache_key}'
    if not os.path.exists(f'{CACHE_DIR}/{PLAYERS_CACHE_SUBDIR}'):
      os.mkdir(f'{CACHE_DIR}/{PLAYERS_CACHE_SUBDIR}')  # init directory
  else:
    cache_fp = f'{CACHE_DIR}/{cache_key}'

  if os.path.exists(cache_fp):
    with open(cache_fp, 'r') as reader:
      return json.load(reader)
  else:
    try:
      response = requests.get(url).json()
      with open(cache_fp, 'w') as writer:
        writer.write(json.dumps(response, sort_keys=True, indent=2, default=str))
      return response
    except Exception:
      msg = traceback.format_exc()
      print(msg)


def _pid(player_id):
  return str(player_id)


def _replace_special_chars(name):
  """
    Replaces special unicode characters with English alternatives (e.g. replacing
    the accented u with an English "u").
  """
  replacements = [('\u00fc', 'u'), ('\u00e8', 'e')]
  for r in replacements:
    name = name.replace(r[0], r[1])
  return name
