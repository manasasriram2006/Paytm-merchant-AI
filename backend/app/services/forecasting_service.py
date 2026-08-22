from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .transaction_data_service import TransactionDataService, _round_money


DEFAULT_FORECAST_DAYS = 7
MIN_FORECAST_DAYS = 1
MAX_FORECAST_DAYS = 30
RECENT_WINDOW_DAYS = 14
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

    def forecast(
        self,
        horizon: int = DEFAULT_FORECAST_DAYS,
        category: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        horizon = validate_forecast_days(horizon)
        start, end = validate_date_range(start_date, end_date)

        daily = self._daily_history(category=category, start_date=start, end_date=end)
        if len(daily) < 14:
            return self._insufficient_data(horizon, daily, category)

        revenue_result = self._forecast_series(daily, "revenue", horizon)
        units_result = self._forecast_series(daily, "units", horizon)
        confidence = self._confidence(revenue_result["metrics"], units_result["metrics"])
        forecast_items = []
        for revenue_item, units_item in zip(revenue_result["forecast"], units_result["forecast"], strict=True):
            forecast_date = pd.Timestamp(revenue_item["date"])
            predicted_revenue = _round_money(revenue_item["value"])
            predicted_units = int(round(units_item["value"]))
            forecast_items.append(
                {
                    "date": revenue_item["date"],
                    "day_of_week": forecast_date.day_name(),
                    "predicted_revenue": predicted_revenue,
                    "predicted_units": predicted_units,
                    "revenue": predicted_revenue,
                    "units": predicted_units,
                    "lower_bound": _round_money(revenue_item["lower_bound"]),
                    "upper_bound": _round_money(revenue_item["upper_bound"]),
                    "units_lower_bound": max(0, int(round(units_item["lower_bound"]))),
                    "units_upper_bound": max(0, int(round(units_item["upper_bound"]))),
                    "confidence": confidence,
                }
            )

        method = (
            "ml_regression"
            if revenue_result["method"] == "ml_regression" and units_result["method"] == "ml_regression"
            else "weekly_average_fallback"
        )

        historical_summary = self._historical_summary(daily)
        weekend_insight = self._weekend_insight(daily, forecast_items)
        category_forecast = self._category_forecast(horizon, category, start, end)
        explanation = self._explanation(historical_summary, weekend_insight, forecast_items)

        return {
            "forecast_period": {"days": horizon, "start_date": forecast_items[0]["date"], "end_date": forecast_items[-1]["date"]},
            "historical_summary": historical_summary,
            "daily_forecast": forecast_items,
            "weekend_insight": weekend_insight,
            "category_forecast": category_forecast,
            "product_forecast_available": False,
            "product_forecast_reason": "The current dataset has Brand values but no stable merchant SKU or product_id history for reliable product-level forecasts.",
            "model": method,
            "confidence": confidence,
            "explanation": explanation,
            "forecast_method": method,
            "horizon": horizon,
            "category": category,
            "historical": self._historical_records(daily),
            "forecast": forecast_items,
            "metrics": {
                "revenue": revenue_result["metrics"],
                "units": units_result["metrics"],
            },
            "summary": self._summary(forecast_items),
            "insights": self._insights(forecast_items),
            "model_details": {
                "features": FEATURE_COLUMNS,
                "validation": "chronological holdout using the latest historical period",
                "historical_days": int(len(daily)),
            },
            "note": "Forecast uses representative FMCG retail data and does not represent live Paytm production transactions.",
        }

    def _daily_history(self, category: str | None = None, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        df = self.transaction_data.filtered_dataframe(start_date, end_date)
        self._validate_history_frame(df)
        if category:
            if "Category" not in df.columns:
                raise ValueError("category filtering is unavailable because Category is missing from the dataset")
            category_mask = df["Category"].fillna("").str.casefold() == category.casefold()
            if not category_mask.any():
                raise ValueError(f"category not found: {category}")
            df = df.loc[category_mask].copy()
        if df.empty:
            return pd.DataFrame(columns=["date", "revenue", "units"])
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

    @staticmethod
    def _validate_history_frame(df: pd.DataFrame) -> None:
        if df.empty:
            return
        missing = sorted({"Invoice_Date", "Revenue", "Units"} - set(df.columns))
        if missing:
            raise ValueError(f"forecasting dataset is missing required columns: {missing}")
        if df[["Invoice_Date", "Revenue", "Units"]].isna().any().any():
            raise ValueError("forecasting dataset contains missing date, revenue, or units values")
        if not pd.api.types.is_datetime64_any_dtype(df["Invoice_Date"]):
            parsed_dates = pd.to_datetime(df["Invoice_Date"], errors="coerce")
            if parsed_dates.isna().any():
                raise ValueError("forecasting dataset contains malformed Invoice_Date values")
            df["Invoice_Date"] = parsed_dates
        for column in ["Revenue", "Units"]:
            numeric = pd.to_numeric(df[column], errors="coerce")
            if numeric.isna().any():
                raise ValueError(f"forecasting dataset contains malformed {column} values")
            df[column] = numeric

    def _category_forecast(
        self,
        horizon: int,
        selected_category: str | None,
        start_date: str | None,
        end_date: str | None,
    ) -> list[dict[str, Any]]:
        df = self.transaction_data.filtered_dataframe(start_date, end_date)
        if df.empty or "Category" not in df.columns:
            return []
        if selected_category:
            df = df.loc[df["Category"].fillna("").str.casefold() == selected_category.casefold()].copy()
        if df.empty:
            return []

        records = []
        for category, group in df.groupby("Category"):
            daily = (
                group.set_index("Invoice_Date")
                .resample("D")
                .agg(units=("Units", "sum"))
                .reset_index()
                .sort_values("Invoice_Date")
            )
            if len(daily) < 7:
                continue
            historical_average = float(daily["units"].mean())
            recent_average = float(daily["units"].tail(RECENT_WINDOW_DAYS).mean())
            previous = daily["units"].iloc[-RECENT_WINDOW_DAYS * 2 : -RECENT_WINDOW_DAYS]
            previous_average = float(previous.mean()) if len(previous) else historical_average
            trend_percent = _growth_percent(recent_average, previous_average)
            forecast_daily = max(0.0, recent_average if trend_percent is None else recent_average * (1 + trend_percent / 100))
            records.append(
                {
                    "category": str(category),
                    "historical_average": round(historical_average, 2),
                    "forecast_demand": round(forecast_daily * horizon, 2),
                    "expected_change_percent": trend_percent,
                    "trend": _trend_label(trend_percent),
                }
            )
        return sorted(records, key=lambda item: item["forecast_demand"], reverse=True)

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
    def _historical_summary(daily: pd.DataFrame) -> dict[str, Any]:
        average_revenue = float(daily["revenue"].mean()) if len(daily) else 0.0
        recent_average = float(daily["revenue"].tail(RECENT_WINDOW_DAYS).mean()) if len(daily) else 0.0
        previous = daily["revenue"].iloc[-RECENT_WINDOW_DAYS * 2 : -RECENT_WINDOW_DAYS]
        previous_average = float(previous.mean()) if len(previous) else average_revenue
        return {
            "average_daily_revenue": _round_money(average_revenue),
            "recent_average_daily_revenue": _round_money(recent_average),
            "average_daily_units": round(float(daily["units"].mean()), 2) if len(daily) else 0,
            "recent_average_daily_units": round(float(daily["units"].tail(RECENT_WINDOW_DAYS).mean()), 2) if len(daily) else 0,
            "trend_percent": _growth_percent(recent_average, previous_average),
            "trend": _trend_label(_growth_percent(recent_average, previous_average)),
            "historical_days": int(len(daily)),
        }

    @staticmethod
    def _weekend_insight(daily: pd.DataFrame, forecast: list[dict[str, Any]]) -> dict[str, Any]:
        if not forecast:
            return {"expected_change_percent": None, "direction": "insufficient_data", "message": "Not enough forecast data to compare weekend demand."}
        frame = pd.DataFrame(forecast)
        frame["date"] = pd.to_datetime(frame["date"])
        weekend_forecast = frame[frame["date"].dt.dayofweek.isin([5, 6])]["predicted_revenue"]
        recent_weekday = daily[~daily["date"].dt.dayofweek.isin([5, 6])]["revenue"].tail(RECENT_WINDOW_DAYS)
        if weekend_forecast.empty or recent_weekday.empty:
            return {"expected_change_percent": None, "direction": "insufficient_data", "message": "Not enough weekend or weekday history to compare demand."}
        change = _growth_percent(float(weekend_forecast.mean()), float(recent_weekday.mean()))
        direction = _direction(change)
        return {
            "expected_change_percent": change,
            "direction": direction,
            "message": f"Weekend demand is expected to {direction} compared with the recent weekday average.",
        }

    @staticmethod
    def _confidence(revenue_metrics: dict[str, float | None], units_metrics: dict[str, float | None]) -> float:
        mape_values = [metric.get("mape") for metric in [revenue_metrics, units_metrics] if metric.get("mape") is not None]
        if not mape_values:
            return 0.55
        average_mape = float(np.mean(mape_values))
        return round(float(np.clip(1 - average_mape / 100, 0.35, 0.95)), 2)

    @staticmethod
    def _explanation(historical_summary: dict[str, Any], weekend_insight: dict[str, Any], forecast: list[dict[str, Any]]) -> str:
        trend = historical_summary.get("trend", "stable")
        recent = historical_summary.get("recent_average_daily_revenue", 0)
        expected = _round_money(np.mean([item["predicted_revenue"] for item in forecast])) if forecast else 0
        weekend_direction = weekend_insight.get("direction", "stable")
        return (
            f"Sales show a {trend} recent trend: recent average daily revenue is {recent}, "
            f"and the next forecast window averages {expected} per day. "
            f"Weekend demand is expected to {weekend_direction} versus the recent weekday average."
        )

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
    def _insufficient_data(horizon: int, daily: pd.DataFrame, category: str | None = None) -> dict[str, Any]:
        message = "Not enough historical sales data to generate a reliable forecast."
        return {
            "forecast_period": {"days": horizon},
            "historical_summary": ForecastingService._historical_summary(daily),
            "daily_forecast": [],
            "weekend_insight": {"expected_change_percent": None, "direction": "insufficient_data", "message": message},
            "category_forecast": [],
            "product_forecast_available": False,
            "product_forecast_reason": "Insufficient historical data for product-level forecasting.",
            "model": "insufficient_data",
            "confidence": 0.0,
            "explanation": message,
            "forecast_method": "insufficient_data",
            "horizon": horizon,
            "category": category,
            "historical": ForecastingService._historical_records(daily),
            "forecast": [],
            "metrics": {"revenue": ForecastingService._empty_metrics(), "units": ForecastingService._empty_metrics()},
            "summary": {},
            "insights": [],
            "model_details": {
                "features": FEATURE_COLUMNS,
                "validation": "not enough historical days for chronological validation",
                "historical_days": int(len(daily)),
            },
            "message": message,
        }


def validate_forecast_days(days: int) -> int:
    try:
        parsed = int(days)
    except (TypeError, ValueError) as exc:
        raise ValueError("days must be an integer") from exc
    if parsed < MIN_FORECAST_DAYS or parsed > MAX_FORECAST_DAYS:
        raise ValueError(f"days must be between {MIN_FORECAST_DAYS} and {MAX_FORECAST_DAYS}")
    return parsed


def validate_date_range(start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
    start = _parse_date_filter(start_date, "start_date")
    end = _parse_date_filter(end_date, "end_date")
    if start is not None and end is not None and start > end:
        raise ValueError("start_date must be before or equal to end_date")
    end_of_day = end + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1) if end is not None and end.time() == pd.Timestamp.min.time() else end
    return (
        start.isoformat() if start is not None else None,
        end_of_day.isoformat() if end_of_day is not None else None,
    )


def _parse_date_filter(value: str | None, name: str) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        return pd.to_datetime(value, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid date") from exc


def _growth_percent(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def _trend_label(change_percent: float | None) -> str:
    if change_percent is None:
        return "stable"
    if change_percent > 3:
        return "increase"
    if change_percent < -3:
        return "decrease"
    return "stable"


def _direction(change_percent: float | None) -> str:
    if change_percent is None:
        return "stable"
    if change_percent > 1:
        return "increase"
    if change_percent < -1:
        return "decrease"
    return "remain stable"
