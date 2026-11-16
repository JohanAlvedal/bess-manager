"""Energy-balance identities shared by the sensor and flow layers.

House load is not measured on every platform (SolaX native, Solis and Huawei
have no load register), so it has to be derived from the counters that every
platform does provide. That derivation was duplicated — once over lifetime
totals in ``ha_api_controller`` and once over period deltas in
``energy_flow_calculator`` — and the two copies drifted: the lifetime copy
omitted the battery terms entirely and reported load plus net battery charge
(issue #528). One definition, two callers, so they cannot drift again.
"""


def derive_load_consumption(
    *,
    solar_production: float,
    import_from_grid: float,
    export_to_grid: float,
    battery_charged: float,
    battery_discharged: float,
) -> float:
    """Derive house load consumption from the five core energy counters.

    Decomposing into the seven physical flows::

        solar       = solar_to_home + solar_to_battery + solar_to_grid
        import      = grid_to_home  + grid_to_battery
        export      = solar_to_grid + battery_to_grid
        charged     = solar_to_battery + grid_to_battery
        discharged  = battery_to_home + battery_to_grid

    gives ``load = solar_to_home + battery_to_home + grid_to_home``, which
    reduces to the balance below. Dropping the battery terms yields
    ``load + (charged - discharged)`` — the issue #528 defect.

    The result is returned unclamped: over a consistent set of counters it is
    physically non-negative, so a negative value means the inputs disagree and
    must stay visible rather than being laundered into a plausible zero (per
    ``docs/agents/rules.md`` — no silent fallbacks). Callers working with
    per-period deltas, where sensor noise can legitimately produce a small
    negative, clamp it themselves.

    Args:
        solar_production: Solar energy produced, kWh.
        import_from_grid: Energy imported from the grid, kWh.
        export_to_grid: Energy exported to the grid, kWh.
        battery_charged: Energy charged into the battery, kWh.
        battery_discharged: Energy discharged from the battery, kWh.

    Returns:
        House load consumption in kWh.
    """
    return (
        solar_production
        + import_from_grid
        + battery_discharged
        - battery_charged
        - export_to_grid
    )


# The five lifetime counters derive_load_consumption needs, keyed by the
# sensor key each is mapped under. Every platform requires all five, which is
# what lets the lifetime reading and the recorder history both fall back to
# the balance when no load sensor is mapped.
LOAD_BALANCE_COUNTERS: dict[str, str] = {
    "lifetime_solar_energy": "solar_production",
    "lifetime_import_from_grid": "import_from_grid",
    "lifetime_export_to_grid": "export_to_grid",
    "lifetime_battery_charged": "battery_charged",
    "lifetime_battery_discharged": "battery_discharged",
}


def derive_load_consumption_stats(
    counter_stats: dict[str, list[dict]],
) -> tuple[list[dict], int, int]:
    """Derive hourly house-load statistics from the counters' recorder stats.

    Args:
        counter_stats: HA Recorder ``{"start", "change"}`` entries per
            counter, keyed by sensor key (every key of
            ``LOAD_BALANCE_COUNTERS``). All lists come from the same query
            window, so equal ``start`` values denote the same hour.

    Returns:
        ``(stats, incomplete_hours, clamped_hours)``. ``stats`` holds one
        ``{"start", "change"}`` entry per hour that every counter reported.
        An hour missing from any counter is left out and counted in
        ``incomplete_hours``: deriving it from the rest would drop a whole
        term of the balance. A negative hourly balance is floored at 0.0 and
        counted in ``clamped_hours`` — counters that update at different
        moments can shift a little energy across an hour boundary, and a
        negative load would corrupt the profile.
    """
    changes_by_counter = {
        key: {entry["start"]: entry["change"] for entry in counter_stats[key]}
        for key in LOAD_BALANCE_COUNTERS
    }
    all_starts: list = []
    seen: set = set()
    for key in LOAD_BALANCE_COUNTERS:
        for entry in counter_stats[key]:
            if entry["start"] not in seen:
                seen.add(entry["start"])
                all_starts.append(entry["start"])

    stats: list[dict] = []
    incomplete_hours = 0
    clamped_hours = 0
    for start in all_starts:
        changes: dict[str, float] = {}
        for key, arg in LOAD_BALANCE_COUNTERS.items():
            change = changes_by_counter[key].get(start)
            if change is not None:
                changes[arg] = change
        if len(changes) < len(LOAD_BALANCE_COUNTERS):
            incomplete_hours += 1
            continue
        load = derive_load_consumption(**changes)
        if load < 0:
            clamped_hours += 1
            load = 0.0
        stats.append({"start": start, "change": load})
    return stats, incomplete_hours, clamped_hours
