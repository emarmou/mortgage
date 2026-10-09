"""Mortgage amortization calculations."""

from calendar import monthrange
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
import math


@dataclass(frozen=True)
class MortgageSchedule:
    monthly_payment: float
    total_interest: float
    balances: tuple[float, ...]


def sum_balance_curves(
    curves: Iterable[tuple[Sequence[date], Sequence[float]]],
) -> tuple[tuple[date, ...], tuple[float, ...]]:
    """Sum scheduled balances on a shared timeline, carrying balances forward."""
    changes: dict[date, float] = {}
    for curve_dates, balances in curves:
        if len(curve_dates) != len(balances):
            raise ValueError("Each balance curve must have one balance per date.")
        if any(later <= earlier for earlier, later in zip(curve_dates, curve_dates[1:])):
            raise ValueError("Balance curve dates must be strictly increasing.")

        previous_balance = 0.0
        for curve_date, balance in zip(curve_dates, balances):
            changes[curve_date] = changes.get(curve_date, 0.0) + balance - previous_balance
            previous_balance = balance

    total_dates = tuple(sorted(changes))
    totals = []
    total_balance = 0.0
    for curve_date in total_dates:
        total_balance += changes[curve_date]
        totals.append(total_balance)
    return total_dates, tuple(totals)


def calculate_savings_curve(
    current_savings: float,
    monthly_savings: float,
    start_date: date,
    end_date: date,
) -> tuple[tuple[date, ...], tuple[float, ...]]:
    """Calculate savings from the current total through the requested end date."""
    if not math.isfinite(current_savings) or current_savings < 0:
        raise ValueError("Current savings must be a finite, non-negative number.")
    if not math.isfinite(monthly_savings) or monthly_savings < 0:
        raise ValueError("Monthly savings must be a finite, non-negative number.")
    if end_date < start_date:
        return (), ()

    month_span = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month
    anniversaries = (
        schedule_dates(start_date, month_span) if month_span else (start_date,)
    )
    dates = [start_date]
    balances = [current_savings]
    for month_number, anniversary in enumerate(anniversaries[1:], start=1):
        if anniversary > end_date:
            break
        dates.append(anniversary)
        balances.append(current_savings + monthly_savings * month_number)

    if dates[-1] != end_date:
        dates.append(end_date)
        balances.append(balances[-1])
    return tuple(dates), tuple(balances)


def schedule_dates(start_date: date, duration_months: int) -> tuple[date, ...]:
    """Return the start date and each monthly anniversary through the term."""
    if isinstance(duration_months, bool) or not isinstance(duration_months, int):
        raise ValueError("Duration must be a whole number of months.")
    if duration_months <= 0:
        raise ValueError("Duration must be greater than zero months.")

    dates = []
    for month_offset in range(duration_months + 1):
        absolute_month = start_date.month - 1 + month_offset
        year = start_date.year + absolute_month // 12
        month = absolute_month % 12 + 1
        day = min(start_date.day, monthrange(year, month)[1])
        dates.append(date(year, month, day))
    return tuple(dates)


def calculate_schedule(
    principal: float,
    annual_rate_percent: float,
    duration_months: int,
) -> MortgageSchedule:
    """Calculate a fixed-rate, fully amortizing mortgage schedule.

    The annual rate is a nominal percentage divided into monthly periods.
    Balances include the initial balance at month 0, followed by one entry
    for each monthly payment.
    """
    if not math.isfinite(principal) or principal <= 0:
        raise ValueError("Loan principal must be a finite number greater than zero.")
    if not math.isfinite(annual_rate_percent) or annual_rate_percent < 0:
        raise ValueError("Annual rate must be a finite, non-negative number.")
    if isinstance(duration_months, bool) or not isinstance(duration_months, int):
        raise ValueError("Duration must be a whole number of months.")
    if duration_months <= 0:
        raise ValueError("Duration must be greater than zero months.")

    monthly_rate = annual_rate_percent / 1200
    if monthly_rate == 0:
        monthly_payment = principal / duration_months
    else:
        payment_factor = -math.expm1(
            -duration_months * math.log1p(monthly_rate)
        )
        monthly_payment = principal * monthly_rate / payment_factor

    balances = [principal]
    balance = principal
    total_interest = 0.0
    for month in range(1, duration_months + 1):
        interest = balance * monthly_rate
        total_interest += interest
        balance = max(0.0, balance + interest - monthly_payment)
        if month == duration_months:
            balance = 0.0
        balances.append(balance)

    return MortgageSchedule(
        monthly_payment=monthly_payment,
        total_interest=total_interest,
        balances=tuple(balances),
    )
