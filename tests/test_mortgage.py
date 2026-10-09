import math
import unittest
from datetime import date
import json
from pathlib import Path
import tempfile

from mortgage import (
    calculate_savings_curve,
    calculate_schedule,
    schedule_dates,
    sum_balance_curves,
)
from user_inputs import (
    MortgageInputs,
    PersonalSavings,
    UserInputStorageError,
    load_inputs,
    save_inputs,
)


class CalculateScheduleTests(unittest.TestCase):
    def test_zero_interest_divides_principal_evenly(self):
        schedule = calculate_schedule(12_000, 0, 12)

        self.assertEqual(schedule.monthly_payment, 1_000)
        self.assertEqual(schedule.total_interest, 0)
        self.assertEqual(len(schedule.balances), 13)
        self.assertEqual(schedule.balances[0], 12_000)
        self.assertEqual(schedule.balances[-1], 0)

    def test_positive_interest_amortizes_over_full_duration(self):
        schedule = calculate_schedule(250_000, 4.5, 360)

        self.assertAlmostEqual(schedule.monthly_payment, 1_266.71, places=2)
        self.assertGreater(schedule.total_interest, 0)
        self.assertEqual(schedule.balances[0], 250_000)
        self.assertEqual(schedule.balances[-1], 0)
        self.assertTrue(
            all(later <= earlier for earlier, later in zip(
                schedule.balances, schedule.balances[1:]
            ))
        )

    def test_small_rate_has_finite_payment(self):
        schedule = calculate_schedule(100_000, 0.000001, 360)

        self.assertTrue(math.isfinite(schedule.monthly_payment))
        self.assertAlmostEqual(schedule.monthly_payment, 100_000 / 360, places=3)

    def test_rejects_invalid_inputs(self):
        invalid_inputs = [
            (0, 4.5, 360),
            (100_000, -1, 360),
            (100_000, 4.5, 0),
            (100_000, 4.5, 12.5),
            (float("inf"), 4.5, 360),
        ]
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                calculate_schedule(*inputs)


class ScheduleDatesTests(unittest.TestCase):
    def test_dates_follow_monthly_anniversaries_from_start_date(self):
        dates = schedule_dates(date(2024, 1, 31), 3)

        self.assertEqual(
            dates,
            (
                date(2024, 1, 31),
                date(2024, 2, 29),
                date(2024, 3, 31),
                date(2024, 4, 30),
            ),
        )

    def test_rejects_invalid_duration(self):
        for duration in (0, 1.5, True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                schedule_dates(date(2024, 1, 1), duration)


class SumBalanceCurvesTests(unittest.TestCase):
    def test_sums_balances_on_union_of_dates_and_carries_forward(self):
        first_curve = (
            (date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)),
            (100.0, 50.0, 0.0),
        )
        second_curve = (
            (date(2024, 2, 15), date(2024, 3, 15)),
            (200.0, 0.0),
        )

        dates, totals = sum_balance_curves((first_curve, second_curve))

        self.assertEqual(
            dates,
            (
                date(2024, 1, 1),
                date(2024, 2, 1),
                date(2024, 2, 15),
                date(2024, 3, 1),
                date(2024, 3, 15),
            ),
        )
        self.assertEqual(totals, (100.0, 50.0, 250.0, 200.0, 0.0))

    def test_rejects_unaligned_curve_data(self):
        with self.assertRaisesRegex(ValueError, "one balance per date"):
            sum_balance_curves((((date(2024, 1, 1),), (100.0, 50.0)),))


class SavingsCurveTests(unittest.TestCase):
    def test_accumulates_monthly_and_stops_on_requested_end_date(self):
        dates, balances = calculate_savings_curve(
            1_000,
            200,
            date(2024, 1, 31),
            date(2024, 4, 15),
        )

        self.assertEqual(
            dates,
            (
                date(2024, 1, 31),
                date(2024, 2, 29),
                date(2024, 3, 31),
                date(2024, 4, 15),
            ),
        )
        self.assertEqual(balances, (1_000, 1_200, 1_400, 1_400))

    def test_returns_no_curve_if_savings_start_after_mortgage_end(self):
        self.assertEqual(
            calculate_savings_curve(1_000, 200, date(2024, 2, 1), date(2024, 1, 31)),
            ((), ()),
        )

    def test_rejects_negative_savings(self):
        with self.assertRaisesRegex(ValueError, "Current savings"):
            calculate_savings_curve(-1, 200, date(2024, 1, 1), date(2024, 2, 1))
        with self.assertRaisesRegex(ValueError, "Monthly saving"):
            calculate_savings_curve(1_000, -1, date(2024, 1, 1), date(2024, 2, 1))


class UserInputStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "mortgage_inputs.json"
        self.defaults = MortgageInputs(
            "mortgage-1",
            "Mortgage 1",
            250_000,
            4.5,
            360,
            date(2024, 1, 31),
        )
        self.default_savings = PersonalSavings(5_000, date(2024, 1, 31), 500)

    def test_missing_file_returns_defaults(self):
        self.assertEqual(
            load_inputs(self.path, self.defaults, self.default_savings).mortgages,
            (self.defaults,),
        )
        self.assertEqual(
            load_inputs(self.path, self.defaults, self.default_savings).savings,
            self.default_savings,
        )

    def test_all_inputs_load_after_restart(self):
        mortgages = (
            self.defaults,
            MortgageInputs(
                "mortgage-2",
                "Second home",
                320_000.5,
                3.75,
                240,
                date(2025, 6, 15),
            ),
        )

        savings = PersonalSavings(8_500, date(2025, 6, 15), 750)
        save_inputs(self.path, mortgages, savings)

        loaded = load_inputs(self.path, self.defaults, self.default_savings)
        self.assertEqual(loaded.mortgages, mortgages)
        self.assertEqual(loaded.savings, savings)

    def test_migrates_legacy_single_mortgage_file(self):
        self.path.write_text(
            json.dumps(
                {
                    "principal": 320_000,
                    "annual_rate": 3.75,
                    "duration_months": 240,
                    "start_date": "2025-06-15",
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual(
            load_inputs(self.path, self.defaults, self.default_savings).mortgages,
            (
                MortgageInputs(
                    "mortgage-1",
                    "Mortgage 1",
                    320_000,
                    3.75,
                    240,
                    date(2025, 6, 15),
                ),
            ),
        )

    def test_invalid_saved_inputs_raise_clear_error(self):
        self.path.write_text(
            json.dumps([{"id": "bad", "name": "Invalid", "principal": -100}]),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(UserInputStorageError, "Saved inputs are invalid"):
            load_inputs(self.path, self.defaults, self.default_savings)

    def test_invalid_persisted_savings_raise_clear_error(self):
        save_inputs(self.path, (self.defaults,), self.default_savings)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        saved["savings"]["monthly_amount"] = -1
        self.path.write_text(json.dumps(saved), encoding="utf-8")

        with self.assertRaisesRegex(UserInputStorageError, "savings monthly_amount"):
            load_inputs(self.path, self.defaults, self.default_savings)


if __name__ == "__main__":
    unittest.main()
