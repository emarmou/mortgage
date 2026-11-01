"""Mortgage amortization calculations."""

from bisect import bisect_left, bisect_right
from calendar import monthrange
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
import math
from typing import Literal


FundingSource = Literal["personal_savings", "external_fund"]


@dataclass(frozen=True)
class PartialRepayment:
    id: str
    mortgage_id: str
    repayment_date: date
    amount: float
    adjustment: str
    funding_source: FundingSource = "external_fund"


@dataclass(frozen=True)
class SavingsGrowthChange:
    effective_date: date
    monthly_amount_change: float


@dataclass(frozen=True)
class MortgageSchedule:
    monthly_payment: float
    total_interest: float
    balances: tuple[float, ...]
    monthly_payments: tuple[float, ...] = ()
    monthly_payment_changes: tuple[tuple[int, float], ...] = ()


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
    repayments: Iterable[PartialRepayment] = (),
    growth_changes: Iterable[SavingsGrowthChange] = (),
) -> tuple[tuple[date, ...], tuple[float, ...]]:
    """Calculate savings after contributions and personal-funded repayments."""
    repayments = tuple(repayments)
    growth_changes = _validate_growth_changes(growth_changes)
    _validate_savings(current_savings, monthly_savings)
    for repayment in repayments:
        _validate_funding_source(repayment.funding_source)
        if (
            repayment.funding_source == "personal_savings"
            and repayment.repayment_date < start_date
        ):
            raise ValueError(
                "A personal-savings repayment cannot predate the savings start date."
            )
    if end_date < start_date:
        return (), ()

    month_span = (end_date.year - start_date.year) * 12 + end_date.month - start_date.month
    anniversaries = schedule_dates(start_date, month_span) if month_span else (start_date,)
    dates = {
        start_date,
        end_date,
        *(anniversary for anniversary in anniversaries if anniversary <= end_date),
        *(
            repayment.repayment_date
            for repayment in repayments
            if repayment.funding_source == "personal_savings"
            and repayment.repayment_date <= end_date
        ),
        *(
            change.effective_date
            for change in growth_changes
            if start_date <= change.effective_date <= end_date
        ),
    }
    sorted_dates = tuple(sorted(dates))
    balances = tuple(
        calculate_savings_balance(
            current_savings,
            monthly_savings,
            start_date,
            curve_date,
            repayments,
            growth_changes,
        )
        for curve_date in sorted_dates
    )
    return sorted_dates, balances


def calculate_savings_balance(
    current_savings: float,
    monthly_savings: float,
    start_date: date,
    balance_date: date,
    repayments: Iterable[PartialRepayment] = (),
    growth_changes: Iterable[SavingsGrowthChange] = (),
) -> float:
    """Return savings after contributions and personal repayments by a date."""
    _validate_savings(current_savings, monthly_savings)
    if balance_date < start_date:
        raise ValueError("Balance date cannot predate the savings start date.")

    repayments = tuple(repayments)
    growth_changes = _validate_growth_changes(growth_changes)
    month_span = (balance_date.year - start_date.year) * 12 + balance_date.month - start_date.month
    anniversaries = schedule_dates(start_date, max(1, month_span))
    elapsed_months = bisect_right(anniversaries, balance_date) - 1
    balance = current_savings
    for anniversary in anniversaries[1 : elapsed_months + 1]:
        monthly_growth = monthly_savings + sum(
            change.monthly_amount_change
            for change in growth_changes
            if change.effective_date <= anniversary
        )
        balance += monthly_growth

    for repayment in repayments:
        _validate_funding_source(repayment.funding_source)
        if repayment.funding_source != "personal_savings":
            continue
        if repayment.repayment_date < start_date:
            raise ValueError(
                "A personal-savings repayment cannot predate the savings start date."
            )
        if repayment.repayment_date <= balance_date:
            if not math.isfinite(repayment.amount) or repayment.amount <= 0:
                raise ValueError(
                    "Repayment amount must be a finite number greater than zero."
                )
            balance -= repayment.amount
    return balance


def _validate_savings(current_savings: float, monthly_savings: float) -> None:
    if not math.isfinite(current_savings) or current_savings < 0:
        raise ValueError("Current savings must be a finite, non-negative number.")
    if not math.isfinite(monthly_savings) or monthly_savings < 0:
        raise ValueError("Monthly savings must be a finite, non-negative number.")


def _validate_funding_source(funding_source: str) -> None:
    if funding_source not in ("personal_savings", "external_fund"):
        raise ValueError("Repayment funding source must be personal_savings or external_fund.")


