"""Load and save locally persisted mortgage scenarios."""

from dataclasses import dataclass
from datetime import date
import json
import math
import os
from pathlib import Path
import tempfile

from mortgage import PartialRepayment


class UserInputStorageError(Exception):
    """Raised when saved mortgage inputs cannot be read or written."""


@dataclass(frozen=True)
class MortgageInputs:
    id: str
    name: str
    principal: float
    annual_rate: float
    duration_months: int
    start_date: date


@dataclass(frozen=True)
class PersonalSavings:
    current_total: float
    start_date: date
    monthly_amount: float


@dataclass(frozen=True)
class CalculatorInputs:
    mortgages: tuple[MortgageInputs, ...]
    savings: PersonalSavings
    repayments: tuple[PartialRepayment, ...] = ()


def load_inputs(
    path: Path,
    default_mortgage: MortgageInputs,
    default_savings: PersonalSavings,
) -> CalculatorInputs:
    """Load saved calculator inputs, migrating earlier mortgage-only formats."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return CalculatorInputs((default_mortgage,), default_savings)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UserInputStorageError(f"Could not read saved inputs: {error}") from error

    if isinstance(data, dict) and "mortgages" in data:
        records = data["mortgages"]
        savings_data = data.get("savings", _serialize_savings(default_savings))
        repayment_records = data.get("repayments", [])
    elif isinstance(data, dict):
        records = [{"id": "mortgage-1", "name": "Mortgage 1", **data}]
        savings_data = _serialize_savings(default_savings)
        repayment_records = []
    elif isinstance(data, list):
        records = data
        savings_data = _serialize_savings(default_savings)
        repayment_records = []
    else:
        raise UserInputStorageError(
            "Saved inputs are invalid: expected a mortgage list or calculator object."
        )

    try:
        savings = _parse_savings(savings_data)
        mortgages = tuple(_parse_mortgage(record) for record in records)
        if not mortgages:
            raise ValueError("at least one mortgage must be saved")
        ids = [mortgage.id for mortgage in mortgages]
        if len(ids) != len(set(ids)):
            raise ValueError("mortgage IDs must be unique")
        repayments = tuple(
            _parse_repayment(record) for record in repayment_records
        )
        repayment_ids = [repayment.id for repayment in repayments]
        if len(repayment_ids) != len(set(repayment_ids)):
            raise ValueError("repayment IDs must be unique")
        mortgage_ids = set(ids)
        if any(repayment.mortgage_id not in mortgage_ids for repayment in repayments):
            raise ValueError("each repayment must target a saved mortgage")
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise UserInputStorageError(f"Saved inputs are invalid: {error}") from error
    return CalculatorInputs(mortgages, savings, repayments)


def _parse_savings(data: object) -> PersonalSavings:
    if not isinstance(data, dict):
        raise ValueError("saved savings must be a JSON object")
    current_total = data["current_total"]
    monthly_amount = data["monthly_amount"]
    start_date_text = data["start_date"]
    for field_name, value in (
        ("current_total", current_total),
        ("monthly_amount", monthly_amount),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"savings {field_name} must be a finite non-negative number")
    if not isinstance(start_date_text, str):
        raise ValueError("savings start_date must be an ISO date string")
    start_date = date.fromisoformat(start_date_text)
    if start_date.isoformat() != start_date_text:
        raise ValueError("savings start_date must use YYYY-MM-DD format")
    return PersonalSavings(
        current_total=float(current_total),
        start_date=start_date,
        monthly_amount=float(monthly_amount),
    )


def _parse_mortgage(data: object) -> MortgageInputs:
    if not isinstance(data, dict):
        raise ValueError("each mortgage must be a JSON object")

    mortgage_id = data["id"]
    name = data["name"]
    principal = data["principal"]
    annual_rate = data["annual_rate"]
    duration_months = data["duration_months"]
    start_date_text = data["start_date"]

    if not isinstance(mortgage_id, str) or not mortgage_id:
        raise ValueError("mortgage id must be a non-empty string")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("mortgage name must be a non-empty string")
    if (
        isinstance(principal, bool)
        or not isinstance(principal, (int, float))
        or not math.isfinite(principal)
        or principal <= 0
    ):
        raise ValueError("principal must be a finite number greater than zero")
    if (
        isinstance(annual_rate, bool)
        or not isinstance(annual_rate, (int, float))
        or not math.isfinite(annual_rate)
        or annual_rate < 0
    ):
        raise ValueError("annual_rate must be a finite non-negative number")
    if (
        isinstance(duration_months, bool)
        or not isinstance(duration_months, int)
        or duration_months <= 0
    ):
        raise ValueError("duration_months must be a positive whole number")
    if not isinstance(start_date_text, str):
        raise ValueError("start_date must be an ISO date string")
    start_date = date.fromisoformat(start_date_text)
    if start_date.isoformat() != start_date_text:
        raise ValueError("start_date must use YYYY-MM-DD format")

    return MortgageInputs(
        id=mortgage_id,
        name=name.strip(),
        principal=float(principal),
        annual_rate=float(annual_rate),
        duration_months=duration_months,
        start_date=start_date,
    )


def _parse_repayment(data: object) -> PartialRepayment:
    if not isinstance(data, dict):
        raise ValueError("each repayment must be a JSON object")

    repayment_id = data["id"]
    mortgage_id = data["mortgage_id"]
    repayment_date_text = data["repayment_date"]
    amount = data["amount"]
    adjustment = data["adjustment"]

    if not isinstance(repayment_id, str) or not repayment_id:
        raise ValueError("repayment id must be a non-empty string")
    if not isinstance(mortgage_id, str) or not mortgage_id:
        raise ValueError("repayment mortgage_id must be a non-empty string")
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(amount)
        or amount <= 0
    ):
        raise ValueError("repayment amount must be a finite number greater than zero")
    if not isinstance(repayment_date_text, str):
        raise ValueError("repayment_date must be an ISO date string")
    repayment_date = date.fromisoformat(repayment_date_text)
    if repayment_date.isoformat() != repayment_date_text:
        raise ValueError("repayment_date must use YYYY-MM-DD format")
    if adjustment not in ("keep_payment", "keep_end_date"):
        raise ValueError("repayment adjustment is invalid")
    funding_source = data.get("funding_source", "external_fund")
    if funding_source not in ("personal_savings", "external_fund"):
        raise ValueError("repayment funding_source is invalid")

    return PartialRepayment(
        id=repayment_id,
        mortgage_id=mortgage_id,
        repayment_date=repayment_date,
        amount=float(amount),
        adjustment=adjustment,
        funding_source=funding_source,
    )


def _serialize_savings(savings: PersonalSavings) -> dict[str, object]:
    return {
        "current_total": savings.current_total,
        "start_date": savings.start_date.isoformat(),
        "monthly_amount": savings.monthly_amount,
    }


def save_inputs(
    path: Path,
    mortgages: tuple[MortgageInputs, ...],
    savings: PersonalSavings,
    repayments: tuple[PartialRepayment, ...] = (),
) -> None:
    """Atomically save mortgage, savings, and repayment inputs locally."""
    temporary_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            data = {
                "mortgages": [
                    {
                        "id": mortgage.id,
                        "name": mortgage.name,
                        "principal": mortgage.principal,
                        "annual_rate": mortgage.annual_rate,
                        "duration_months": mortgage.duration_months,
                        "start_date": mortgage.start_date.isoformat(),
                    }
                    for mortgage in mortgages
                ],
                "savings": _serialize_savings(savings),
                "repayments": [
                    {
                        "id": repayment.id,
                        "mortgage_id": repayment.mortgage_id,
                        "repayment_date": repayment.repayment_date.isoformat(),
                        "amount": repayment.amount,
                        "adjustment": repayment.adjustment,
                        "funding_source": repayment.funding_source,
                    }
                    for repayment in repayments
                ],
            }
            json.dump(data, temporary_file, indent=2)
            temporary_file.write("\n")
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError, OverflowError) as error:
        raise UserInputStorageError(f"Could not save inputs: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
