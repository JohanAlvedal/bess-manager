"""Period settings for periods that elapsed before the latest optimization.

A mid-day re-optimization only produces PeriodData from the current period on;
`BatterySystemManager` stores the earlier entries of the full-day
`period_data` list as None ("no data for this period"). The schedule view
(`/api/inverter/schedule`) asks `get_period_settings` for every hour of the day,
so every hour before the re-plan raised
`'NoneType' object has no attribute 'decision'` and the endpoint replaced it
with a hard-coded IDLE row -- the hour that actually ran LOAD_SUPPORT was shown
as IDLE (seen on a Huawei install, 2026-10-24 20:46-22:08).
"""

import pytest

from core.bess.dp_schedule import DPSchedule
from core.bess.huawei_controller import HuaweiController
from core.bess.settings import BatterySettings

PERIODS = 96
REPLAN_PERIOD = 64  # 16:00 -- everything before it elapsed before the re-plan
ELAPSED_LOAD_SUPPORT_PERIOD = 60  # 15:00


@pytest.fixture
def replanned_controller() -> HuaweiController:
    controller = HuaweiController(
        battery_settings=BatterySettings(
            total_capacity=10.0,
            max_charge_power_kw=5.0,
            max_discharge_power_kw=5.0,
            min_soc=5.0,
            max_soc=100.0,
        )
    )
    intents = ["IDLE"] * PERIODS
    intents[ELAPSED_LOAD_SUPPORT_PERIOD] = "LOAD_SUPPORT"
    controller.strategic_intents = intents
    controller.current_schedule = DPSchedule(
        actions=[0.0] * PERIODS,
        state_of_energy=[5.0] * PERIODS,
        prices=[1.0] * PERIODS,
        original_dp_results={
            "strategic_intent": intents,
            "period_data": [None] * PERIODS,
        },
    )
    return controller


def test_elapsed_period_reports_the_intent_that_ran(
    replanned_controller: HuaweiController,
) -> None:
    settings = replanned_controller.get_period_settings(ELAPSED_LOAD_SUPPORT_PERIOD)

    assert settings["strategic_intent"] == "LOAD_SUPPORT"


def test_every_hour_of_the_replanned_day_has_settings(
    replanned_controller: HuaweiController,
) -> None:
    for period in range(REPLAN_PERIOD):
        replanned_controller.get_period_settings(period)
