import unittest
from datetime import date
from pathlib import Path
import tempfile

from streamlit.testing.v1 import AppTest

from mortgage import calculate_repayment_schedule
from user_inputs import MortgageInputs, PersonalSavings, load_inputs


class PartialRepaymentAppTests(unittest.TestCase):
    def create_app(self, inputs_path):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        source = app_path.read_text(encoding="utf-8")
        input_path_line = (
            'INPUTS_FILE = Path(__file__).resolve().with_name("mortgage_inputs.json")'
        )
        self.assertIn(input_path_line, source)
        source = source.replace(
            input_path_line,
            f"INPUTS_FILE = Path({str(inputs_path)!r})",
        )
        app = AppTest.from_string(source).run()
        self.assertFalse(app.exception, app.exception)
        return app

    def set_widget(self, app, widgets, label, value):
        next(widget for widget in widgets if widget.label == label).set_value(
            value
        ).run()
        self.assertFalse(app.exception, app.exception)

    def test_repayment_amount_is_capped_and_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs_path = Path(directory) / "mortgage_inputs.json"
            app = self.create_app(inputs_path)

            self.set_widget(app, app.number_input, "Loan principal", 12_000.0)
            self.set_widget(app, app.number_input, "Annual interest rate (%)", 0.0)
            self.set_widget(app, app.number_input, "Duration (months)", 12)
            self.set_widget(app, app.date_input, "Starting date (T0)", date(2024, 1, 31))
            self.set_widget(app, app.date_input, "Repayment date", date(2024, 2, 15))

            amount_widget = next(
                widget for widget in app.number_input if widget.label == "Amount"
            )
            self.assertEqual(amount_widget.proto.max, 11_000)
            amount_widget.set_value(2_000).run()
            self.assertFalse(app.exception, app.exception)
            app.selectbox(key="repayment_adjustment").select(
                "Keep end date; reduce payment"
            ).run()
            self.assertFalse(app.exception, app.exception)
            next(
                widget
                for widget in app.button
                if widget.label == "Add partial repayment"
            ).click().run()
            self.assertFalse(app.exception, app.exception)

            saved_inputs = load_inputs(
                inputs_path,
                MortgageInputs(
                    "mortgage-1",
                    "Mortgage 1",
                    12_000,
                    0,
                    12,
                    date(2024, 1, 31),
                ),
                PersonalSavings(0, date(2024, 1, 31), 0),
            )
            self.assertEqual(len(saved_inputs.repayments), 1)
            repayment = saved_inputs.repayments[0]
            self.assertEqual(repayment.repayment_date, date(2024, 2, 15))
            self.assertEqual(repayment.amount, 2_000)
            self.assertEqual(repayment.adjustment, "keep_end_date")
            self.assertEqual(repayment.funding_source, "external_fund")
            schedule = calculate_repayment_schedule(
                12_000,
                0,
                12,
                date(2024, 1, 31),
                saved_inputs.repayments,
            )
            self.assertEqual(schedule.balances[1], 9_000)
            self.assertAlmostEqual(schedule.monthly_payments[1], 9_000 / 11)

    def test_personal_savings_caps_repayment_and_persists_funding_source(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs_path = Path(directory) / "mortgage_inputs.json"
            app = self.create_app(inputs_path)

            self.set_widget(app, app.number_input, "Loan principal", 12_000.0)
            self.set_widget(app, app.number_input, "Annual interest rate (%)", 0.0)
            self.set_widget(app, app.number_input, "Duration (months)", 12)
            self.set_widget(app, app.date_input, "Starting date (T0)", date(2024, 1, 31))
            self.set_widget(app, app.number_input, "Current total savings", 800.0)
            self.set_widget(app, app.date_input, "Savings starting date", date(2024, 1, 31))
            app.selectbox(key="repayment_funding_source").select(
                "personal_savings"
            ).run()
            self.assertFalse(app.exception, app.exception)
            self.set_widget(app, app.date_input, "Repayment date", date(2024, 2, 15))

            amount_widget = next(
                widget for widget in app.number_input if widget.label == "Amount"
            )
            self.assertEqual(amount_widget.proto.max, 800)
            amount_widget.set_value(500).run()
            self.assertFalse(app.exception, app.exception)
            next(
                widget
                for widget in app.button
                if widget.label == "Add partial repayment"
            ).click().run()
            self.assertFalse(app.exception, app.exception)

            saved_inputs = load_inputs(
                inputs_path,
                MortgageInputs(
                    "mortgage-1",
                    "Mortgage 1",
                    12_000,
                    0,
                    12,
                    date(2024, 1, 31),
                ),
                PersonalSavings(0, date(2024, 1, 31), 0),
            )
            repayment = saved_inputs.repayments[0]
            self.assertEqual(repayment.funding_source, "personal_savings")
            self.assertEqual(repayment.amount, 500)

    def test_removing_repayment_removes_its_frame_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            inputs_path = Path(directory) / "mortgage_inputs.json"
            app = self.create_app(inputs_path)

            self.set_widget(app, app.number_input, "Loan principal", 12_000.0)
            self.set_widget(app, app.number_input, "Annual interest rate (%)", 0.0)
            self.set_widget(app, app.number_input, "Duration (months)", 12)
            self.set_widget(
                app, app.date_input, "Starting date (T0)", date(2024, 1, 31)
            )
            self.set_widget(
                app, app.date_input, "Repayment date", date(2024, 2, 15)
            )
            next(
                widget
                for widget in app.button
                if widget.label == "Add partial repayment"
            ).click().run()
            self.assertFalse(app.exception, app.exception)

            saved_inputs = load_inputs(
                inputs_path,
                MortgageInputs(
                    "mortgage-1",
                    "Mortgage 1",
                    12_000,
                    0,
                    12,
                    date(2024, 1, 31),
                ),
                PersonalSavings(0, date(2024, 1, 31), 0),
            )
            repayment_id = saved_inputs.repayments[0].id
            remove_key = f"{repayment_id}_remove"

            app.button(key=remove_key).click().run()

            self.assertFalse(app.exception, app.exception)
            self.assertNotIn(remove_key, [widget.key for widget in app.button])
            saved_inputs = load_inputs(
                inputs_path,
                MortgageInputs(
                    "mortgage-1",
                    "Mortgage 1",
                    12_000,
                    0,
                    12,
                    date(2024, 1, 31),
                ),
                PersonalSavings(0, date(2024, 1, 31), 0),
            )
            self.assertEqual(saved_inputs.repayments, ())


if __name__ == "__main__":
    unittest.main()
