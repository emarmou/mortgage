"""Load and save locally persisted mortgage scenarios."""

from dataclasses import dataclass
from datetime import date
import json
import math
import os
from pathlib import Path
import tempfile


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
    elif isinstance(data, dict):
        records = [{"id": "mortgage-1", "name": "Mortgage 1", **data}]
        savings_data = _serialize_savings(default_savings)
    elif isinstance(data, list):
        records = data
        savings_data = _serialize_savings(default_savings)
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
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise UserInputStorageError(f"Saved inputs are invalid: {error}") from error
    return CalculatorInputs(mortgages, savings)


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
) -> None:
    """Atomically save every mortgage and personal savings input locally."""
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
            }
            json.dump(data, temporary_file, indent=2)
            temporary_file.write("\n")
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError, OverflowError) as error:
        raise UserInputStorageError(f"Could not save inputs: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
