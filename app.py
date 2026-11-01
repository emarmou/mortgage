"""Browser-based mortgage calculator HMI."""

import colorsys
import datetime
import math
from pathlib import Path
from uuid import uuid4

import plotly.graph_objects as go
import streamlit as st

from mortgage import (
    PartialRepayment,
    SavingsGrowthChange,
    calculate_savings_balance,
    calculate_repayment_schedule,
    calculate_savings_curve,
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

INPUTS_FILE = Path(__file__).resolve().with_name("mortgage_inputs.json")
DEFAULT_INPUTS = MortgageInputs(
    id="mortgage-1",
    name="Mortgage 1",
    principal=250_000.0,
    annual_rate=4.5,
    duration_months=360,
    start_date=datetime.datetime.now().astimezone().date(),
)
DEFAULT_SAVINGS = PersonalSavings(
    current_total=0.0,
    start_date=datetime.datetime.now().astimezone().date(),
    monthly_amount=0.0,
)


def _mortgage_color(color_index: int) -> str:
    hue = (color_index * 0.618033988749895) % 1
    red, green, blue = colorsys.hls_to_rgb(hue, 0.43, 0.72)
    return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def _savings_growth_changes(
    mortgages: tuple[MortgageInputs, ...],
    repayments: tuple[PartialRepayment, ...],
) -> tuple[SavingsGrowthChange, ...]:
    changes = []
    for mortgage in mortgages:
        schedule = calculate_repayment_schedule(
            mortgage.principal,
            mortgage.annual_rate,
            mortgage.duration_months,
            mortgage.start_date,
            (
                repayment
                for repayment in repayments
                if repayment.mortgage_id == mortgage.id
            ),
        )
        dates = schedule_dates(mortgage.start_date, mortgage.duration_months)
        changes.extend(
            SavingsGrowthChange(dates[month_index], monthly_amount_change)
            for month_index, monthly_amount_change
            in schedule.monthly_payment_changes
        )
    return tuple(changes)


st.set_page_config(page_title="Mortgage calculator", page_icon="🏠", layout="wide")
st.title("Mortgage calculator")
st.write(
    "Compare mortgage scenarios by adjusting their terms. Changes are saved "
    "locally and the graph updates immediately."
)

try:
    saved_inputs = load_inputs(INPUTS_FILE, DEFAULT_INPUTS, DEFAULT_SAVINGS)
except UserInputStorageError as error:
    st.error(str(error))
    st.stop()

saved_mortgages = saved_inputs.mortgages
repayments = list(saved_inputs.repayments)
mortgages = []
remove_id = None
for mortgage in saved_mortgages:
    with st.expander(mortgage.name, expanded=True):
        name = st.text_input(
            "Mortgage name",
            value=mortgage.name,
            key=f"{mortgage.id}_name",
        )
        principal_col, rate_col, duration_col, start_date_col = st.columns(4)
        with principal_col:
            principal = st.number_input(
                "Loan principal",
                min_value=0.01,
                value=mortgage.principal,
                step=1_000.0,
                format="%.2f",
                key=f"{mortgage.id}_principal",
                help="The amount borrowed, in your chosen currency.",
            )
        with rate_col:
            annual_rate = st.number_input(
                "Annual interest rate (%)",
                min_value=0.0,
                value=mortgage.annual_rate,
                step=0.1,
                format="%.2f",
                key=f"{mortgage.id}_annual_rate",
                help="A fixed nominal annual rate, converted to a monthly rate.",
            )
        with duration_col:
            duration_months = st.number_input(
                "Duration (months)",
                min_value=1,
                value=mortgage.duration_months,
                step=12,
                format="%d",
                key=f"{mortgage.id}_duration",
            )
        with start_date_col:
            start_date = st.date_input(
                "Starting date (T0)",
                value=mortgage.start_date,
                key=f"{mortgage.id}_start_date",
            )

        if not name.strip():
            st.error("Mortgage name cannot be empty.")
            st.stop()
        mortgages.append(
            MortgageInputs(
                id=mortgage.id,
                name=name.strip(),
                principal=principal,
                annual_rate=annual_rate,
                duration_months=duration_months,
                start_date=start_date,
            )
        )

        metric_col, interest_col, remove_col = st.columns([2, 2, 1])
        try:
            schedule = calculate_repayment_schedule(
                principal,
                annual_rate,
                duration_months,
                start_date,
                (
                    repayment
                    for repayment in repayments
                    if repayment.mortgage_id == mortgage.id
                ),
            )
        except ValueError:
            metric_col.caption("Schedule unavailable until repayments are corrected.")
        else:
            metric_col.metric(
                "First monthly payment", f"{schedule.monthly_payment:,.2f}"
            )
            interest_col.metric("Projected interest", f"{schedule.total_interest:,.2f}")
        if remove_col.button(
            "Remove mortgage",
            key=f"{mortgage.id}_remove",
            disabled=len(saved_mortgages) == 1,
            help="Also removes partial repayments linked to this mortgage.",
        ):
            remove_id = mortgage.id

add_requested = st.button("Add mortgage", type="primary")
if add_requested:
    new_index = len(mortgages) + 1
    mortgages.append(
        MortgageInputs(
            id=uuid4().hex,
            name=f"Mortgage {new_index}",
            principal=DEFAULT_INPUTS.principal,
            annual_rate=DEFAULT_INPUTS.annual_rate,
            duration_months=DEFAULT_INPUTS.duration_months,
            start_date=DEFAULT_INPUTS.start_date,
        )
    )

if remove_id is not None:
    mortgages = [mortgage for mortgage in mortgages if mortgage.id != remove_id]
    repayments = [
        repayment
        for repayment in repayments
        if repayment.mortgage_id != remove_id
    ]

latest_mortgage_end = max(
    schedule_dates(mortgage.start_date, mortgage.duration_months)[-1]
    for mortgage in mortgages
)
st.subheader("Personal savings")
savings_total_col, savings_date_col, savings_monthly_col = st.columns(3)
with savings_total_col:
    current_savings = st.number_input(
        "Current total savings",
        min_value=0.0,
        value=saved_inputs.savings.current_total,
        step=1_000.0,
        format="%.2f",
        key="savings_current_total",
    )
with savings_date_col:
    savings_start_date = st.date_input(
        "Savings starting date",
        value=saved_inputs.savings.start_date,
        key="savings_start_date",
    )
with savings_monthly_col:
    monthly_savings = st.number_input(
        "Monthly saving amount",
        min_value=0.0,
        value=saved_inputs.savings.monthly_amount,
        step=100.0,
        format="%.2f",
        key="savings_monthly_amount",
        help="Added to the current total on each monthly anniversary.",
    )

savings = PersonalSavings(
    current_total=current_savings,
    start_date=savings_start_date,
    monthly_amount=monthly_savings,
)

st.subheader("Partial mortgage repayments")
remove_repayment_id = None
if repayments:
    updated_repayments = []
    for repayment in repayments:
        mortgage = next(
            mortgage
            for mortgage in mortgages
            if mortgage.id == repayment.mortgage_id
        )
        try:
            effective_index = repayment_month_index(
                mortgage.start_date,
                mortgage.duration_months,
                repayment.repayment_date,
            )
        except ValueError:
            effective_date_label = "outside the mortgage term"
            payment_label = "schedule unavailable"
        else:
            effective_date = schedule_dates(
                mortgage.start_date, mortgage.duration_months
            )[effective_index]
            effective_date_label = f"applied {effective_date:%b %d, %Y}"
            try:
                repayment_schedule = calculate_repayment_schedule(
                    mortgage.principal,
                    mortgage.annual_rate,
                    mortgage.duration_months,
                    mortgage.start_date,
                    (
                        saved_repayment
                        for saved_repayment in repayments
                        if saved_repayment.mortgage_id == mortgage.id
                    ),
                )
            except ValueError:
                payment_label = "schedule unavailable"
            else:
                if effective_index < mortgage.duration_months:
                    next_payment = repayment_schedule.monthly_payments[
                        effective_index
                    ]
                    payment_label = f"next payment {next_payment:,.2f}"
                else:
                    payment_label = "no remaining scheduled payments"
        adjustment_label = (
            "Keep monthly payment; shorten term"
            if repayment.adjustment == "keep_payment"
            else "Keep original end date; reduce payment"
        )
        other_personal_repayments = tuple(
            saved_repayment
            for saved_repayment in repayments
            if saved_repayment.id != repayment.id
            and saved_repayment.funding_source == "personal_savings"
        )
        can_use_personal_savings = repayment.funding_source == "personal_savings"
        if not can_use_personal_savings:
            try:
                available_for_repayment = calculate_savings_balance(
                    savings.current_total,
                    savings.monthly_amount,
                    savings.start_date,
                    repayment.repayment_date,
                    other_personal_repayments,
                )
            except ValueError:
                available_for_repayment = 0.0
            can_use_personal_savings = (
                repayment.amount <= available_for_repayment + 1e-8
            )
        funding_options = ("external_fund", "personal_savings")
        if not can_use_personal_savings:
            funding_options = ("external_fund",)
        with st.container(border=True):
            repayment_col, source_col, remove_col = st.columns([5, 2, 1])
            repayment_col.write(
                f"**{mortgage.name}** — {repayment.amount:,.2f} on "
                f"{repayment.repayment_date:%b %d, %Y} "
                f"({effective_date_label}); {adjustment_label}; {payment_label}"
            )
            funding_source = source_col.selectbox(
                "Funding source",
                options=funding_options,
                index=0 if repayment.funding_source == "external_fund" else 1,
                format_func=lambda source: (
                    "Personal savings"
                    if source == "personal_savings"
                    else "External fund"
                ),
                key=f"{repayment.id}_funding_source",
            )
            if funding_source != repayment.funding_source:
                repayment = PartialRepayment(
                    id=repayment.id,
                    mortgage_id=repayment.mortgage_id,
                    repayment_date=repayment.repayment_date,
                    amount=repayment.amount,
                    adjustment=repayment.adjustment,
                    funding_source=funding_source,
                )
            updated_repayments.append(repayment)
            if remove_col.button("Remove", key=f"{repayment.id}_remove"):
                remove_repayment_id = repayment.id
    repayments = [
        repayment
        for repayment in updated_repayments
        if repayment.id != remove_repayment_id
    ]
else:
    st.caption("No partial repayments have been added.")

personal_repayments = tuple(
    repayment
    for repayment in repayments
    if repayment.funding_source == "personal_savings"
)
try:
    growth_changes = _savings_growth_changes(tuple(mortgages), tuple(repayments))
except ValueError as error:
    st.error(f"Cannot calculate savings growth from mortgage repayments: {error}")
    st.stop()
personal_repayments_by_date = {}
for repayment in personal_repayments:
    personal_repayments_by_date.setdefault(repayment.repayment_date, []).append(
        repayment
    )
for repayment_date, date_repayments in personal_repayments_by_date.items():
    earlier_repayments = tuple(
        repayment
        for repayment in personal_repayments
        if repayment.repayment_date < repayment_date
    )
    try:
        available_before = calculate_savings_balance(
            savings.current_total,
            savings.monthly_amount,
            savings.start_date,
            repayment_date,
            earlier_repayments,
            growth_changes,
        )
    except ValueError as error:
        st.error(f"Cannot validate personal savings-funded repayments: {error}")
        continue
    total_debit = sum(repayment.amount for repayment in date_repayments)
    if total_debit > available_before + 1e-8:
        st.error(
            f"Personal savings are insufficient for repayments on "
            f"{repayment_date:%b %d, %Y}: {total_debit:,.2f} due, "
            f"{available_before:,.2f} available. Increase the savings input, "
            "remove a repayment, or change its funding source."
        )

add_repayment_requested = False
if mortgages:
    mortgage_by_id = {mortgage.id: mortgage for mortgage in mortgages}
    mortgage_name_counts = {}
    for mortgage in mortgages:
        mortgage_name_counts[mortgage.name] = (
            mortgage_name_counts.get(mortgage.name, 0) + 1
        )
    mortgage_labels = {
        mortgage.id: (
            mortgage.name
            if mortgage_name_counts[mortgage.name] == 1
            else f"{mortgage.name} ({mortgage.id[:8]})"
        )
        for mortgage in mortgages
    }
    repayment_cols = st.columns(3)
    with repayment_cols[0]:
        target_mortgage_id = st.selectbox(
            "Target mortgage",
            options=list(mortgage_by_id),
            format_func=lambda mortgage_id: mortgage_labels[mortgage_id],
            key="repayment_target",
        )
    with repayment_cols[1]:
        funding_source = st.selectbox(
            "Funding source",
            options=("external_fund", "personal_savings"),
            format_func=lambda source: (
                "Personal savings" if source == "personal_savings" else "External fund"
            ),
            key="repayment_funding_source",
        )
    target_mortgage = mortgage_by_id[target_mortgage_id]
    mortgage_end_date = schedule_dates(
        target_mortgage.start_date, target_mortgage.duration_months
    )[-1]
    today = datetime.datetime.now().astimezone().date()
    default_repayment_date = min(
        max(today, target_mortgage.start_date), mortgage_end_date
    )
    earliest_repayment_date = target_mortgage.start_date
    if funding_source == "personal_savings":
        earliest_repayment_date = max(
            earliest_repayment_date, savings.start_date
        )
    repayment_date_is_valid = earliest_repayment_date <= mortgage_end_date
    if repayment_date_is_valid:
        default_repayment_date = min(
            max(default_repayment_date, earliest_repayment_date),
            mortgage_end_date,
        )
        with repayment_cols[2]:
            repayment_date = st.date_input(
                "Repayment date",
                value=default_repayment_date,
                min_value=earliest_repayment_date,
                max_value=mortgage_end_date,
                key=(
                    f"repayment_date_{target_mortgage.id}_{funding_source}_"
                    f"{target_mortgage.start_date}_{target_mortgage.duration_months}"
                ),
                help="Savings are debited on this date. The mortgage repayment "
                "is applied after the installment on the next scheduled date.",
            )
    else:
        repayment_date = mortgage_end_date
        with repayment_cols[2]:
            st.info(
                "Savings start after this mortgage ends. Choose an external fund."
            )
    target_repayments = tuple(
        repayment
        for repayment in repayments
        if repayment.mortgage_id == target_mortgage.id
    )
    try:
        target_schedule = calculate_repayment_schedule(
            target_mortgage.principal,
            target_mortgage.annual_rate,
            target_mortgage.duration_months,
            target_mortgage.start_date,
            target_repayments,
        )
        repayment_month = repayment_month_index(
            target_mortgage.start_date,
            target_mortgage.duration_months,
            repayment_date,
        )
        remaining_balance = target_schedule.balances[repayment_month]
    except ValueError as error:
        st.error(
            f"{target_mortgage.name} has an invalid repayment schedule: {error} "
            "Remove or re-enter the affected repayment before adding another."
        )
        remaining_balance = 0.0
        target_schedule = None

    savings_available = math.inf
    if funding_source == "personal_savings" and repayment_date_is_valid:
        try:
            savings_available = calculate_savings_balance(
                savings.current_total,
                savings.monthly_amount,
                savings.start_date,
                repayment_date,
                personal_repayments,
                growth_changes,
            )
        except ValueError as error:
            st.error(f"Cannot calculate available personal savings: {error}")
            savings_available = 0.0
    amount_limit = min(remaining_balance, savings_available)
    max_repayment_amount = math.floor((amount_limit + 1e-8) * 100) / 100
    can_add_repayment = (
        repayment_date_is_valid
        and max_repayment_amount >= 0.01
        and target_schedule is not None
    )
    amount_cols = st.columns(2)
    with amount_cols[0]:
        if can_add_repayment:
            repayment_amount = st.number_input(
                "Amount",
                min_value=0.01,
                max_value=max_repayment_amount,
                value=min(1_000.0, max_repayment_amount),
                step=100.0,
                format="%.2f",
                key=(
                    f"repayment_amount_{target_mortgage.id}_{repayment_date}_"
                    f"{max_repayment_amount:.2f}"
                ),
                help=(
                    "Capped by the mortgage balance at its application date "
                    "and the available funding source."
                ),
            )
        else:
            if target_schedule is not None and repayment_date_is_valid:
                if remaining_balance < 0.01:
                    st.info("No remaining mortgage balance is available.")
                elif funding_source == "personal_savings":
                    st.info("No personal savings are available for this repayment.")
            repayment_amount = 0.0
    with amount_cols[1]:
        adjustment = st.selectbox(
            "After repayment",
            options=("keep_payment", "keep_end_date"),
            format_func=lambda choice: (
                "Keep payment; shorten term"
                if choice == "keep_payment"
                else "Keep end date; reduce payment"
            ),
            key="repayment_adjustment",
        )
    if st.button("Add partial repayment", disabled=not can_add_repayment):
        new_repayment = PartialRepayment(
            id=uuid4().hex,
            mortgage_id=target_mortgage.id,
            repayment_date=repayment_date,
            amount=repayment_amount,
            adjustment=adjustment,
            funding_source=funding_source,
        )
        try:
            calculate_repayment_schedule(
                target_mortgage.principal,
                target_mortgage.annual_rate,
                target_mortgage.duration_months,
                target_mortgage.start_date,
                (*target_repayments, new_repayment),
            )
        except ValueError as error:
            st.error(f"Could not add partial repayment: {error}")
        else:
            repayments.append(new_repayment)
            add_repayment_requested = True

try:
    save_inputs(INPUTS_FILE, tuple(mortgages), savings, tuple(repayments))
except UserInputStorageError as error:
    st.error(str(error))
    st.stop()
if (
    add_requested
    or remove_id is not None
    or remove_repayment_id is not None
    or add_repayment_requested
):
    st.rerun()
st.caption("All mortgage inputs are saved locally on this machine.")

projected_schedules = {}
for mortgage in mortgages:
    try:
        projected_schedules[mortgage.id] = calculate_repayment_schedule(
            mortgage.principal,
            mortgage.annual_rate,
            mortgage.duration_months,
            mortgage.start_date,
            (
                repayment
                for repayment in repayments
                if repayment.mortgage_id == mortgage.id
            ),
        )
    except ValueError as error:
        st.error(
            f"Cannot project {mortgage.name}: {error} "
            "Remove or re-enter the affected repayment."
        )
        st.stop()

figure = go.Figure()
balance_curves = []
for scenario_index, mortgage in enumerate(mortgages):
    schedule = projected_schedules[mortgage.id]
    dates = schedule_dates(mortgage.start_date, mortgage.duration_months)
    balance_curves.append((dates, schedule.balances))
    months = list(range(mortgage.duration_months + 1))
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=schedule.balances,
            customdata=months,
            mode="lines",
            name=mortgage.name,
            line={"color": _mortgage_color(scenario_index), "width": 3},
            hovertemplate=(
                "%{x|%b %d, %Y}<br>"
                f"{mortgage.name}<br>"
                "Month %{customdata}<br>"
                "Balance %{y:,.2f}<extra></extra>"
            ),
        )
    )

