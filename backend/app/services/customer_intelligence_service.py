from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .transaction_data_service import TransactionDataService, _round_money


SEGMENTS = ["HIGH_VALUE", "LOYAL", "AT_RISK", "NEW", "OCCASIONAL"]
VALID_PRIORITIES = {"HIGH", "MEDIUM", "LOW"}


class CustomerNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class CustomerThresholds:
    reference_date: pd.Timestamp
    first_purchase_new_window_days: int
    at_risk_days: int
    high_value_spend: float
    loyal_order_count: int
    loyal_frequency_per_30_days: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "reference_date": self.reference_date.date().isoformat(),
            "recency": "days_since_last_purchase is measured from the latest Invoice_Date in the dataset.",
            "frequency": "purchase_frequency is total_orders per 30 customer-age days through the reference date.",
            "monetary": "total_spend is the sum of Revenue for the customer.",
            "segment_rules": {
                "AT_RISK": (
                    f"total_orders >= 2 and days_since_last_purchase > {self.at_risk_days}; "
                    "this rule is evaluated first so inactive valuable customers are surfaced for action."
                ),
                "NEW": (
                    f"first purchase within {self.first_purchase_new_window_days} days of the reference date "
                    "and total_orders <= 2."
                ),
                "HIGH_VALUE": f"total_spend >= Rs {_round_money(self.high_value_spend)}.",
                "LOYAL": (
                    f"total_orders >= {self.loyal_order_count} or purchase_frequency >= "
                    f"{round(self.loyal_frequency_per_30_days, 4)} orders per 30 customer-age days."
                ),
                "OCCASIONAL": "valid activity that does not match the other deterministic segment rules.",
            },
            "recommendation_rules": {
                "HIGH": "AT_RISK customers with high spend or loyal purchase history.",
                "MEDIUM": "AT_RISK, HIGH_VALUE, LOYAL, or NEW customers with a clear retention or nurture action.",
                "LOW": "OCCASIONAL customers where a light re-engagement or basket-building action is suitable.",
            },
        }


