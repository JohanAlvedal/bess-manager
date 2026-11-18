"""Real-time fuse guard on Huawei LUNA2000.

Huawei has no per-period charge-rate register (its schedule is a TOU period
list), but its "Maximum charging power" number caps charging immediately, in
watts. The fuse guard throttles that cap while the plan grid-charges and
returns it to full power otherwise, so solar charging is never left capped.
"""

from typing import Any

import pytest

from core.bess.huawei_controller import HuaweiController
from core.bess.tests.conftest import MockHomeAssistantController, MockSensorCollector

MAX_CHARGE_KW = 5.0
FULL_POWER_W = 5000


def _huawei_system(
    monkeypatch: pytest.MonkeyPatch,
    arbitrage_prices: Any,
    fuse_protection: bool,
) -> tuple[Any, MockHomeAssistantController]:
    from core.bess.battery_system_manager import BatterySystemManager
    from core.bess.price_manager import MockSource

    monkeypatch.setattr(
        "core.bess.sensor_collector.SensorCollector", MockSensorCollector
    )
    controller = MockHomeAssistantController()
    system = BatterySystemManager(
        controller=controller,
        price_source=MockSource(arbitrage_prices),
        addon_options={"inverter": {"platform": "huawei_solar_luna2000"}},
    )
    system.update_settings({"battery": {"max_charge_power_kw": MAX_CHARGE_KW}})
    system.update_settings(
        {
            "home": {
                "power_monitoring_enabled": fuse_protection,
                "max_fuse_current": 25,
                "voltage": 230,
                "safety_margin": 1.0,
                "phase_count": 3,
            }
        }
    )
    controller.calls["charge_rate"].clear()
    return system, controller


class TestHuaweiFuseGuard:
    def test_huawei_runs_the_realtime_fuse_guard(
        self,
        monkeypatch: pytest.MonkeyPatch,
        arbitrage_prices: Any,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        system, _ = _huawei_system(monkeypatch, arbitrage_prices, fuse_protection=True)

        assert system.realtime_fuse_guard_supported is True
        assert system._power_monitor is not None
        assert "only the day-ahead schedule" not in caplog.text

    def test_overload_while_grid_charging_lowers_the_cap_in_watts(
        self, monkeypatch: pytest.MonkeyPatch, arbitrage_prices: Any
    ) -> None:
        system, controller = _huawei_system(
            monkeypatch, arbitrage_prices, fuse_protection=True
        )
        system._inverter_controller.strategic_intents = ["GRID_CHARGING"] * 96
        controller.settings["charging_power_rate"] = FULL_POWER_W
        # L3 at 27 A = 6210 W against a 5750 W phase limit: 460 W over, which
        # is 27.6% of the battery's 1667 W per-phase share -> 72% of 5 kW.
        controller.settings["l3_current"] = 27.0

        system.adjust_charging_power()

        assert controller.calls["charge_rate"] == [3600]

    def test_outside_grid_charging_the_cap_returns_to_full_power(
        self, monkeypatch: pytest.MonkeyPatch, arbitrage_prices: Any
    ) -> None:
        """A cap left low would throttle solar charging too, and the plan's
        per-period charge rate (0 in a discharge period) must not be written
        to a register that caps all charging."""
        system, controller = _huawei_system(
            monkeypatch, arbitrage_prices, fuse_protection=True
        )
        system._inverter_controller.strategic_intents = ["LOAD_SUPPORT"] * 96
        controller.settings["charging_power_rate"] = 2000

        system.adjust_charging_power()

        assert controller.calls["charge_rate"] == [FULL_POWER_W]

    def test_cap_already_at_full_power_is_not_rewritten(
        self, monkeypatch: pytest.MonkeyPatch, arbitrage_prices: Any
    ) -> None:
        system, controller = _huawei_system(
            monkeypatch, arbitrage_prices, fuse_protection=True
        )
        system._inverter_controller.strategic_intents = ["LOAD_SUPPORT"] * 96
        controller.settings["charging_power_rate"] = FULL_POWER_W

        system.adjust_charging_power()

        assert controller.calls["charge_rate"] == []

    def test_without_fuse_protection_the_cap_is_never_written(
        self, monkeypatch: pytest.MonkeyPatch, arbitrage_prices: Any
    ) -> None:
        system, controller = _huawei_system(
            monkeypatch, arbitrage_prices, fuse_protection=False
        )
        system._inverter_controller.strategic_intents = ["LOAD_SUPPORT"] * 96
        controller.settings["charging_power_rate"] = FULL_POWER_W

        system.adjust_charging_power()

        assert controller.calls["charge_rate"] == []

    def test_disabling_fuse_protection_releases_a_lowered_cap(
        self, monkeypatch: pytest.MonkeyPatch, arbitrage_prices: Any
    ) -> None:
        """The cap is a persistent inverter setting: with the guard gone,
        nothing else would ever raise it again."""
        system, controller = _huawei_system(
            monkeypatch, arbitrage_prices, fuse_protection=True
        )
        controller.settings["charging_power_rate"] = 3600

        system.update_settings({"home": {"power_monitoring_enabled": False}})

        assert system._power_monitor is None
        assert controller.calls["charge_rate"] == [FULL_POWER_W]

    def test_huawei_still_has_no_per_period_charge_rate(self) -> None:
        assert HuaweiController.supports_charge_rate_control is False
