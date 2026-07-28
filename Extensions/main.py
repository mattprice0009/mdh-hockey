#!/usr/bin/env python3
"""Build or post a Discord announcement for an MDH extension group."""

from __future__ import annotations

import argparse
import sys
from typing import Iterable

import requests

from discord_webhook import DiscordWebhookError, post_to_discord
from extension_announcement import (
    AnnouncementError,
    DEFAULT_BID_GRID_SHEET,
    DEFAULT_SHEET,
    build_announcement_for_players,
    players_for_group,
)
from extension_data import (
    fetch_sheet_values,
    infer_next_group,
    update_posted_group,
)
from fantrax_processing import (
    claim_bids_from_transactions,
    ensure_group_not_processed,
    fantrax_session,
    fetch_transaction_rows,
    process_free_agent_claims,
)

def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--group",
        type=int,
        help="group to announce (default: one more than worksheet cell AB8)",
    )
    parser.add_argument(
        "--sheet", default=DEFAULT_SHEET, help="CapFriendly worksheet name"
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="post through the configured Discord webhook instead of printing",
    )
    parser.add_argument(
        "--process",
        action="store_true",
        help="process all Fantrax free-agent claims before announcing",
    )
    args = parser.parse_args(argv)
    if args.group is not None and args.group < 1:
        parser.error("--group must be at least 1")
    return args

def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        values = fetch_sheet_values(args.sheet)
        group = args.group if args.group is not None else infer_next_group(values)
        if args.process and group == 1:
            raise AnnouncementError(
                "--process requires a group with a preceding group."
            )
        bid_grid_values = fetch_sheet_values(DEFAULT_BID_GRID_SHEET)
        current_players = players_for_group(values, group)
        previous_players = (
            players_for_group(values, group - 1)
            if group > 1
            else []
        )
        transaction_rows = fetch_transaction_rows()
        if args.process:
            ensure_group_not_processed(previous_players, transaction_rows)
            with fantrax_session() as session:
                process_free_agent_claims(session)
            transaction_rows = fetch_transaction_rows()
        claims = claim_bids_from_transactions(transaction_rows)
        announcement = build_announcement_for_players(
            group,
            current_players,
            previous_players,
            claims,
            bid_grid_values,
        )
        if args.post:
            post_to_discord(announcement)
            update_posted_group(group)
            action = "Claims processed; " if args.process else ""
            print(
                action
                + "announcement posted to Discord and group recorded in Excel."
            )
        else:
            if args.process:
                print("Free-agent claims processed on Fantrax.")
            print(announcement)
    except (AnnouncementError, DiscordWebhookError, requests.RequestException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
