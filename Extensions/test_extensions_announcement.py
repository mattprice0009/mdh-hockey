import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

import main as main_module
from discord_webhook import (
    DISCORD_CONTENT_LIMIT,
    DiscordWebhookError,
    post_to_discord,
)
from extension_data import fetch_recent_claims, update_posted_group
from extension_announcement import (
    ClaimBid,
    build_announcement,
    compensation_for_salary,
    format_money,
    format_owner,
    format_tie_salary,
    parse_compensation_tiers,
    players_for_group,
)
from main import parse_args

VALUES = [
    ["Group", "Player", "Owner", "Start Bid"],
    [38, "John Carlson, D, WSH, 35 (UFA), 5 year(s), 3.45 fpts/gp", "EXP", 3163017.0316],
    [38, "Carter Verhaeghe, F, FLA, 29 (UFA), 6 year(s), 3.56 fpts/gp", "EXP", 685000],
    [38, "Aliaksei Protas, F, WSH, 24 (RFA), 1 year(s), 3.66 fpts/gp", "WTM", 656250],
    [39, "Kiefer Sherwood, F, VAN, 30 (UFA), 4 year(s), 4.74 fpts/gp", "EXP", 525000],
    [39, "Alexander Romanov, D, NYI, 25 (RFA), 1 year(s), 3.32 fpts/gp", "BAR", 656250],
    [39, "Artturi Lehkonen, F, COL, 29 (UFA), 1 year(s), 3.23 fpts/gp", "BR0KE", 525000],
    ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "Groups", "F1", "F2", "D", "G"],
    ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", 38, "Protas*", "Verhaeghe", "Carlson", ""],
    ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", 39, "Sherwood", "Lehkonen", "Romanov*", ""],
]
BID_GRID_VALUES = [
    ["Picks", "4x 1st, 4x 2nd", "4x 1st", "2x 1st", "1st", "2nd", "3rd", "4th"],
    ["Min", "15M + 1", "12M + 1", "9M + 1", "6M + 1", "3M + 1", "1.5M + 1", "750k"],
    ["Max", "MAX", "15M", "12M", "9M", "6M", "3M", "1.5M"],
]

class AnnouncementTests(unittest.TestCase):
    def test_group_order_uses_planning_grid(self):
        self.assertEqual(
            [player.name for player in players_for_group(VALUES, 39)],
            ["Kiefer Sherwood", "Artturi Lehkonen", "Alexander Romanov"],
        )

    def test_money_rounds_half_up(self):
        self.assertEqual(format_money(Decimal("3015153.5")), "$3,015,154")

    def test_announcement_claim_and_auto_match(self):
        output = build_announcement(
            39, VALUES, {"carter verhaeghe": Decimal("3015153.5")}
        )
        self.assertIn("Alexander Romanov* (D), 1 year, $656,250", output)
        self.assertIn(
            format_owner("WTM")
            + " on 1 year of Aliaksei Protas* at "
            + format_money(Decimal("656250"))
            + " (No bids, auto-matched)",
            output,
        )
        self.assertIn(
            format_owner("EXP")
            + " on 6 years of Carter Verhaeghe at "
            + format_money(Decimal("3015154")),
            output
        )
        self.assertNotIn("$3,015,154 (", output)
        self.assertIn(
            format_owner("EXP")
            + " on 5 years of John Carlson at "
            + format_money(Decimal("3163017"))
            + " (No bids, auto-matched)",
            output,
        )

    def test_rfa_winning_bid_includes_compensation(self):
        output = build_announcement(
            39,
            VALUES,
            {"aliaksei protas": Decimal("3000001")},
            BID_GRID_VALUES,
        )
        self.assertIn(
            format_owner("WTM")
            + " on 1 year of Aliaksei Protas* at "
            + format_money(Decimal("3000001"))
            + " (2nd)",
            output,
        )

    def test_bid_grid_boundaries_are_inclusive(self):
        tiers = parse_compensation_tiers(BID_GRID_VALUES)
        self.assertEqual(compensation_for_salary(Decimal("750000"), tiers), "4th")
        self.assertEqual(compensation_for_salary(Decimal("1500000"), tiers), "4th")
        self.assertEqual(compensation_for_salary(Decimal("1500001"), tiers), "3rd")
        self.assertEqual(
            compensation_for_salary(Decimal("15000001"), tiers),
            "4x 1st, 4x 2nd",
        )

    def test_tie_alert_follows_matching_decisions(self):
        values = [
            ["Group", "Player", "Owner", "Start Bid"],
            [1, "Connor McDavid, F, EDM, 29 (UFA), 1 year(s)", "2PRO", 19000000],
            [2, "Nathan MacKinnon, F, COL, 30 (UFA), 1 year(s)", "EXP", 1000000],
        ]
        claims = {
            "connor mcdavid": [
                ClaimBid(Decimal("19100000"), "WRINGS"),
                ClaimBid(Decimal("19100000"), "CTU"),
                ClaimBid(Decimal("19100000"), "DWM"),
                ClaimBid(Decimal("19100000"), "GetRekt"),
                ClaimBid(Decimal("19000000"), "EXP"),
            ]
        }

        lines = build_announcement(2, values, claims).splitlines()

        matching_index = lines.index(
            f"{format_owner('2PRO')} on 1 year of Connor McDavid at "
            f"{format_money(Decimal('19100000'))}"
        )
        bidders = (
            f"{format_owner('WRINGS')}, {format_owner('CTU')}, "
            f"{format_owner('DWM')}, and {format_owner('GetRekt')}"
        )
        self.assertEqual(
            lines[matching_index + 2],
            f"<a:goalsiren:1354137595424014470> We have a tie! If "
            f"{format_owner('2PRO')} decides to "
            f"match, it ends there. If {format_owner('2PRO')} does not match, "
            "then we will begin the tiebreaker process where "
            f"{bidders} bid again with no salary cap limit. Winner gets Connor "
            f"McDavid at {format_tie_salary(Decimal('19100000'))} and a has a "
            "\"Signing Bonus\" cap hit of the overage.",
        )