@dataclass(frozen=True)
class CustomerIntelligenceService:
    transaction_data: TransactionDataService

    def summary(self) -> dict[str, Any]:
        customers, thresholds = self._customers()
        return {
            "total_customers": int(len(customers)),
            "new_customers": self._segment_count(customers, "NEW"),
            "loyal_customers": self._segment_count(customers, "LOYAL"),
            "high_value_customers": self._segment_count(customers, "HIGH_VALUE"),
            "at_risk_customers": self._segment_count(customers, "AT_RISK"),
            "methodology": thresholds.as_dict(),
        }

    def list_customers(
        self,
        segment: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        customers, _ = self._customers()
        filtered = customers
        if segment:
            normalized_segment = self._normalize_segment(segment)
            filtered = filtered[filtered["segment"] == normalized_segment]
        if search:
            needle = search.strip().lower()
            filtered = filtered[filtered["customer_id"].str.lower().str.contains(needle, regex=False)]

        total = int(len(filtered))
        limit = self._limit(limit)
        offset = max(0, int(offset or 0))
        page = filtered.sort_values(["segment_sort", "total_spend"], ascending=[True, False]).iloc[offset : offset + limit]
        return {
            "items": [self._customer_record(row) for row in page.itertuples(index=False)],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def customer_detail(self, customer_id: str) -> dict[str, Any]:
        customers, _ = self._customers()
        matches = customers[customers["customer_id"] == customer_id]
        if matches.empty:
            raise CustomerNotFoundError(f"Customer not found: {customer_id}")
        row = matches.iloc[0]
        record = self._customer_record(row)
        record["recent_purchases"] = self._recent_purchases(customer_id)
        record["customer_insight"] = self._insight(row)
        return record

    def segments(self) -> dict[str, Any]:
        customers, thresholds = self._customers()
        counts = customers["segment"].value_counts().to_dict()
        return {
            "items": [{"segment": segment, "count": int(counts.get(segment, 0))} for segment in SEGMENTS],
            "methodology": thresholds.as_dict(),
        }

    def recommendations(self, limit: int = 20) -> dict[str, Any]:
        customers, thresholds = self._customers()
        recommendations = []
        for row in customers.itertuples(index=False):
            recommendation = self._recommendation(row, thresholds)
            if recommendation:
                recommendations.append(recommendation)
        priority_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        recommendations.sort(key=lambda item: (priority_rank[item["priority"]], -item["total_spend"], item["customer_id"]))
        return {"items": recommendations[: self._limit(limit)], "methodology": thresholds.as_dict()}

    def top_customers(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.list_customers(limit=limit)["items"]

    def at_risk(self, limit: int = 10) -> dict[str, Any]:
        return self.list_customers(segment="AT_RISK", limit=limit)

    def demographics(self) -> dict[str, Any]:
        customers, _ = self._customers()
        response: dict[str, Any] = {}
        response["gender_distribution"] = (
            self._distribution(customers["customer_gender"].dropna())
            if "customer_gender" in customers.columns
            else self._unavailable("Customer_Gender")
        )
        response["age_distribution"] = (
            self._age_distribution(customers["customer_age"].dropna())
            if "customer_age" in customers.columns
            else self._unavailable("Customer_Age")
        )
        return response

    def loyalty(self) -> dict[str, Any]:
        customers, _ = self._customers()
        if "loyalty_flag" not in customers.columns:
            return self._unavailable("Loyalty_Flag")
        grouped = customers.groupby("loyalty_flag", as_index=False).agg(
            customer_count=("customer_id", "count"),
            total_spend=("total_spend", "sum"),
            total_orders=("total_orders", "sum"),
        )
        return {
            "items": [
                {
                    "loyalty_status": "Loyalty Flag" if int(row.loyalty_flag) == 1 else "No Loyalty Flag",
                    "customer_count": int(row.customer_count),
                    "total_spend": _round_money(row.total_spend),
                    "average_order_value": _round_money(row.total_spend / row.total_orders) if row.total_orders else 0,
                }
                for row in grouped.itertuples(index=False)
            ]
        }

    def insights(self) -> list[dict[str, Any]]:
        summary = self.summary()
        return [
            {
                "type": "at_risk",
                "message": f"{summary['at_risk_customers']} customers previously purchased but are now relatively inactive.",
                "value": summary["at_risk_customers"],
            },
            {
                "type": "high_value",
                "message": f"{summary['high_value_customers']} customers contribute high revenue and should be retained.",
                "value": summary["high_value_customers"],
            },
            {
                "type": "loyal",
                "message": f"{summary['loyal_customers']} customers purchase repeatedly or frequently.",
                "value": summary["loyal_customers"],
            },
        ]

    def value_summary(self) -> dict[str, Any]:
        customers, _ = self._customers()
        if customers.empty:
            return {
                "total_customer_revenue": 0,
                "average_revenue_per_customer": 0,
                "median_revenue_per_customer": 0,
                "average_orders_per_customer": 0,
                "average_units_per_customer": 0,
            }
        return {
            "total_customer_revenue": _round_money(customers["total_spend"].sum()),
            "average_revenue_per_customer": _round_money(customers["total_spend"].mean()),
            "median_revenue_per_customer": _round_money(customers["total_spend"].median()),
            "average_orders_per_customer": round(float(customers["total_orders"].mean()), 2),
            "average_units_per_customer": round(float(customers["total_quantity_purchased"].mean()), 2),
        }

    def _customers(self) -> tuple[pd.DataFrame, CustomerThresholds]:
        csv_path = getattr(self.transaction_data, "csv_path", None)
        if csv_path is not None:
            return _build_customer_intelligence(str(csv_path.resolve()))
        return _build_customer_frame(self.transaction_data.dataframe())

    def _recent_purchases(self, customer_id: str, limit: int = 5) -> list[dict[str, Any]]:
        df = self.transaction_data.dataframe()
        customer_rows = df[df["Customer_ID"] == customer_id].sort_values("Invoice_Date", ascending=False).head(limit)
        columns = ["Invoice_ID", "Invoice_Date", "Category", "Brand", "Units", "Revenue"]
        return [
            {
                "invoice_id": str(row.Invoice_ID),
                "invoice_date": row.Invoice_Date.date().isoformat(),
                "category": getattr(row, "Category", None),
                "product": getattr(row, "Brand", None),
                "quantity": int(row.Units),
                "spend": _round_money(row.Revenue),
            }
            for row in customer_rows[[column for column in columns if column in customer_rows.columns]].itertuples(index=False)
        ]

    @staticmethod
    def _customer_record(row: Any) -> dict[str, Any]:
        return {
            "customer_id": row.customer_id,
            "total_orders": int(row.total_orders),
            "total_spend": _round_money(row.total_spend),
            "average_order_value": _round_money(row.average_order_value),
            "first_purchase_date": row.first_purchase_date.date().isoformat(),
            "last_purchase_date": row.last_purchase_date.date().isoformat(),
            "purchase_frequency": round(float(row.purchase_frequency), 4),
            "days_since_last_purchase": int(row.days_since_last_purchase),
            "favorite_category": row.favorite_category,
            "favorite_product": row.favorite_product,
            "total_quantity_purchased": int(row.total_quantity_purchased),
            "segment": row.segment,
            "segment_reason": row.segment_reason,
        }

    @staticmethod
    def _insight(row: Any) -> str:
        if row.segment == "AT_RISK":
            return (
                f"Customer made {int(row.total_orders)} purchases previously but has not purchased in "
                f"{int(row.days_since_last_purchase)} days."
            )
        if row.segment == "HIGH_VALUE":
            return f"Customer contributes Rs {_round_money(row.total_spend)} in revenue and should be retained."
        if row.segment == "LOYAL":
            return f"Customer purchases repeatedly with {int(row.total_orders)} total orders."
        if row.segment == "NEW":
            return "Customer recently joined and may become a repeat customer with a timely nurture offer."
        return "Customer buys occasionally; a relevant bundle or reminder may increase repeat purchases."

    @staticmethod
    def _recommendation(row: Any, thresholds: CustomerThresholds) -> dict[str, Any] | None:
        if row.segment == "AT_RISK":
            high_priority = row.total_spend >= thresholds.high_value_spend or row.total_orders >= thresholds.loyal_order_count
            return {
                "customer_id": row.customer_id,
                "priority": "HIGH" if high_priority else "MEDIUM",
                "reason": (
                    f"Previously active customer has not purchased in {int(row.days_since_last_purchase)} days "
                    f"after {int(row.total_orders)} orders."
                ),
                "recommended_action": "Consider a targeted follow-up or win-back offer.",
                "total_spend": _round_money(row.total_spend),
                "segment": row.segment,
            }
        if row.segment == "HIGH_VALUE":
            return {
                "customer_id": row.customer_id,
                "priority": "MEDIUM",
                "reason": f"Customer has contributed Rs {_round_money(row.total_spend)}, above the high-value threshold.",
                "recommended_action": "Prioritize retention with personalized rewards or early access offers.",
                "total_spend": _round_money(row.total_spend),
                "segment": row.segment,
            }
        if row.segment == "LOYAL":
            return {
                "customer_id": row.customer_id,
                "priority": "MEDIUM",
                "reason": f"Customer has {int(row.total_orders)} orders and frequent purchase activity.",
                "recommended_action": "Encourage larger baskets with category-relevant bundles.",
                "total_spend": _round_money(row.total_spend),
                "segment": row.segment,
            }
        if row.segment == "NEW":
            return {
                "customer_id": row.customer_id,
                "priority": "MEDIUM",
                "reason": "Customer made a recent first purchase with limited history.",
                "recommended_action": "Send a second-purchase nudge for their favorite category.",
                "total_spend": _round_money(row.total_spend),
                "segment": row.segment,
            }
        if row.segment == "OCCASIONAL":
            return {
                "customer_id": row.customer_id,
                "priority": "LOW",
                "reason": "Customer has valid activity but lower frequency and monetary contribution.",
                "recommended_action": "Use light-touch re-engagement or basket-building offers.",
                "total_spend": _round_money(row.total_spend),
                "segment": row.segment,
            }
        return None

    @staticmethod
    def _segment_count(customers: pd.DataFrame, segment: str) -> int:
        return int((customers["segment"] == segment).sum()) if not customers.empty else 0

    @staticmethod
    def _normalize_segment(segment: str) -> str:
        normalized = segment.strip().upper()
        if normalized not in SEGMENTS:
            raise ValueError(f"segment must be one of: {', '.join(SEGMENTS)}")
        return normalized

    @staticmethod
    def _limit(limit: int) -> int:
        return max(1, min(int(limit or 50), 100))

    @staticmethod
    def _distribution(series: pd.Series) -> list[dict[str, Any]]:
        counts = series.astype(str).value_counts(dropna=True)
        total = int(counts.sum())
        return [
            {"label": label, "count": int(count), "percentage": round(count / total * 100, 2) if total else 0}
            for label, count in counts.items()
        ]

    @staticmethod
    def _age_distribution(series: pd.Series) -> list[dict[str, Any]]:
        if series.empty:
            return []
        bins = [0, 24, 34, 44, 54, 64, 200]
        labels = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
        return CustomerIntelligenceService._distribution(pd.cut(series, bins=bins, labels=labels, right=True).dropna())

    @staticmethod
    def _unavailable(column: str) -> dict[str, str]:
        return {"status": "unavailable", "reason": f"Column not present in dataset: {column}"}


@lru_cache(maxsize=4)
def _build_customer_intelligence(csv_path: str) -> tuple[pd.DataFrame, CustomerThresholds]:
    df = TransactionDataService(Path(csv_path).parent).dataframe()
    return _build_customer_frame(df)


def _build_customer_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, CustomerThresholds]:
    if df.empty:
        empty = _empty_customer_frame()
        reference_date = pd.Timestamp("1970-01-01")
        return empty, CustomerThresholds(reference_date, 30, 45, 0, 2, 0)

    latest_date = df["Invoice_Date"].max().normalize()
    earliest_date = df["Invoice_Date"].min().normalize()
    history_days = max(1, int((latest_date - earliest_date).days) + 1)
    first_purchase_new_window_days = max(14, min(30, round(history_days * 0.08)))
    at_risk_days = max(30, min(60, round(history_days * 0.15)))

    grouped = df.groupby("Customer_ID").agg(
        total_orders=("Invoice_ID", "nunique"),
        total_spend=("Revenue", "sum"),
        total_quantity_purchased=("Units", "sum"),
        first_purchase_date=("Invoice_Date", "min"),
        last_purchase_date=("Invoice_Date", "max"),
    )
    customers = grouped.reset_index().rename(columns={"Customer_ID": "customer_id"})
    customers["average_order_value"] = customers["total_spend"] / customers["total_orders"].clip(lower=1)
    customers["days_since_last_purchase"] = (latest_date - customers["last_purchase_date"].dt.normalize()).dt.days
    customers["days_since_first_purchase"] = (latest_date - customers["first_purchase_date"].dt.normalize()).dt.days
    customer_age_days = customers["days_since_first_purchase"] + 1
    customers["purchase_frequency"] = customers["total_orders"] / customer_age_days.clip(lower=1) * 30

    customers = _merge_optional_customer_fields(df, customers)
    customers = _merge_favorite_value(df, customers, "Category", "favorite_category")
    favorite_product_column = "Product" if "Product" in df.columns else "Brand" if "Brand" in df.columns else None
    customers = _merge_favorite_value(df, customers, favorite_product_column, "favorite_product")

    positive_spend = customers.loc[customers["total_spend"] > 0, "total_spend"]
    high_value_spend = float(positive_spend.quantile(0.8)) if not positive_spend.empty else 0
    loyal_order_count = max(2, int(customers["total_orders"].quantile(0.75))) if not customers.empty else 2
    loyal_frequency = float(customers["purchase_frequency"].quantile(0.75)) if not customers.empty else 0
    thresholds = CustomerThresholds(
        reference_date=latest_date,
        first_purchase_new_window_days=first_purchase_new_window_days,
        at_risk_days=at_risk_days,
        high_value_spend=high_value_spend,
        loyal_order_count=loyal_order_count,
        loyal_frequency_per_30_days=loyal_frequency,
    )

    customers["segment"] = customers.apply(lambda row: _segment_customer(row, thresholds), axis=1)
    customers["segment_reason"] = customers.apply(lambda row: _segment_reason(row, thresholds), axis=1)
    segment_sort = {segment: index for index, segment in enumerate(SEGMENTS)}
    customers["segment_sort"] = customers["segment"].map(segment_sort)
    return customers, thresholds


def _merge_optional_customer_fields(df: pd.DataFrame, customers: pd.DataFrame) -> pd.DataFrame:
    if "Customer_Age" in df.columns:
        age = df.groupby("Customer_ID")["Customer_Age"].mean().reset_index()
        customers = customers.merge(age.rename(columns={"Customer_ID": "customer_id", "Customer_Age": "customer_age"}), on="customer_id", how="left")
    if "Customer_Gender" in df.columns:
        gender = df.dropna(subset=["Customer_Gender"]).groupby("Customer_ID")["Customer_Gender"].agg(_mode_or_first).reset_index()
        customers = customers.merge(gender.rename(columns={"Customer_ID": "customer_id", "Customer_Gender": "customer_gender"}), on="customer_id", how="left")
    if "Loyalty_Flag" in df.columns:
        loyalty = df.groupby("Customer_ID")["Loyalty_Flag"].max().reset_index()
        customers = customers.merge(loyalty.rename(columns={"Customer_ID": "customer_id", "Loyalty_Flag": "loyalty_flag"}), on="customer_id", how="left")
    return customers


def _merge_favorite_value(df: pd.DataFrame, customers: pd.DataFrame, column: str | None, output_column: str) -> pd.DataFrame:
    if not column or column not in df.columns:
        customers[output_column] = None
        return customers
    ranked = (
        df.groupby(["Customer_ID", column], as_index=False)
        .agg(spend=("Revenue", "sum"), orders=("Invoice_ID", "nunique"))
        .sort_values(["Customer_ID", "spend", "orders", column], ascending=[True, False, False, True])
    )
    favorite = ranked.drop_duplicates("Customer_ID")[["Customer_ID", column]]
    return customers.merge(
        favorite.rename(columns={"Customer_ID": "customer_id", column: output_column}),
        on="customer_id",
        how="left",
    )


def _segment_customer(row: pd.Series, thresholds: CustomerThresholds) -> str:
    if int(row.total_orders) >= 2 and int(row.days_since_last_purchase) > thresholds.at_risk_days:
        return "AT_RISK"
    if int(row.days_since_first_purchase) <= thresholds.first_purchase_new_window_days and int(row.total_orders) <= 2:
        return "NEW"
    if float(row.total_spend) >= thresholds.high_value_spend and float(row.total_spend) > 0:
        return "HIGH_VALUE"
    if int(row.total_orders) >= thresholds.loyal_order_count or float(row.purchase_frequency) >= thresholds.loyal_frequency_per_30_days:
        return "LOYAL"
    return "OCCASIONAL"


def _segment_reason(row: pd.Series, thresholds: CustomerThresholds) -> str:
    if row.segment == "AT_RISK":
        return (
            f"Customer made {int(row.total_orders)} orders but last purchased "
            f"{int(row.days_since_last_purchase)} days ago, above the {thresholds.at_risk_days}-day inactivity threshold."
        )
    if row.segment == "NEW":
        return (
            f"First purchase was {int(row.days_since_first_purchase)} days before the reference date "
            f"and order history is limited to {int(row.total_orders)} orders."
        )
    if row.segment == "HIGH_VALUE":
        return f"Total spend Rs {_round_money(row.total_spend)} meets or exceeds the high-value threshold."
    if row.segment == "LOYAL":
        return (
            f"Customer has {int(row.total_orders)} orders or {round(float(row.purchase_frequency), 4)} "
            "orders per 30 customer-age days, meeting the loyal activity rule."
        )
    return "Customer has valid purchases but lower recency, frequency, or monetary contribution than other segments."


def _empty_customer_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "customer_id",
            "total_orders",
            "total_spend",
            "average_order_value",
            "first_purchase_date",
            "last_purchase_date",
            "purchase_frequency",
            "days_since_last_purchase",
            "favorite_category",
            "favorite_product",
            "total_quantity_purchased",
            "segment",
            "segment_reason",
            "segment_sort",
        ]
    )


def _mode_or_first(values: pd.Series) -> Any:
    mode = values.mode()
    return mode.iloc[0] if not mode.empty else values.iloc[0]
