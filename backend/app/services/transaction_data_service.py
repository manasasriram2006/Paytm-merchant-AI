from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {
    "Invoice_ID",
    "Invoice_Date",
    "Revenue",
    "Units",
    "Cost",
    "Margin",
    "Customer_ID",
}

NUMERIC_COLUMNS = [
    "Invoice_ID",
    "Units",
    "Cost_Price",
    "Selling_Price",
    "Revenue",
    "Cost",
    "Margin",
    "Margin_%",
    "Stock_On_Hand",
    "Reorder_Level",
    "Lead_Time_Days",
    "Customer_Age",
    "Loyalty_Flag",
]


class TransactionDataError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _load_clean_data(csv_path: str) -> pd.DataFrame:
    path = Path(csv_path)
    if not path.exists():
        raise TransactionDataError(f"Historical FMCG dataset not found: {path}")

    df = pd.read_csv(path)
    missing_required = sorted(REQUIRED_COLUMNS - set(df.columns))
    if missing_required:
        raise TransactionDataError(f"Historical FMCG dataset is missing required columns: {missing_required}")

    df = df.copy()
    df["Invoice_Date"] = pd.to_datetime(df["Invoice_Date"], errors="coerce")
    if df["Invoice_Date"].isna().any():
        raise TransactionDataError("Invoice_Date contains values that could not be parsed.")

    for column in [column for column in NUMERIC_COLUMNS if column in df.columns]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    required_numeric = [column for column in ["Revenue", "Units", "Cost", "Margin"] if column in df.columns]
    if df[required_numeric].isna().any().any():
        raise TransactionDataError("Required numeric transaction fields contain invalid or missing values.")

    return df


def _round_money(value: float) -> float:
    return round(float(value), 2)


