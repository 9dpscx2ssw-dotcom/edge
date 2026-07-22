"""Strict zero-line momentum contract for EMA9/21 ADX/DMI signals."""
import unittest

from gungnir.strategy.kraken_strategies import _has_directional_momentum


class EMA921MomentumTests(unittest.TestCase):
    def test_momentum_must_be_strictly_signed_in_signal_direction(self):
        self.assertTrue(_has_directional_momentum(1.0, 1))
        self.assertTrue(_has_directional_momentum(-1.0, -1))
        self.assertFalse(_has_directional_momentum(0.0, 1))
        self.assertFalse(_has_directional_momentum(0.0, -1))
        self.assertFalse(_has_directional_momentum(-0.1, 1))
        self.assertFalse(_has_directional_momentum(0.1, -1))


if __name__ == "__main__":
    unittest.main()
