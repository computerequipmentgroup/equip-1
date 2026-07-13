from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class FakeClock:
    def __init__(self):
        self.now = 1.0
        self.sleeps: list[float] = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds):
        self.now += seconds


class FakeGPIO:
    instances: list["FakeGPIO"] = []

    def __init__(self, chip, line, direction):
        self.chip = chip
        self.line = line
        self.direction = direction
        self.closed = False
        self.reads: list[bool] = []
        self.writes: list[bool] = []
        FakeGPIO.instances.append(self)

    def read(self):
        if self.reads:
            return self.reads.pop(0)
        return True

    def write(self, value):
        self.writes.append(bool(value))

    def close(self):
        self.closed = True


class OledInputTests(unittest.TestCase):
    def setUp(self):
        FakeGPIO.instances = []
        periphery = types.ModuleType("periphery")
        periphery.GPIO = FakeGPIO
        self.previous_periphery = sys.modules.get("periphery")
        sys.modules["periphery"] = periphery

        import uis.oled.input as oled_input

        self.oled_input = oled_input
        self.previous_time = oled_input.time
        self.clock = FakeClock()
        oled_input.time = types.SimpleNamespace(monotonic=self.clock.monotonic, sleep=self.clock.sleep)

    def tearDown(self):
        self.oled_input.time = self.previous_time
        if self.previous_periphery is None:
            sys.modules.pop("periphery", None)
        else:
            sys.modules["periphery"] = self.previous_periphery

    def test_button_debounces_release_and_repress_edges(self):
        button = self.oled_input.Button("chip", 7, debounce_seconds=0.050)
        gpio = FakeGPIO.instances[-1]

        gpio.reads = [False]
        self.assertTrue(button.pressed())

        gpio.reads = [True]
        self.assertFalse(button.pressed())

        self.clock.advance(0.010)
        gpio.reads = [False]
        self.assertFalse(button.pressed())

        gpio.reads = [True]
        self.assertFalse(button.pressed())

        self.clock.advance(0.050)
        gpio.reads = [False]
        self.assertTrue(button.pressed())

    def test_buzzer_idles_silent_and_only_activates_during_beep(self):
        board = self.oled_input.BoardConfig("test", 0, "/dev/gpiochip-test", 7, 1, 2, 3)

        buzzer = self.oled_input.Buzzer(board, beep_seconds=0.020)
        gpio = FakeGPIO.instances[-1]
        self.assertEqual(gpio.writes, [True])

        buzzer.beep()
        self.assertEqual(gpio.writes, [True, False, True])
        self.assertEqual(self.clock.sleeps, [0.020])

        buzzer.close()
        self.assertEqual(gpio.writes, [True, False, True, True])
        self.assertTrue(gpio.closed)


if __name__ == "__main__":
    unittest.main()
