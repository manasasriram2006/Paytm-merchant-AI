from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .transaction_data_service import TransactionDataService, _round_money


SEGMENT_ORDER = [
    "Champions",
    "Loyal Customers",
    "Potential Loyalists",
    "New Customers",
    "At Risk",
    "Needs Attention",
    "Low Value",
]


@dataclass(frozen=True)
class CustomerIntelligenceService:
    transaction_data: TransactionDataService

    def summary(self) -> dict[str, Any]:
        customers = self._customer_frame()
        total_customers = int(len(customers))
        repeat_customers = int((customers["transaction_count"] > 1).sum())
        active_customers = int(customers["is_active"].sum())
        at_risk_customers = int(customers["segment"].isin(["At Risk", "Needs Attention"]).sum())

        return {
            "total_customers": total_customers,
            "active_customers": active_customers,
            "repeat_customers": repeat_customers,
            "average_customer_value": _round_money(customers["total_revenue"].mean()) if total_customers else 0,
            "at_risk_customers": at_risk_customers,
            "repeat_customer_rate": round(repeat_customers / total_customers * 100, 2) if total_customers else 0,
            "definitions": self._definitions(customers),
            "note": "Customer_ID values are synthetic representative/demo identifiers, not actual Paytm customer records.",
        }

    def segments(self) -> list[dict[str, Any]]:
        customers = self._customer_frame()
        if customers.empty:
            return []
        grouped = customers.groupby("segment", as_index=False).agg(
            customer_count=("customer_id", "count"),
            total_revenue=("total_revenue", "sum"),
            average_revenue=("total_revenue", "mean"),
        )
        grouped["percentage"] = grouped["customer_count"] / len(customers) * 100
        grouped["sort_order"] = grouped["segment"].apply(lambda value: SEGMENT_ORDER.index(value) if value in SEGMENT_ORDER else 99)
        grouped = grouped.sort_values("sort_order")
        return [
            {
                "segment": row.segment,
                "customer_count": int(row.customer_count),
                "percentage": round(float(row.percentage), 2),
                "total_revenue": _round_money(row.total_revenue),
                "average_revenue": _round_money(row.average_revenue),
            }
            for row in grouped.itertuples(index=False)
        ]

    def top_customers(self, limit: int = 10) -> list[dict[str, Any]]:
        customers = self._customer_frame().sort_values("total_revenue", ascending=False).head(self._limit(limit))
        return [self._customer_record(row) for row in customers.itertuples(index=False)]

    def at_risk(self, limit: int = 10) -> dict[str, Any]:
        customers = self._customer_frame()
        rows = (
            customers[customers["segment"].isin(["At Risk", "Needs Attention"])]
            .sort_values(["rfm_score", "total_revenue"], ascending=[True, False])
            .head(self._limit(limit))
        )
        return {
            "explanation": "These customers have shown previous purchasing activity but have become less active recently.",
            "items": [self._customer_record(row) for row in rows.itertuples(index=False)],
        }

    def demographics(self) -> dict[str, Any]:
        customers = self._customer_frame()
        response: dict[str, Any] = {}
        if "customer_gender" in customers.columns:
            gender = customers["customer_gender"].dropna()
            response["gender_distribution"] = self._distribution(gender)
        else:
            response["gender_distribution"] = self._unavailable("Customer_Gender")

        if "customer_age" in customers.columns:
            age = customers["customer_age"].dropna()
            if age.empty:
                response["age_distribution"] = []
            else:
                bins = [0, 24, 34, 44, 54, 64, 200]
                labels = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
                age_groups = pd.cut(age, bins=bins, labels=labels, right=True)
                response["age_distribution"] = self._distribution(age_groups.dropna())
        else:
            response["age_distribution"] = self._unavailable("Customer_Age")
        return response

    def loyalty(self) -> dict[str, Any]:
        customers = self._customer_frame()
        if "loyalty_flag" not in customers.columns:
            return self._unavailable("Loyalty_Flag")

        grouped = customers.groupby("loyalty_flag", as_index=False).agg(
            customer_count=("customer_id", "count"),
            total_revenue=("total_revenue", "sum"),
            total_transactions=("transaction_count", "sum"),
        )
        items = []
        for row in grouped.itertuples(index=False):
            label = "Loyalty Flag" if int(row.loyalty_flag) == 1 else "No Loyalty Flag"
            items.append(
                {
                    "loyalty_status": label,
                    "customer_count": int(row.customer_count),
                    "total_revenue": _round_money(row.total_revenue),
                    "average_transaction_value": _round_money(row.total_revenue / row.total_transactions) if row.total_transactions else 0,
                }
            )
        return {
            "items": items,
            "note": "Loyalty_Flag is treated only as a field in the representative dataset, not as an official Paytm loyalty program.",
        }

    def insights(self) -> list[dict[str, Any]]:
        customers = self._customer_frame()
        segments = self.segments()
        summary = self.summary()
        at_risk_count = summary["at_risk_customers"]
        insights = [
            {
                "type": "repeat_rate",
                "message": f"{summary['repeat_customer_rate']}% of customers have made more than one purchase.",
                "value": summary["repeat_customer_rate"],
            },
            {
                "type": "attention",
                "message": f"{at_risk_count} customers have become less active recently.",
                "value": at_risk_count,
            },
        ]
        if segments:
            highest_value = max(segments, key=lambda item: item["total_revenue"])
            revenue_share = highest_value["total_revenue"] / customers["total_revenue"].sum() * 100 if customers["total_revenue"].sum() else 0
            insights.append(
                {
                    "type": "segment_value",
                    "message": f"{highest_value['segment']} contribute {round(revenue_share, 2)}% of customer revenue.",
                    "value": round(revenue_share, 2),
                }
            )
        champions = next((item for item in segments if item["segment"] == "Champions"), None)
        if champions:
            insights.append(
                {
                    "type": "champions",
                    "message": f"Champions generate Rs {champions['total_revenue']:,.2f} in total revenue.",
                    "value": champions["total_revenue"],
                }
            )
        return insights

    def value_summary(self) -> dict[str, Any]:
        customers = self._customer_frame()
        return {
            "total_customer_revenue": _round_money(customers["total_revenue"].sum()),
            "average_revenue_per_customer": _round_money(customers["total_revenue"].mean()),
            "median_revenue_per_customer": _round_money(customers["total_revenue"].median()),
            "average_transactions_per_customer": round(float(customers["transaction_count"].mean()), 2),
            "average_units_per_customer": round(float(customers["total_units"].mean()), 2),
        }

    def _customer_frame(self) -> pd.DataFrame:
        df = self.transaction_data.dataframe()
        grouped = df.groupby("Customer_ID").agg(
            transaction_count=("Invoice_ID", "nunique"),
            total_revenue=("Revenue", "sum"),
            total_units=("Units", "sum"),
            first_purchase_date=("Invoice_Date", "min"),
            last_purchase_date=("Invoice_Date", "max"),
        )
        latest_date = df["Invoice_Date"].max().normalize()
        earliest_date = df["Invoice_Date"].min().normalize()
        history_days = max(1, int((latest_date - earliest_date).days) + 1)
        recent_window_days = max(30, min(60, round(history_days * 0.15)))
        at_risk_days = recent_window_days

        customers = grouped.reset_index().rename(columns={"Customer_ID": "customer_id"})
        customers["recency_days"] = (latest_date - customers["last_purchase_date"].dt.normalize()).dt.days
        active_span = (customers["last_purchase_date"] - customers["first_purchase_date"]).dt.days.clip(lower=1)
        customers["average_days_between_purchases"] = active_span / customers["transaction_count"].sub(1).clip(lower=1)
        customers["is_active"] = customers["recency_days"] <= recent_window_days

        if "Customer_Age" in df.columns:
            customers = customers.merge(df.groupby("Customer_ID")["Customer_Age"].mean().reset_index().rename(columns={"Customer_ID": "customer_id", "Customer_Age": "customer_age"}), on="customer_id", how="left")
        if "Customer_Gender" in df.columns:
            gender = df.dropna(subset=["Customer_Gender"]).groupby("Customer_ID")["Customer_Gender"].agg(lambda values: values.mode().iloc[0] if not values.mode().empty else values.iloc[0])
            customers = customers.merge(gender.reset_index().rename(columns={"Customer_ID": "customer_id", "Customer_Gender": "customer_gender"}), on="customer_id", how="left")
        if "Loyalty_Flag" in df.columns:
            loyalty = df.groupby("Customer_ID")["Loyalty_Flag"].max().reset_index().rename(columns={"Customer_ID": "customer_id", "Loyalty_Flag": "loyalty_flag"})
            customers = customers.merge(loyalty, on="customer_id", how="left")

        customers["recency_score"] = self._score(customers["recency_days"], higher_is_better=False)
        customers["frequency_score"] = self._score(customers["transaction_count"], higher_is_better=True)
        customers["monetary_score"] = self._score(customers["total_revenue"], higher_is_better=True)
        customers["rfm_score"] = customers["recency_score"] + customers["frequency_score"] + customers["monetary_score"]
        customers["segment"] = customers.apply(lambda row: self._segment(row, at_risk_days), axis=1)
        customers.attrs["latest_date"] = latest_date
        customers.attrs["earliest_date"] = earliest_date
        customers.attrs["recent_window_days"] = recent_window_days
        customers.attrs["at_risk_days"] = at_risk_days
        return customers

    @staticmethod
    def _score(series: pd.Series, higher_is_better: bool) -> pd.Series:
        unique_count = int(series.nunique(dropna=True))
        bins = min(5, unique_count)
        if bins <= 1:
            return pd.Series([3] * len(series), index=series.index)
        ranked = series.rank(method="first", ascending=not higher_is_better)
        scores = pd.qcut(ranked, q=bins, labels=False, duplicates="drop") + 1
        max_score = int(scores.max())
        if max_score < 5:
            scores = ((scores - 1) / max(1, max_score - 1) * 4 + 1).round()
        return scores.astype(int)

    @staticmethod
    def _segment(row: pd.Series, at_risk_days: int) -> str:
        recency = int(row.recency_score)
        frequency = int(row.frequency_score)
        monetary = int(row.monetary_score)
        transactions = int(row.transaction_count)
        inactive = int(row.recency_days) > at_risk_days

        if recency >= 4 and frequency >= 4 and monetary >= 4:
            return "Champions"
        if frequency >= 4 and monetary >= 3 and recency >= 3:
            return "Loyal Customers"
        if recency >= 4 and transactions <= 2:
            return "New Customers"
        if recency >= 4 and frequency >= 2:
            return "Potential Loyalists"
        if inactive and (frequency >= 4 or monetary >= 4):
            return "At Risk"
        if inactive:
            return "Needs Attention"
        if frequency <= 2 and monetary <= 2:
            return "Low Value"
        return "Potential Loyalists"

    @staticmethod
    def _customer_record(row: Any) -> dict[str, Any]:
        return {
            "customer_id": row.customer_id,
            "total_revenue": _round_money(row.total_revenue),
            "transaction_count": int(row.transaction_count),
            "total_units": int(row.total_units),
            "first_purchase_date": row.first_purchase_date.date().isoformat(),
            "last_purchase_date": row.last_purchase_date.date().isoformat(),
            "days_since_purchase": int(row.recency_days),
            "segment": row.segment,
        }

    @staticmethod
    def _distribution(series: pd.Series) -> list[dict[str, Any]]:
        counts = series.astype(str).value_counts(dropna=True)
        total = int(counts.sum())
        return [
            {"label": label, "count": int(count), "percentage": round(count / total * 100, 2) if total else 0}
            for label, count in counts.items()
        ]

    @staticmethod
    def _definitions(customers: pd.DataFrame) -> dict[str, Any]:
        return {
            "reference_date": customers.attrs["latest_date"].date().isoformat(),
            "historical_period": {
                "start": customers.attrs["earliest_date"].date().isoformat(),
                "end": customers.attrs["latest_date"].date().isoformat(),
            },
            "active_customer": f"Most recent purchase within {customers.attrs['recent_window_days']} days of the latest date in the dataset.",
            "at_risk_customer": "Segmented as At Risk or Needs Attention when previous purchasing activity has become less recent.",
            "repeat_customer": "More than one transaction in the historical dataset.",
            "rfm_reference": "Recency is measured from the latest date available in the dataset, not from today's calendar date.",
        }

    @staticmethod
    def _limit(limit: int) -> int:
        return max(1, min(int(limit or 10), 100))

    @staticmethod
    def _unavailable(column: str) -> dict[str, str]:
        return {"status": "unavailable", "reason": f"Column not present in dataset: {column}"}