def _validate_growth_changes(
    growth_changes: Iterable[SavingsGrowthChange],
) -> tuple[SavingsGrowthChange, ...]:
    changes = tuple(growth_changes)
    for change in changes:
        if (
            not math.isfinite(change.monthly_amount_change)
            or change.monthly_amount_change < 0
        ):
            raise ValueError(
                "Savings growth changes must be finite, non-negative amounts."
            )
    return changes


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
    monthly_payment = _monthly_payment(principal, monthly_rate, duration_months)

    balances = [principal]
    balance = principal
    total_interest = 0.0
    monthly_payments = []
    for month in range(1, duration_months + 1):
        interest = balance * monthly_rate
        total_interest += interest
        amount_due = balance + interest
        payment = min(monthly_payment, amount_due)
        balance = max(0.0, amount_due - payment)
        if month == duration_months:
            balance = 0.0
        balances.append(balance)
        monthly_payments.append(payment)

    return MortgageSchedule(
        monthly_payment=monthly_payment,
        total_interest=total_interest,
        balances=tuple(balances),
        monthly_payments=tuple(monthly_payments),
    )


def repayment_month_index(
    start_date: date,
    duration_months: int,
    repayment_date: date,
) -> int:
    """Return the next scheduled payment index on or after a repayment date."""
    dates = schedule_dates(start_date, duration_months)
    if repayment_date < start_date or repayment_date > dates[-1]:
        raise ValueError("Repayment date must be within the mortgage term.")
    return bisect_left(dates[1:], repayment_date) + 1


def calculate_repayment_schedule(
    principal: float,
    annual_rate_percent: float,
    duration_months: int,
    start_date: date,
    repayments: Iterable[PartialRepayment],
) -> MortgageSchedule:
    """Calculate a mortgage schedule including partial repayments.

    Repayments are applied after the regular installment on the next scheduled
    payment date on or after their entered date. Each repayment can either
    preserve the current monthly payment or recalculate it to the original
    maturity date.
    """
    initial_schedule = calculate_schedule(
        principal, annual_rate_percent, duration_months
    )
    monthly_rate = annual_rate_percent / 1200
    repayments_by_month: dict[int, list[PartialRepayment]] = {}
    for repayment in repayments:
        if not math.isfinite(repayment.amount) or repayment.amount <= 0:
            raise ValueError("Repayment amount must be a finite number greater than zero.")
        if repayment.adjustment not in ("keep_payment", "keep_end_date"):
            raise ValueError("Repayment adjustment must be keep_payment or keep_end_date.")
        month_index = repayment_month_index(
            start_date, duration_months, repayment.repayment_date
        )
        repayments_by_month.setdefault(month_index, []).append(repayment)
    for month_repayments in repayments_by_month.values():
        month_repayments.sort(
            key=lambda repayment: (repayment.repayment_date, repayment.id)
        )

    monthly_payment = initial_schedule.monthly_payment
    balance = principal
    total_interest = 0.0
    balances = [balance]
    monthly_payments = []
    monthly_payment_changes = []
    shorten_term_selected = False
    payoff_growth_recorded = False

    first_monthly_payment = monthly_payment

    for month_index in range(1, duration_months + 1):
        interest = balance * monthly_rate
        total_interest += interest
        amount_due = balance + interest
        payment = min(monthly_payment, amount_due)
        balance = max(0.0, amount_due - payment)
        if month_index == duration_months:
            balance = 0.0

        for repayment in repayments_by_month.get(month_index, ()):
            balance = _apply_repayment(balance, repayment)
            shorten_term_selected |= repayment.adjustment == "keep_payment"
            if repayment.adjustment == "keep_end_date":
                remaining_months = duration_months - month_index
                previous_monthly_payment = monthly_payment
                monthly_payment = _monthly_payment(
                    balance, monthly_rate, remaining_months
                )
                payment_reduction = previous_monthly_payment - monthly_payment
                if payment_reduction > 0 and remaining_months > 0:
                    monthly_payment_changes.append(
                        (month_index + 1, payment_reduction)
                    )
        if (
            balance <= 1e-8
            and month_index < duration_months
            and shorten_term_selected
            and not payoff_growth_recorded
        ):
            monthly_payment_changes.append((month_index + 1, monthly_payment))
            payoff_growth_recorded = True
        balances.append(balance)
        monthly_payments.append(payment)

    return MortgageSchedule(
        monthly_payment=first_monthly_payment,
        total_interest=total_interest,
        balances=tuple(balances),
        monthly_payments=tuple(monthly_payments),
        monthly_payment_changes=tuple(monthly_payment_changes),
    )


def _apply_repayment(balance: float, repayment: PartialRepayment) -> float:
    if repayment.amount > balance + 1e-8:
        raise ValueError(
            f"Repayment {repayment.id} exceeds the remaining mortgage balance "
            f"({balance:.2f})."
        )
    return max(0.0, balance - repayment.amount)


def _monthly_payment(
    principal: float,
    monthly_rate: float,
    duration_months: int,
) -> float:
    if principal <= 0 or duration_months <= 0:
        return 0.0
    if monthly_rate == 0:
        return principal / duration_months
    payment_factor = -math.expm1(
        -duration_months * math.log1p(monthly_rate)
    )
    return principal * monthly_rate / payment_factor
