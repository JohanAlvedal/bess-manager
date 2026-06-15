import { describe, expect, it } from 'vitest';
import { buildConsumptionChartData } from './ConsumptionForecastComparison';
import { ConsumptionForecastComparison, FormattedValue, StrategyForecast } from '../types';

const value = (v: number): FormattedValue => ({
  value: v,
  display: v.toFixed(1),
  unit: 'kWh',
  text: `${v.toFixed(1)} kWh`,
});

describe('buildConsumptionChartData', () => {
  it('preserves numeric values, legitimate zeroes, and missing values', () => {
    const hourlyProfile = Array.from({ length: 24 }, (_, hour) => value(hour === 0 ? 1.25 : 0));
    const actualHourlyProfile = Array.from({ length: 24 }, (_, hour) => (
      hour === 0 ? value(0.75) : hour === 1 ? value(0) : null
    ));
    const strategy: StrategyForecast = {
      name: 'influxdb_7d_avg',
      isActive: true,
      available: true,
      error: null,
      totalKwh: value(1.25),
      hourlyProfile,
      mae: null,
    };
    const comparison: ConsumptionForecastComparison = {
      activeStrategy: 'influxdb_7d_avg',
      strategies: [strategy],
      actualHourlyProfile,
      actualHoursAvailable: 2,
    };

    const chartData = buildConsumptionChartData(comparison, [strategy]);

    expect(chartData[0].actual).toBe(0.75);
    expect(chartData[0].influxdb_7d_avg).toBe(1.25);
    expect(chartData[1].actual).toBe(0);
    expect(chartData[1].influxdb_7d_avg).toBe(0);
    expect(chartData[2].actual).toBeNull();
  });
});
