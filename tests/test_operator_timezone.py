"""Operator-facing timestamps are standardized on Johannesburg time."""
from datetime import timedelta
import unittest
from zoneinfo import ZoneInfo

from gungnir.core.timezone import operator_now


class OperatorTimezoneTests(unittest.TestCase):
    def test_operator_now_returns_johannesburg_aware_timestamp(self):
        value = operator_now()

        self.assertEqual(value.tzinfo, ZoneInfo("Africa/Johannesburg"))
        self.assertEqual(value.utcoffset(), timedelta(hours=2))


if __name__ == "__main__":
    unittest.main()
