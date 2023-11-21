import json
import os
import traceback
from datetime import date, datetime

import requests

from mdhhockey.constants import (CACHE_DIR, NHL_API_BASE_URL, PLAYERS_CACHE_SUBDIR)


def calculate_age(dob):
  """ Calculate current age given a DOB in YYYY-mm-dd format"""
  today = date.today()
  dob = datetime.strptime(dob.replace('-', ' '), '%Y %m %d')
  return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _replace_special_chars(name):
  """
    Replaces special unicode characters with English alternatives (e.g. replacing
    the accented u with an English "u").
  """
  replacements = [('\u00fc', 'u'), ('\u00e8', 'e')]
  for r in replacements:
    name = name.replace(r[0], r[1])
  return name
