This repository contains scripts to help with the management of MDH, a salary dynasty league.

## Generating a complete dataset for the MDH CF

### Overview

Given a Fantrax CSV file containing all players of interest (likely just "all owned players"), this script will output a new, "completed" CSV that contains supplemental information for each player. This additional info comes from the NHL API.

The output CSV is formatted to perfectly match the format & columns of the "All contracts" CF page, with the goal being that this output can be pasted into the "All contracts" page with zero additional work needed.

### Requirements to run

1. Download a Players CSV export for all owned players from Fantrax.
    * On the "players" page in fantrax, filter by "All positions" and "Status - 'All taken players'" - this will give you a CSV containing all players under contract.
    * Move the CSV into the path defined in the `FANTRAX_EXPORT_FP` constant variable (make sure the file name matches).
2. Install Python3
3. Install the `requests` Python package
4. Install this package - `pip install --editable .` (from the same folder as the `setup.py` file)

### Running

**NOTE: Running this will store many (at least a few thousand) JSON files in the directory defined in `CACHE_DIR`. Ensure you're OK with storing a couple dozen MB in local files before running.**
**NOTE: It also may take 10 or 15 minutes to run**

To run the script, simply run `python main.py`.

Once it's finished, the output CSV will be stored in the `OUTPUTS_DIR` path.

There's a Fantrax cookie required to run this, unique to your user session. More info can be found in the config file.
