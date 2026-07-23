#!/usr/bin/env python3
"""Build or post a Discord announcement for an MDH extension group."""

from __future__ import annotations

import argparse
import sys
from typing import Iterable

import requests

from discord_webhook import DiscordWebhookError, post_to_discord
from extension_announcement import AnnouncementError, DEFAULT_SHEET, build_announcement
from extension_data import fetch_recent_claims, fetch_sheet_values

def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", type=int, required=True, help="group to announce")
    parser.add_argument(
        "--sheet", default=DEFAULT_SHEET, help="CapFriendly worksheet name"
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="post through the configured Discord webhook instead of printing",
    )
    args = parser.parse_args(argv)
    if args.group < 1:
        parser.error("--group must be at least 1")
    return args

def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        values = fetch_sheet_values(args.sheet)
        claims = fetch_recent_claims()
        announcement = build_announcement(args.group, values, claims)
        if args.post:
            post_to_discord(announcement)
            print("Announcement posted to Discord.")
        else:
            print(announcement)
    except (AnnouncementError, DiscordWebhookError, requests.RequestException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
