from __future__ import annotations

from dataclasses import dataclass
from unittest import TestCase, main

import pandas as pd

from app.services.forecasting_service import ForecastingService, validate_date_range, validate_forecast_days


@dataclass(frozen=True)
class StubTransactionData:
    frame: pd.DataFrame

    def dataframe(self) -> pd.DataFrame:
        return self.frame.copy()

    def filtered_dataframe(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        df = self.frame.copy()
        mask = pd.Series(True, index=df.index)
        if start_date:
            start = pd.to_datetime(start_date, errors="raise")
            mask &= df["Invoice_Date"] >= start
        if end_date:
            end = pd.to_datetime(end_date, errors="raise")
            mask &= df["Invoice_Date"] <= end
        return df.loc[mask].copy()


def make_frame(days: int = 35) -> pd.DataFrame:
    rows = []
    for index, date in enumerate(pd.date_range("2024-01-01", periods=days, freq="D")):
        for category, base in [("Dairy", 90), ("Snacks", 55)]:
            weekend_boost = 20 if date.dayofweek in [5, 6] else 0
            trend = index * 1.5
            units = int((base + weekend_boost + trend) / 10)
            revenue = float(base + weekend_boost + trend)
            rows.append(
                {
                    "Invoice_Date": date,
                    "Category": category,
                    "Brand": "Amul" if category == "Dairy" else "Lays",
                    "Units": units,
                    "Revenue": revenue,
                }
            )
    return pd.DataFrame(rows)


class ForecastingServiceTests(TestCase):
    def test_basic_7_day_forecast_schema(self) -> None:
        result = ForecastingService(StubTransactionData(make_frame())).forecast(7)

        self.assertEqual(result["forecast_period"]["days"], 7)
        self.assertEqual(len(result["daily_forecast"]), 7)
        self.assertIn("predicted_revenue", result["daily_forecast"][0])
        self.assertIn("day_of_week", result["daily_forecast"][0])
        self.assertIn("explanation", result)
        self.assertIn("historical_summary", result)
        self.assertIn("weekend_insight", result)
        self.assertIn("category_forecast", result)
        self.assertIn("confidence", result)
        self.assertIn("model", result)

    def test_custom_forecast_horizon(self) -> None:
        result = ForecastingService(StubTransactionData(make_frame())).forecast(10)

        self.assertEqual(result["horizon"], 10)
        self.assertEqual(len(result["forecast"]), 10)

    def test_empty_data_returns_insufficient_data(self) -> None:
        frame = make_frame(0)
        result = ForecastingService(StubTransactionData(frame)).forecast(7)

        self.assertEqual(result["forecast_method"], "insufficient_data")
        self.assertEqual(result["daily_forecast"], [])

    def test_invalid_date_range_raises_clean_value_error(self) -> None:
        service = ForecastingService(StubTransactionData(make_frame()))

        with self.assertRaises(ValueError):
            service.forecast(7, start_date="not-a-date")

        with self.assertRaises(ValueError):
            validate_date_range("2024-02-01", "2024-01-01")

    def test_category_filtering(self) -> None:
        result = ForecastingService(StubTransactionData(make_frame())).forecast(7, category="Dairy")

        self.assertEqual(result["category"], "Dairy")
        self.assertTrue(result["category_forecast"])
        self.assertTrue(all(item["category"] == "Dairy" for item in result["category_forecast"]))

    def test_unknown_category_is_rejected(self) -> None:
        service = ForecastingService(StubTransactionData(make_frame()))

        with self.assertRaises(ValueError):
            service.forecast(7, category="Electronics")

    def test_weekend_insight_is_calculated(self) -> None:
        result = ForecastingService(StubTransactionData(make_frame())).forecast(7)

        self.assertIn(result["weekend_insight"]["direction"], {"increase", "decrease", "remain stable", "stable"})
        self.assertIn("message", result["weekend_insight"])

    def test_trend_calculation(self) -> None:
        result = ForecastingService(StubTransactionData(make_frame())).forecast(7)

        self.assertEqual(result["historical_summary"]["trend"], "increase")
        self.assertGreater(result["historical_summary"]["trend_percent"], 0)

    def test_invalid_days_parameter(self) -> None:
        with self.assertRaises(ValueError):
            validate_forecast_days(0)

    def test_missing_required_columns_raise_clean_error(self) -> None:
        frame = pd.DataFrame(
            {
                "Invoice_Date": pd.date_range("2024-01-01", periods=20, freq="D"),
                "Revenue": [100.0] * 20,
            }
        )
        service = ForecastingService(StubTransactionData(frame))

        with self.assertRaisesRegex(ValueError, "missing required columns"):
            service.forecast(7)


if __name__ == "__main__":
    main()