class ExtensionDataTests(unittest.TestCase):
    @patch("mdhhockey.helpers.CAPFRIENDLY_GRAPH_URL_ROOT", "https://graph.test/workbook")
    @patch("mdhhockey.helpers._acquire_azure_token")
    @patch("extension_data.requests.patch")
    def test_updates_posted_group_cell(self, request_patch, acquire_token):
        acquire_token.return_value = {"access_token": "excel-token"}
        response = Mock()
        request_patch.return_value = response

        update_posted_group(39)

        request_patch.assert_called_once_with(
            "https://graph.test/workbook/worksheets/Extensions%20Research"
            "/range(address='AB8')",
            headers={"Authorization": "Bearer excel-token"},
            json={"values": [[39]]},
            timeout=30,
        )
        response.raise_for_status.assert_called_once_with()

    @patch("extension_data.requests.post")
    def test_transaction_history_includes_unexecuted_transactions(self, request_post):
        response = Mock()
        response.json.return_value = {
            "responses": [{"data": {"table": {"rows": []}}}]
        }
        request_post.return_value = response

        fetch_recent_claims()

        payload = request_post.call_args.kwargs["json"]
        request_data = payload["msgs"][0]["data"]
        self.assertFalse(request_data["executedOnly"])
        self.assertFalse(request_data["includeDeleted"])

    @patch("extension_data.requests.post")
    def test_keeps_all_bidders_for_tie_detection(self, request_post):
        response = Mock()
        response.json.return_value = {
            "responses": [
                {
                    "data": {
                        "table": {
                            "rows": [
                                {
                                    "transactionCode": "CLAIM",
                                    "executed": False,
                                    "deleted": False,
                                    "scorer": {"name": "Connor McDavid"},
                                    "cells": [
                                        {"key": "team", "teamId": "np7jgzqrmoafw8b9"},
                                        {"key": "bid", "content": "19100000"},
                                    ],
                                },
                                {
                                    "transactionCode": "CLAIM",
                                    "executed": False,
                                    "deleted": False,
                                    "scorer": {"name": "Connor McDavid"},
                                    "cells": [
                                        {"key": "team", "teamId": "9sv3988vmoafw8b7"},
                                        {"key": "bid", "content": "19100000"},
                                    ],
                                },
                            ]
                        }
                    }
                }
            ]
        }
        request_post.return_value = response

        claims = fetch_recent_claims()

        self.assertEqual(
            claims["connor mcdavid"],
            [
                ClaimBid(Decimal("19100000"), "WRINGS"),
                ClaimBid(Decimal("19100000"), "CTU"),
            ],
        )

class DiscordWebhookTests(unittest.TestCase):
    @patch("discord_webhook.DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    @patch("discord_webhook.requests.post")
    def test_posts_content_and_waits_for_confirmation(self, request_post):
        response = Mock()
        response.json.return_value = {"id": "message-id"}
        request_post.return_value = response

        result = post_to_discord("Announcement")

        self.assertEqual(result, {"id": "message-id"})
        request_post.assert_called_once_with(
            "https://discord.test/webhook",
            params={"wait": "true"},
            json={"content": "Announcement"},
            timeout=30,
        )
        response.raise_for_status.assert_called_once_with()

    @patch("discord_webhook.DISCORD_WEBHOOK_URL", "")
    @patch("discord_webhook.requests.post")
    def test_rejects_missing_webhook_url_without_request(self, request_post):
        with self.assertRaisesRegex(
            DiscordWebhookError, "webhook URL is not configured"
        ):
            post_to_discord("Announcement")

        request_post.assert_not_called()

    @patch("discord_webhook.DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    @patch("discord_webhook.requests.post")
    def test_rejects_content_over_discord_limit(self, request_post):
        with self.assertRaisesRegex(DiscordWebhookError, "exceeds 2000 characters"):
            post_to_discord("x" * (DISCORD_CONTENT_LIMIT + 1))

        request_post.assert_not_called()

class CommandLineTests(unittest.TestCase):
    def test_posting_is_opt_in(self):
        self.assertFalse(parse_args(["--group", "39"]).post)
        self.assertTrue(parse_args(["--group", "39", "--post"]).post)

    @patch("main.update_posted_group")
    @patch("main.post_to_discord")
    @patch("main.build_announcement", return_value="Announcement")
    @patch("main.fetch_recent_claims", return_value={})
    @patch("main.fetch_sheet_values", side_effect=[VALUES, BID_GRID_VALUES])
    def test_posting_records_group_in_excel(
        self,
        fetch_values,
        fetch_claims,
        build,
        post,
        update_group,
    ):
        update_group.side_effect = lambda group: self.assertTrue(post.called)
        result = main_module.main(["--group", "39", "--post"])

        self.assertEqual(result, 0)
        post.assert_called_once_with("Announcement")
        update_group.assert_called_once_with(39)

if __name__ == "__main__":
    unittest.main()
