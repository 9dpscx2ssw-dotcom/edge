"""Regression tests for Capital.com candle time parsing."""
from datetime import datetime, timezone
import unittest

from gungnir.data.capital_com_feed import _parse_candles


class CapitalCandleTimestampTests(unittest.TestCase):
    def test_snapshot_time_utc_is_authoritative_over_local_snapshot_time(self):
        candles = _parse_candles("US100", "5m", {
            "prices": [{
                "snapshotTime": "2026-07-22T12:30:00",
                "snapshotTimeUTC": "2026-07-22T11:30:00Z",
                "openPrice": {"bid": 1, "ask": 3},
                "highPrice": {"bid": 2, "ask": 4},
                "lowPrice": {"bid": 0, "ask": 2},
                "closePrice": {"bid": 1, "ask": 3},
            }]
        })

        self.assertEqual(len(candles), 1)
        self.assertEqual(
            candles[0].ts,
            datetime(2026, 7, 22, 11, 30, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