total_dates, total_balances = sum_balance_curves(balance_curves)
if total_dates:
    figure.add_trace(
        go.Scatter(
            x=total_dates,
            y=total_balances,
            mode="lines",
            name="Total outstanding balance",
            line={"color": "#111827", "width": 7},
            hovertemplate=(
                "%{x|%b %d, %Y}<br>"
                "Total outstanding balance %{y:,.2f}<extra></extra>"
            ),
        )
    )

try:
    savings_dates, savings_balances = calculate_savings_curve(
        savings.current_total,
        savings.monthly_amount,
        savings.start_date,
        latest_mortgage_end,
        repayments,
        growth_changes,
    )
except ValueError as error:
    st.error(f"Cannot calculate the personal savings curve: {error}")
    st.stop()
if savings_dates:
    figure.add_trace(
        go.Scatter(
            x=savings_dates,
            y=savings_balances,
            mode="lines",
            name="Personal savings",
            line={"color": "#16a34a", "width": 3},
            hovertemplate=(
                "%{x|%b %d, %Y}<br>"
                "Personal savings<br>"
                "Balance %{y:,.2f}<extra></extra>"
            ),
        )
    )
else:
    st.info("Savings start after the latest mortgage end date, so no savings curve is shown.")

figure.update_layout(
    title="Outstanding balance by month",
    xaxis_title="Date (month number shown on hover)",
    yaxis_title="Outstanding balance",
    hovermode="x",
    hoverlabel={
        "bgcolor": "#ffffff",
        "bordercolor": "#111827",
        "font": {"color": "#111827"},
    },
    margin={"l": 20, "r": 20, "t": 55, "b": 20},
)
figure.update_xaxes(type="date", dtick="M12", tickformat="%b %Y")
figure.update_yaxes(rangemode="tozero", tickformat=",.2f")
st.markdown(
    """
    <style>
    .hoverlayer .hovertext path {
        fill-opacity: 0.65 !important;
        stroke-opacity: 0.35 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.plotly_chart(figure, width="stretch")
st.caption(
    "Assumes a fixed rate and equal monthly payments, with interest calculated "
    "monthly. Savings increase on monthly anniversaries, including payment "
    "reductions and payments freed after an early payoff. The savings curve "
    "ends at the latest mortgage end date. Fees, taxes, insurance, and payment "
    "rounding are not included."
)
