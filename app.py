"""Browser-based mortgage calculator HMI."""

import colorsys
import datetime
from pathlib import Path
from uuid import uuid4

import plotly.graph_objects as go
import streamlit as st

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
        schedule = calculate_schedule(principal, annual_rate, duration_months)
        metric_col.metric("Monthly payment", f"{schedule.monthly_payment:,.2f}")
        interest_col.metric("Total interest", f"{schedule.total_interest:,.2f}")
        if remove_col.button(
            "Remove mortgage",
            key=f"{mortgage.id}_remove",
            disabled=len(saved_mortgages) == 1,
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
try:
    save_inputs(INPUTS_FILE, tuple(mortgages), savings)
except UserInputStorageError as error:
    st.error(str(error))
    st.stop()
if add_requested or remove_id is not None:
    st.rerun()
st.caption("All mortgage inputs are saved locally on this machine.")

figure = go.Figure()
balance_curves = []
for scenario_index, mortgage in enumerate(mortgages):
    schedule = calculate_schedule(
        mortgage.principal,
        mortgage.annual_rate,
        mortgage.duration_months,
    )
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

savings_dates, savings_balances = calculate_savings_curve(
    savings.current_total,
    savings.monthly_amount,
    savings.start_date,
    latest_mortgage_end,
)
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
st.plotly_chart(figure, use_container_width=True)
st.caption(
    "Assumes a fixed rate and equal monthly payments, with interest calculated "
    "monthly. Savings start at the current total and increase on monthly "
    "anniversaries. The savings curve ends at the latest mortgage end date. "
    "Fees, taxes, insurance, and payment rounding are not included."
)