def _growth(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


@dataclass(frozen=True)
class TransactionDataService:
    data_dir: Path

    @property
    def csv_path(self) -> Path:
        return self.data_dir / "fmcg_sales_enriched.csv"

    def dataframe(self) -> pd.DataFrame:
        return _load_clean_data(str(self.csv_path.resolve()))

    def filtered_dataframe(self, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
        df = self.dataframe()
        mask = pd.Series(True, index=df.index)
        if start_date:
            start = pd.to_datetime(start_date, errors="raise")
            mask &= df["Invoice_Date"] >= start
        if end_date:
            end = pd.to_datetime(end_date, errors="raise")
            mask &= df["Invoice_Date"] <= end
        return df.loc[mask].copy()

    def profile(self) -> dict[str, Any]:
        df = self.dataframe()
        important_categories = {}
        for column in ["City", "Store_Format", "Category", "Brand", "Channel", "Payment_Mode", "Customer_Gender", "Loyalty_Flag"]:
            if column in df.columns:
                important_categories[column] = sorted(str(value) for value in df[column].dropna().unique().tolist())

        return {
            "row_count": int(len(df)),
            "column_count": int(len(df.columns)),
            "columns": list(df.columns),
            "dtypes": {column: str(dtype) for column, dtype in df.dtypes.items()},
            "missing_values": {column: int(count) for column, count in df.isna().sum().items()},
            "duplicate_rows": int(df.duplicated().sum()),
            "unique_customer_id_count": int(df["Customer_ID"].nunique(dropna=True)),
            "date_range": {
                "start": df["Invoice_Date"].min().isoformat(),
                "end": df["Invoice_Date"].max().isoformat(),
            },
            "numeric_columns": list(df.select_dtypes(include="number").columns),
            "categorical_columns": list(df.select_dtypes(exclude="number").columns),
            "important_categorical_values": important_categories,
        }

    def summary(self) -> dict[str, Any]:
        df = self.dataframe()
        total_revenue = float(df["Revenue"].sum())
        total_transactions = self._transaction_count(df)
        total_units = int(df["Units"].sum())
        total_cost = float(df["Cost"].sum())
        total_margin = float(df["Margin"].sum())
        monthly = df.assign(month=df["Invoice_Date"].dt.to_period("M")).groupby("month").agg(
            revenue=("Revenue", "sum"),
            transactions=("Invoice_ID", "nunique"),
            units=("Units", "sum"),
        )
        latest, previous = monthly.iloc[-1], monthly.iloc[-2]

        return {
            "total_revenue": _round_money(total_revenue),
            "total_transactions": int(total_transactions),
            "total_units": total_units,
            "average_transaction_value": _round_money(total_revenue / total_transactions) if total_transactions else 0,
            "total_cost": _round_money(total_cost),
            "total_margin": _round_money(total_margin),
            "margin_percentage": round(total_margin / total_revenue * 100, 2) if total_revenue else 0,
            "revenue_growth": _growth(float(latest["revenue"]), float(previous["revenue"])),
            "transaction_growth": _growth(float(latest["transactions"]), float(previous["transactions"])),
            "units_growth": _growth(float(latest["units"]), float(previous["units"])),
            "growth_basis": "latest month compared with previous month",
        }

    def time_series(self, frequency: str, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        df = self.filtered_dataframe(start_date, end_date)
        rule = {"daily": "D", "weekly": "W-MON", "monthly": "MS"}[frequency]
        if df.empty:
            return {"frequency": frequency, "items": []}

        grouped = (
            df.set_index("Invoice_Date")
            .resample(rule)
            .agg(revenue=("Revenue", "sum"), units=("Units", "sum"), transaction_count=("Invoice_ID", "nunique"))
            .reset_index()
        )
        return {
            "frequency": frequency,
            "items": [
                {
                    "date": row.Invoice_Date.date().isoformat(),
                    "revenue": _round_money(row.revenue),
                    "units": int(row.units),
                    "transaction_count": int(row.transaction_count),
                }
                for row in grouped.itertuples()
            ],
        }

    def product_analytics(self) -> dict[str, Any]:
        return {
            "top_brands_by_revenue": self._rank("Brand", "Revenue"),
            "top_brands_by_units": self._rank("Brand", "Units"),
            "average_selling_performance": self._average_selling_performance("Brand"),
        }

    def category_analytics(self) -> dict[str, Any]:
        return {
            "top_categories_by_revenue": self._rank("Category", "Revenue"),
            "top_categories_by_units": self._rank("Category", "Units"),
            "category_margin": self._margin_by("Category"),
        }

    def brand_analytics(self) -> dict[str, Any]:
        return {
            "top_brands_by_revenue": self._rank("Brand", "Revenue"),
            "top_brands_by_units": self._rank("Brand", "Units"),
            "brand_margin": self._margin_by("Brand"),
            "average_selling_performance": self._average_selling_performance("Brand"),
        }

    def payment_analytics(self) -> dict[str, Any]:
        if "Payment_Mode" not in self.dataframe().columns:
            return self._unavailable("Payment_Mode")
        grouped = self._group("Payment_Mode")
        total_transactions = grouped["transaction_count"].sum()
        grouped["transaction_percentage"] = grouped["transaction_count"] / total_transactions * 100 if total_transactions else 0
        return {"payment_methods": self._records(grouped)}

    def business_analytics(self) -> dict[str, Any]:
        response = {}
        for column, key in [("City", "city"), ("Store_Format", "store_format"), ("Channel", "channel")]:
            if column not in self.dataframe().columns:
                response[key] = self._unavailable(column)
                continue
            grouped = self._group(column)
            response[key] = self._records(grouped)
        return response

    def customer_basic_summary(self) -> dict[str, Any]:
        df = self.dataframe()
        required = {"Customer_ID", "Invoice_Date", "Revenue", "Units"}
        if not required.issubset(df.columns):
            return self._unavailable(", ".join(sorted(required - set(df.columns))))
        grouped = df.groupby("Customer_ID").agg(
            transaction_count=("Invoice_ID", "nunique"),
            revenue=("Revenue", "sum"),
            units=("Units", "sum"),
            first_purchase_date=("Invoice_Date", "min"),
            last_purchase_date=("Invoice_Date", "max"),
        )
        active_days = (grouped["last_purchase_date"] - grouped["first_purchase_date"]).dt.days + 1
        grouped["purchase_frequency"] = grouped["transaction_count"] / active_days.clip(lower=1)
        return {
            "note": "Customer_ID values are synthetic representative/demo identifiers, not actual Paytm customer records.",
            "unique_customers": int(grouped.shape[0]),
            "total_customer_revenue": _round_money(grouped["revenue"].sum()),
            "averages": {
                "transactions_per_customer": round(float(grouped["transaction_count"].mean()), 2),
                "revenue_per_customer": _round_money(grouped["revenue"].mean()),
                "units_per_customer": round(float(grouped["units"].mean()), 2),
                "purchase_frequency": round(float(grouped["purchase_frequency"].mean()), 4),
            },
        }

    def inventory_data_summary(self) -> dict[str, Any]:
        df = self.dataframe()
        required = {"Stock_On_Hand", "Reorder_Level"}
        if not required.issubset(df.columns):
            return self._unavailable(", ".join(sorted(required - set(df.columns))))
        below = df[df["Stock_On_Hand"] <= df["Reorder_Level"]]
        return {
            "inventory_records": int(len(df)),
            "items_below_reorder_level": int(len(below)),
            "stock_on_hand": self._stats(df["Stock_On_Hand"]),
            "reorder_level": self._stats(df["Reorder_Level"]),
            "demand_indicators": {
                "total_units": int(df["Units"].sum()) if "Units" in df.columns else None,
                "average_units_per_record": round(float(df["Units"].mean()), 2) if "Units" in df.columns else None,
            },
            "potential_inventory_risk": self._records(
                df.assign(stock_gap=df["Stock_On_Hand"] - df["Reorder_Level"])
                .sort_values("stock_gap")
                .head(10)[[column for column in ["Brand", "Category", "Stock_On_Hand", "Reorder_Level", "Lead_Time_Days", "stock_gap"] if column in df.columns or column == "stock_gap"]]
            ),
        }

    def _rank(self, column: str, metric: str, limit: int = 10) -> list[dict[str, Any]]:
        if column not in self.dataframe().columns:
            return []
        grouped = self.dataframe().groupby(column, as_index=False).agg(value=(metric, "sum")).sort_values("value", ascending=False).head(limit)
        return [{column.lower(): row[0], metric.lower(): _round_money(row.value) if metric == "Revenue" else int(row.value)} for row in grouped.itertuples(index=False)]

    def _margin_by(self, column: str) -> list[dict[str, Any]]:
        grouped = self.dataframe().groupby(column, as_index=False).agg(revenue=("Revenue", "sum"), margin=("Margin", "sum"))
        grouped["margin_percentage"] = grouped["margin"] / grouped["revenue"] * 100
        grouped = grouped.sort_values("margin", ascending=False)
        return self._records(grouped)

    def _average_selling_performance(self, column: str) -> list[dict[str, Any]]:
        grouped = self.dataframe().groupby(column, as_index=False).agg(
            average_selling_price=("Selling_Price", "mean"),
            average_units=("Units", "mean"),
            average_revenue=("Revenue", "mean"),
        )
        return self._records(grouped.sort_values("average_revenue", ascending=False))

    def _group(self, column: str) -> pd.DataFrame:
        return self.dataframe().groupby(column, as_index=False).agg(
            revenue=("Revenue", "sum"),
            units=("Units", "sum"),
            margin=("Margin", "sum"),
            transaction_count=("Invoice_ID", "nunique"),
        ).sort_values("revenue", ascending=False)

    @staticmethod
    def _transaction_count(df: pd.DataFrame) -> int:
        return int(df["Invoice_ID"].nunique()) if "Invoice_ID" in df.columns else int(len(df))

    @staticmethod
    def _stats(series: pd.Series) -> dict[str, float]:
        return {
            "min": _round_money(series.min()),
            "max": _round_money(series.max()),
            "average": _round_money(series.mean()),
            "median": _round_money(series.median()),
        }

    @staticmethod
    def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
        return [
            {
                key: (
                    value.isoformat()
                    if hasattr(value, "isoformat")
                    else _round_money(value)
                    if isinstance(value, float)
                    else int(value)
                    if hasattr(value, "item") and isinstance(value.item(), int)
                    else value.item()
                    if hasattr(value, "item")
                    else value
                )
                for key, value in row.items()
            }
            for row in df.to_dict(orient="records")
        ]

    @staticmethod
    def _unavailable(column: str) -> dict[str, str]:
        return {"status": "unavailable", "reason": f"Column not present in dataset: {column}"}
