This contains / will contain scripts to help commissioners with automation / management of the MDH salary league.

## Generating a complete dataset for the MDH CF

### Overview

Given a Fantrax CSV file containing all players of interest (likely just "all owned players"), this script will supplement output a new, "completed" CSV that contains supplemental information for each player. This supplemental info comes from the NHL API.

The output CSV is formatted to perfectly match the "All contracts" sheet of the MDH CF, with the goal being that it can be pasted into it with zero additional work needed.

### Requirements to run

1. Download a Players CSV export for all owned players from Fantrax.
  a. On the "players" page in fantrax, filter by "All positions" and "Status - 'All taken players'"
  b. Move / Rename the CSV into the path defined in `FANTRAX_EXPORT_FP` constant variable
2. Python3 installed
3. `requests` Python package installed
4. Install this package - `pip install --editable .` from same dir as this `setup.py` file.

### Running

**NOTE: Running this will by default store many (at least a few thousand) JSON files in the directory defined in `CACHE_DIR`. Ensure you're OK with storing a couple dozen MB in local files before running.**

To run the script, simply run `python main.py`.

Once it's finished, the output CSV will be stored in `OUTPUTS_DIR`.

