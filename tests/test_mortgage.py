import math
import unittest
from datetime import date
import json
from pathlib import Path
import tempfile

from mortgage import (
    PartialRepayment,
    SavingsGrowthChange,
    calculate_savings_balance,
    calculate_savings_curve,
    calculate_repayment_schedule,
    calculate_schedule,
    repayment_month_index,
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
        self.assertEqual(schedule.monthly_payments, (1_000,) * 12)
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


class PartialRepaymentTests(unittest.TestCase):
    def setUp(self):
        self.start_date = date(2024, 1, 31)

    def repayment(
        self,
        amount,
        adjustment="keep_payment",
        repayment_date=date(2024, 4, 15),
    ):
        return PartialRepayment(
            id="repayment-1",
            mortgage_id="mortgage-1",
            repayment_date=repayment_date,
            amount=amount,
            adjustment=adjustment,
        )

    def test_date_applies_on_next_scheduled_payment_date(self):
        self.assertEqual(
            repayment_month_index(self.start_date, 12, self.start_date),
            1,
        )
        self.assertEqual(
            repayment_month_index(self.start_date, 12, date(2024, 4, 15)),
            3,
        )

        schedule = calculate_repayment_schedule(
            12_000,
            0,
            12,
            self.start_date,
            (self.repayment(3_000),),
        )

        self.assertEqual(schedule.balances[3], 6_000)
        self.assertEqual(schedule.balances[9], 0)
        self.assertEqual(schedule.monthly_payment, 1_000)

    def test_keep_end_date_recalculates_payment_through_original_maturity(self):
        schedule = calculate_repayment_schedule(
            12_000,
            0,
            12,
            self.start_date,
            (self.repayment(3_000, "keep_end_date"),),
        )

        self.assertEqual(schedule.balances[3], 6_000)
        self.assertAlmostEqual(schedule.balances[4], 6_000 - 6_000 / 9)
        self.assertAlmostEqual(schedule.balances[-1], 0)
        self.assertAlmostEqual(schedule.monthly_payments[3], 6_000 / 9)
        self.assertEqual(schedule.monthly_payment, 1_000)
        self.assertEqual(len(schedule.monthly_payment_changes), 1)
        self.assertEqual(schedule.monthly_payment_changes[0][0], 4)
        self.assertAlmostEqual(
            schedule.monthly_payment_changes[0][1], 1_000 / 3
        )

    def test_keep_payment_adds_savings_growth_after_early_payoff(self):
        schedule = calculate_repayment_schedule(
            12_000,
            0,
            12,
            self.start_date,
            (
                self.repayment(
                    7_000,
                    "keep_payment",
                    repayment_date=date(2024, 2, 15),
                ),
            ),
        )

        self.assertEqual(schedule.balances[5], 0)
        self.assertEqual(schedule.monthly_payment_changes, ((6, 1_000.0),))

    def test_start_date_repayment_applies_at_first_payment_date(self):
        schedule = calculate_repayment_schedule(
            12_000,
            0,
            12,
            self.start_date,
            (
                self.repayment(
                    2_000,
                    "keep_end_date",
                    repayment_date=self.start_date,
                ),
            ),
        )

        self.assertEqual(schedule.balances[0], 12_000)
        self.assertEqual(schedule.balances[1], 9_000)
        self.assertEqual(schedule.monthly_payment, 1_000)
        self.assertAlmostEqual(schedule.monthly_payments[1], 9_000 / 11)

    def test_multiple_repayments_are_applied_in_date_order(self):
        later_repayment = self.repayment(
            500,
            repayment_date=date(2024, 3, 1),
        )
        earlier_repayment = PartialRepayment(
            "repayment-2",
            "mortgage-1",
            date(2024, 2, 15),
            1_000,
            "keep_payment",
        )

        schedule = calculate_repayment_schedule(
            12_000,
            0,
            12,
            self.start_date,
            (later_repayment, earlier_repayment),
        )

        self.assertEqual(schedule.balances[1], 10_000)
        self.assertEqual(schedule.balances[2], 8_500)

    def test_rejects_repayment_above_remaining_balance(self):
        with self.assertRaisesRegex(ValueError, "exceeds the remaining mortgage balance"):
            calculate_repayment_schedule(
                12_000,
                0,
                12,
                self.start_date,
                (self.repayment(11_000.01, repayment_date=date(2024, 2, 15)),),
            )

    def test_rejects_repayment_outside_mortgage_term(self):
        with self.assertRaisesRegex(ValueError, "within the mortgage term"):
            calculate_repayment_schedule(
                12_000,
                0,
                12,
                self.start_date,
                (self.repayment(100, repayment_date=date(2025, 2, 1)),),
            )


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

    def test_personal_repayment_reduces_savings_on_entered_date(self):
        repayment = PartialRepayment(
            "repayment-1",
            "mortgage-1",
            date(2024, 2, 15),
            200,
            "keep_payment",
            "personal_savings",
        )
        external_repayment = PartialRepayment(
            "repayment-2",
            "mortgage-1",
            date(2024, 3, 15),
            500,
            "keep_payment",
            "external_fund",
        )

        dates, balances = calculate_savings_curve(
            1_000,
            100,
            date(2024, 1, 31),
            date(2024, 3, 31),
            (repayment, external_repayment),
        )

        self.assertEqual(
            dates,
            (
                date(2024, 1, 31),
                date(2024, 2, 15),
                date(2024, 2, 29),
                date(2024, 3, 31),
            ),
        )
        self.assertEqual(balances, (1_000, 800, 900, 1_000))

    def test_savings_availability_includes_anniversary_contribution_and_debits(self):
        first_repayment = PartialRepayment(
            "repayment-1",
            "mortgage-1",
            date(2024, 2, 29),
            200,
            "keep_payment",
            "personal_savings",
        )
        second_repayment = PartialRepayment(
            "repayment-2",
            "mortgage-1",
            date(2024, 3, 15),
            100,
            "keep_payment",
            "personal_savings",
        )

        self.assertEqual(
            calculate_savings_balance(
                1_000,
                100,
                date(2024, 1, 31),
                date(2024, 3, 15),
                (first_repayment, second_repayment),
            ),
            800,
        )

    def test_payment_reduction_increases_savings_growth_from_effective_date(self):
        growth_change = SavingsGrowthChange(date(2024, 2, 29), 300)

        self.assertEqual(
            calculate_savings_balance(
                1_000,
                100,
                date(2024, 1, 31),
                date(2024, 3, 31),
                growth_changes=(growth_change,),
            ),
            1_800,
        )

    def test_savings_curve_includes_payment_change_date_and_growth(self):
        dates, balances = calculate_savings_curve(
            0,
            100,
            date(2024, 1, 31),
            date(2024, 3, 31),
            growth_changes=(SavingsGrowthChange(date(2024, 2, 15), 300),),
        )

        self.assertEqual(
            dates,
            (
                date(2024, 1, 31),
                date(2024, 2, 15),
                date(2024, 2, 29),
                date(2024, 3, 31),
            ),
        )
        self.assertEqual(balances, (0, 0, 400, 800))

    def test_multiple_mortgage_payment_changes_accumulate_in_savings(self):
        growth_changes = (
            SavingsGrowthChange(date(2024, 2, 29), 300),
            SavingsGrowthChange(date(2024, 3, 31), 1_000),
        )

        self.assertEqual(
            calculate_savings_balance(
                0,
                100,
                date(2024, 1, 31),
                date(2024, 4, 30),
                growth_changes=growth_changes,
            ),
            3_200,
        )

    def test_personal_repayment_cannot_predate_savings_start(self):
        repayment = PartialRepayment(
            "repayment-1",
            "mortgage-1",
            date(2024, 1, 30),
            200,
            "keep_payment",
            "personal_savings",
        )

        with self.assertRaisesRegex(ValueError, "cannot predate the savings start date"):
            calculate_savings_curve(
                1_000,
                100,
                date(2024, 1, 31),
                date(2024, 3, 31),
                (repayment,),
            )

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
        self.assertEqual(
            load_inputs(self.path, self.defaults, self.default_savings).repayments,
            (),
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
        repayments = (
            PartialRepayment(
                "repayment-1",
                "mortgage-1",
                date(2025, 7, 1),
                2_500,
                "keep_end_date",
                "personal_savings",
            ),
            PartialRepayment(
                "repayment-2",
                "mortgage-2",
                date(2025, 7, 15),
                500,
                "keep_payment",
            ),
        )
        save_inputs(self.path, mortgages, savings, repayments)

        loaded = load_inputs(self.path, self.defaults, self.default_savings)
        self.assertEqual(loaded.mortgages, mortgages)
        self.assertEqual(loaded.savings, savings)
        self.assertEqual(loaded.repayments, repayments)

    def test_legacy_repayment_without_funding_source_defaults_to_external(self):
        self.path.write_text(
            json.dumps(
                {
                    "mortgages": [
                        {
                            "id": self.defaults.id,
                            "name": self.defaults.name,
                            "principal": self.defaults.principal,
                            "annual_rate": self.defaults.annual_rate,
                            "duration_months": self.defaults.duration_months,
                            "start_date": self.defaults.start_date.isoformat(),
                        }
                    ],
                    "savings": {
                        "current_total": self.default_savings.current_total,
                        "start_date": self.default_savings.start_date.isoformat(),
                        "monthly_amount": self.default_savings.monthly_amount,
                    },
                    "repayments": [
                        {
                            "id": "repayment-1",
                            "mortgage_id": self.defaults.id,
                            "repayment_date": "2024-02-01",
                            "amount": 100,
                            "adjustment": "keep_payment",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        loaded = load_inputs(self.path, self.defaults, self.default_savings)

        self.assertEqual(loaded.repayments[0].funding_source, "external_fund")

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

    def test_invalid_persisted_repayment_target_raises_clear_error(self):
        save_inputs(
            self.path,
            (self.defaults,),
            self.default_savings,
            (
                PartialRepayment(
                    "repayment-1",
                    "missing-mortgage",
                    date(2024, 2, 1),
                    100,
                    "keep_payment",
                ),
            ),
        )

        with self.assertRaisesRegex(
            UserInputStorageError, "each repayment must target a saved mortgage"
        ):
            load_inputs(self.path, self.defaults, self.default_savings)


if __name__ == "__main__":
    unittest.main()
