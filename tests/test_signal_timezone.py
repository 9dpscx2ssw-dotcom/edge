"""Operator-facing signal timestamps use Johannesburg time."""
from datetime import timedelta
import unittest
from zoneinfo import ZoneInfo

from gungnir.data.models import Side, Signal


class SignalTimezoneTests(unittest.TestCase):
    def test_new_signal_timestamp_is_johannesburg_time(self):
        signal = Signal(strategy="test", symbol="US100", side=Side.BUY, conviction=0.5)

        self.assertEqual(signal.ts.tzinfo, ZoneInfo("Africa/Johannesburg"))
        self.assertEqual(signal.ts.utcoffset(), timedelta(hours=2))


if __name__ == "__main__":
    unittest.main()
