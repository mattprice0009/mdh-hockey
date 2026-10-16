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

To run the script, simply run `python CapFriendly/main.py`.

Once it's finished, the output CSV will be stored in the `OUTPUTS_DIR` path.

There's a Fantrax cookie required to run this, unique to your user session. More info can be found in the config file.

## Checking today's lineups

`LineupCheck/check_lineups.py` reports any fantasy team that could fit more healthy,
non-minor-league players whose NHL team plays today. It uses the current
Fantrax lineup day, each player's Fantrax position eligibility, and the
league's actual active slots. Full lineups are not flagged merely because an
additional bench player is playing. Players in fantasy minors or injured
reserve are only counted when they can be activated without dropping another
player; legal moves of another player to minors or injured reserve are shown in
the suggested correction. Goalies only qualify when Fantrax marks them as the
confirmed starter; an expected or unconfirmed goalie is ignored.

The cron job polls the NHL schedule every five minutes and posts the lineup
check during the hour before the first game. Polls outside that window exit
before fetching team rosters. The check runs once per local date, after a
successful post. Use `--force` to run it manually outside the schedule window.

Run it from the repository root with the project virtual environment:

```bash
./mdh.venv/bin/python LineupCheck/check_lineups.py --force
```

The default lineup timezone is `America/New_York`. Override it when needed:

```bash
./mdh.venv/bin/python LineupCheck/check_lineups.py --timezone America/Chicago
```

RosterCop posts each report to the separate Discord webhook configured as
`[discord] lineup_webhook_url` in the root `config.cfg`. The Fantrax team IDs
are matched to the owner abbreviations used by MDH extensions, then formatted
as the same Discord user mentions. Keep this webhook URL private.

## Extension announcements

Preview an announcement without posting it. Omit `--group` to use one more than the group recorded in worksheet cell AB8:

```bash
python Extensions/main.py
```

An explicit group still overrides AB8:

```bash
python Extensions/main.py --group 39
```

Process the previous group free-agent claims on Fantrax before previewing:

```bash
python Extensions/main.py --group 39 --process
```

`--process` is independent from `--post`, so both may be used together. Processing is destructive: the command aborts if any previous-group player already has an executed `ADD`, `CLAIM`, or `CLAIM - FA` transaction, or if Fantrax rejects the commissioner action.

### Discord webhook setup

Create an incoming webhook for the target channel using [Discord's webhook setup](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks), then add its URL to the ignored root `config.cfg` file:

```ini
[discord]
webhook_url = https://discord.com/api/webhooks/WEBHOOK_ID/WEBHOOK_TOKEN
```

Then post the announcement:

```bash
python Extensions/main.py --group 39 --post
```

Without `--post`, the command only prints a preview. With `--post`, it sends the same announcement and waits for Discord to confirm that the message was created.

Treat the webhook URL as a secret and do not commit it. Webhook messages allow Discord mentions. Labels such as `@OTH` remain plain text, while valid Discord mention syntax such as `<@USER_ID>`, `<@&ROLE_ID>`, `@everyone`, and `@here` can notify their targets.
