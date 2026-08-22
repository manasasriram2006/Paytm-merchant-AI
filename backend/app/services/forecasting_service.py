from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .transaction_data_service import TransactionDataService, _round_money


ALLOWED_HORIZONS = {7, 14, 30}
FEATURE_COLUMNS = [
    "day_of_week",
    "day_of_month",
    "month",
    "is_weekend",
    "lag_1",
    "lag_7",
    "lag_14",
    "rolling_7_mean",
    "rolling_14_mean",
    "rolling_28_mean",
]


class ForecastingError(RuntimeError):
    pass


@dataclass(frozen=True)
class ForecastingService:
    transaction_data: TransactionDataService

    def forecast(self, horizon: int = 7) -> dict[str, Any]:
        if horizon not in ALLOWED_HORIZONS:
            raise ValueError("horizon must be one of: 7, 14, 30")

        daily = self._daily_history()
        if len(daily) < 14:
            return self._insufficient_data(horizon, daily)

        revenue_result = self._forecast_series(daily, "revenue", horizon)
        units_result = self._forecast_series(daily, "units", horizon)
        forecast_items = []
        for revenue_item, units_item in zip(revenue_result["forecast"], units_result["forecast"], strict=True):
            forecast_items.append(
                {
                    "date": revenue_item["date"],
                    "revenue": _round_money(revenue_item["value"]),
                    "units": int(round(units_item["value"])),
                    "lower_bound": _round_money(revenue_item["lower_bound"]),
                    "upper_bound": _round_money(revenue_item["upper_bound"]),
                    "units_lower_bound": max(0, int(round(units_item["lower_bound"]))),
                    "units_upper_bound": max(0, int(round(units_item["upper_bound"]))),
                }
            )

        method = (
            "ml_regression"
            if revenue_result["method"] == "ml_regression" and units_result["method"] == "ml_regression"
            else "weekly_average_fallback"
        )

        return {
            "forecast_method": method,
            "horizon": horizon,
            "historical": self._historical_records(daily),
            "forecast": forecast_items,
            "metrics": {
                "revenue": revenue_result["metrics"],
                "units": units_result["metrics"],
            },
            "summary": self._summary(forecast_items),
            "insights": self._insights(forecast_items),
            "model": {
                "features": FEATURE_COLUMNS,
                "validation": "chronological holdout using the latest historical period",
                "historical_days": int(len(daily)),
            },
            "note": "Forecast uses representative FMCG retail data and does not represent live Paytm production transactions.",
        }

    def _daily_history(self) -> pd.DataFrame:
        df = self.transaction_data.dataframe()
        daily = (
            df.set_index("Invoice_Date")
            .resample("D")
            .agg(revenue=("Revenue", "sum"), units=("Units", "sum"))
            .reset_index()
            .rename(columns={"Invoice_Date": "date"})
            .sort_values("date")
        )
        daily["revenue"] = daily["revenue"].astype(float)
        daily["units"] = daily["units"].astype(float)
        return daily

    def _forecast_series(self, daily: pd.DataFrame, target: str, horizon: int) -> dict[str, Any]:
        prepared = self._feature_frame(daily[["date", target]].rename(columns={target: "target"}))
        feature_rows = prepared.dropna(subset=FEATURE_COLUMNS + ["target"]).copy()
        if len(feature_rows) < 60:
            return self._weekly_average_forecast(daily, target, horizon)

        validation_size = min(30, max(14, int(len(feature_rows) * 0.2)))
        train = feature_rows.iloc[:-validation_size]
        validation = feature_rows.iloc[-validation_size:]
        if train.empty or validation.empty:
            return self._weekly_average_forecast(daily, target, horizon)

        model = RandomForestRegressor(n_estimators=200, min_samples_leaf=2, random_state=42, n_jobs=1)
        model.fit(train[FEATURE_COLUMNS], train["target"])
        validation_predictions = np.maximum(0, model.predict(validation[FEATURE_COLUMNS]))
        metrics = self._metrics(validation["target"].to_numpy(), validation_predictions)
        residual_error = float(np.mean(np.abs(validation["target"].to_numpy() - validation_predictions)))

        final_model = RandomForestRegressor(n_estimators=200, min_samples_leaf=2, random_state=42, n_jobs=1)
        final_model.fit(feature_rows[FEATURE_COLUMNS], feature_rows["target"])

        history = [
            {"date": row.date, "target": float(row.target)}
            for row in daily[["date", target]].rename(columns={target: "target"}).itertuples(index=False)
        ]
        forecast = []
        for _ in range(horizon):
            next_date = history[-1]["date"] + pd.Timedelta(days=1)
            features = self._features_for_date(next_date, [item["target"] for item in history])
            prediction = float(max(0, final_model.predict(pd.DataFrame([features], columns=FEATURE_COLUMNS))[0]))
            history.append({"date": next_date, "target": prediction})
            forecast.append(
                {
                    "date": next_date.date().isoformat(),
                    "value": prediction,
                    "lower_bound": max(0, prediction - residual_error),
                    "upper_bound": prediction + residual_error,
                }
            )

        return {"method": "ml_regression", "forecast": forecast, "metrics": metrics}

    def _weekly_average_forecast(self, daily: pd.DataFrame, target: str, horizon: int) -> dict[str, Any]:
        series = daily[["date", target]].rename(columns={target: "target"}).copy()
        validation_size = min(14, max(1, len(series) // 4))
        train = series.iloc[:-validation_size].copy()
        validation = series.iloc[-validation_size:].copy()
        predictions = []
        for row in validation.itertuples(index=False):
            previous = train[train["date"].dt.dayofweek == row.date.dayofweek]["target"].tail(8)
            value = float(previous.mean()) if not previous.empty else float(train["target"].tail(7).mean())
            predictions.append(max(0, value))
            train = pd.concat([train, pd.DataFrame([{"date": row.date, "target": row.target}])], ignore_index=True)

        metrics = self._metrics(validation["target"].to_numpy(), np.array(predictions)) if len(validation) else self._empty_metrics()
        residual_error = float(np.mean(np.abs(validation["target"].to_numpy() - np.array(predictions)))) if len(validation) else 0.0

        history = series.copy()
        forecast = []
        for _ in range(horizon):
            next_date = history["date"].iloc[-1] + pd.Timedelta(days=1)
            same_day = history[history["date"].dt.dayofweek == next_date.dayofweek]["target"].tail(8)
            value = float(same_day.mean()) if not same_day.empty else float(history["target"].tail(7).mean())
            value = max(0, value)
            history = pd.concat([history, pd.DataFrame([{"date": next_date, "target": value}])], ignore_index=True)
            forecast.append(
                {
                    "date": next_date.date().isoformat(),
                    "value": value,
                    "lower_bound": max(0, value - residual_error),
                    "upper_bound": value + residual_error,
                }
            )

        return {"method": "weekly_average_fallback", "forecast": forecast, "metrics": metrics}

    @staticmethod
    def _feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        result["day_of_week"] = result["date"].dt.dayofweek
        result["day_of_month"] = result["date"].dt.day
        result["month"] = result["date"].dt.month
        result["is_weekend"] = result["day_of_week"].isin([5, 6]).astype(int)
        shifted = result["target"].shift(1)
        result["lag_1"] = result["target"].shift(1)
        result["lag_7"] = result["target"].shift(7)
        result["lag_14"] = result["target"].shift(14)
        result["rolling_7_mean"] = shifted.rolling(7, min_periods=3).mean()
        result["rolling_14_mean"] = shifted.rolling(14, min_periods=7).mean()
        result["rolling_28_mean"] = shifted.rolling(28, min_periods=14).mean()
        return result

    @staticmethod
    def _features_for_date(date: pd.Timestamp, history: list[float]) -> list[float]:
        series = pd.Series(history, dtype=float)
        return [
            int(date.dayofweek),
            int(date.day),
            int(date.month),
            int(date.dayofweek in [5, 6]),
            float(series.iloc[-1]),
            float(series.iloc[-7]) if len(series) >= 7 else float(series.tail(7).mean()),
            float(series.iloc[-14]) if len(series) >= 14 else float(series.tail(14).mean()),
            float(series.tail(7).mean()),
            float(series.tail(14).mean()),
            float(series.tail(28).mean()),
        ]

    @staticmethod
    def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float | None]:
        mae = float(mean_absolute_error(actual, predicted))
        rmse = float(np.sqrt(mean_squared_error(actual, predicted)))
        non_zero_mask = actual != 0
        mape = None
        if np.any(non_zero_mask):
            mape = float(np.mean(np.abs((actual[non_zero_mask] - predicted[non_zero_mask]) / actual[non_zero_mask])) * 100)
        return {
            "mae": _round_money(mae),
            "rmse": _round_money(rmse),
            "mape": round(mape, 2) if mape is not None else None,
        }

    @staticmethod
    def _empty_metrics() -> dict[str, None]:
        return {"mae": None, "rmse": None, "mape": None}

    @staticmethod
    def _historical_records(daily: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                "date": row.date.date().isoformat(),
                "revenue": _round_money(row.revenue),
                "units": int(round(row.units)),
            }
            for row in daily.itertuples(index=False)
        ]

    @staticmethod
    def _summary(forecast: list[dict[str, Any]]) -> dict[str, Any]:
        if not forecast:
            return {}
        expected_revenue = sum(float(item["revenue"]) for item in forecast)
        expected_units = sum(int(item["units"]) for item in forecast)
        highest = max(forecast, key=lambda item: item["revenue"])
        lowest = min(forecast, key=lambda item: item["revenue"])
        return {
            "expected_revenue": _round_money(expected_revenue),
            "expected_units": int(expected_units),
            "average_daily_revenue": _round_money(expected_revenue / len(forecast)),
            "highest_expected_sales_day": highest,
            "lowest_expected_sales_day": lowest,
        }

    @staticmethod
    def _insights(forecast: list[dict[str, Any]]) -> list[str]:
        if not forecast:
            return []
        frame = pd.DataFrame(forecast)
        frame["date"] = pd.to_datetime(frame["date"])
        strongest = frame.loc[frame["revenue"].idxmax()]
        first_half = frame["revenue"].iloc[: max(1, len(frame) // 2)].mean()
        second_half = frame["revenue"].iloc[max(1, len(frame) // 2) :].mean()
        weekend = frame[frame["date"].dt.dayofweek.isin([5, 6])]["revenue"].mean()
        weekday = frame[~frame["date"].dt.dayofweek.isin([5, 6])]["revenue"].mean()

        insights = [
            f"{strongest.date.day_name()} is expected to be the strongest sales day in this forecast window.",
        ]
        if not np.isnan(weekend) and not np.isnan(weekday):
            if weekend > weekday:
                insights.append("Expected sales are higher on weekends than weekdays.")
            else:
                insights.append("Expected sales are higher on weekdays than weekends.")
        if second_half > first_half:
            insights.append("Expected revenue trends upward over the forecast period.")
        elif second_half < first_half:
            insights.append("Expected revenue trends downward over the forecast period.")
        else:
            insights.append("Expected revenue is stable across the forecast period.")
        return insights

    @staticmethod
    def _insufficient_data(horizon: int, daily: pd.DataFrame) -> dict[str, Any]:
        return {
            "forecast_method": "insufficient_data",
            "horizon": horizon,
            "historical": ForecastingService._historical_records(daily),
            "forecast": [],
            "metrics": {"revenue": ForecastingService._empty_metrics(), "units": ForecastingService._empty_metrics()},
            "summary": {},
            "insights": [],
            "model": {
                "features": FEATURE_COLUMNS,
                "validation": "not enough historical days for chronological validation",
                "historical_days": int(len(daily)),
            },
            "message": "Not enough historical sales data to generate a reliable forecast.",
        }
