from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class DataService:
    data_dir: Path

    def transactions(self) -> pd.DataFrame:
        df = pd.read_csv(self.data_dir / "fmcg_sales_enriched.csv")
        df["Invoice_Date"] = pd.to_datetime(df["Invoice_Date"])
        df["date"] = df["Invoice_Date"].dt.normalize()
        df["time"] = df["Invoice_Date"].dt.strftime("%H:%M")
        df["amount"] = pd.to_numeric(df["Revenue"])
        df["category"] = df["Category"]
        df["payment_method"] = df["Payment_Mode"]
        df["customer_id"] = df["Customer_ID"]
        df["transaction_id"] = df["Invoice_ID"]
        return df

    def summary(self, low_stock_count: int = 0) -> dict:
        df = self.transactions()
        daily = df.groupby("date", as_index=False)["amount"].sum()
        latest_day = daily["date"].max()
        previous_days = daily[daily["date"] < latest_day]
        latest_sales = float(daily.loc[daily["date"] == latest_day, "amount"].iloc[0])
        previous_avg = float(previous_days["amount"].tail(7).mean()) if not previous_days.empty else latest_sales
        growth = ((latest_sales - previous_avg) / previous_avg * 100) if previous_avg else 0

        visits_by_customer = df.groupby("customer_id")["Invoice_ID"].nunique()
        repeat_customer_ids = visits_by_customer[visits_by_customer > 1].index
        repeat_customers = len(repeat_customer_ids)
        total_customers = df["customer_id"].nunique()
        repeat_rate = repeat_customers / total_customers * 100 if total_customers else 0
        avg_order_value = float(df["amount"].mean())
        total_sales = float(df["amount"].sum())

        return {
            "totalSales": round(total_sales),
            "latestDaySales": round(latest_sales),
            "sevenDayTrendPct": round(growth, 1),
            "avgOrderValue": round(avg_order_value),
            "repeatCustomerRate": round(repeat_rate, 1),
            "transactionCount": int(len(df)),
            "lowStockCount": low_stock_count,
        }

    def dashboard(self, low_stock_count: int = 0) -> dict:
        df = self.transactions()
        daily = df.groupby("date", as_index=False)["amount"].sum()
        category = df.groupby("category", as_index=False)["amount"].sum().sort_values("amount", ascending=False)
        methods = df.groupby("payment_method", as_index=False)["amount"].sum()
        hours = df.assign(hour=df["time"].str.slice(0, 2).astype(int)).groupby("hour", as_index=False)["amount"].sum()

        return {
            "summary": self.summary(low_stock_count),
            "dailySales": [{"date": row.date.strftime("%d %b"), "sales": round(row.amount)} for row in daily.itertuples()],
            "categorySales": [
                {"category": row.category.replace("_", " ").title(), "sales": round(row.amount)}
                for row in category.itertuples()
            ],
            "paymentMix": [
                {"method": row.payment_method, "sales": round(row.amount)}
                for row in methods.itertuples()
            ],
            "hourlySales": [
                {"hour": f"{row.hour:02d}:00", "sales": round(row.amount)}
                for row in hours.itertuples()
            ],
        }

    def business_health(self, low_stock_count: int = 0) -> dict:
        s = self.summary(low_stock_count)
        stock_score = max(0, 100 - s["lowStockCount"] * 12)
        growth_score = float(np.clip(60 + s["sevenDayTrendPct"], 0, 100))
        repeat_score = float(np.clip(s["repeatCustomerRate"] * 1.4, 0, 100))
        aov_score = float(np.clip(s["avgOrderValue"] / 8, 0, 100))
        score = round((stock_score * 0.25) + (growth_score * 0.3) + (repeat_score * 0.25) + (aov_score * 0.2))

        return {
            "score": score,
            "label": "Healthy" if score >= 75 else "Needs Attention" if score >= 55 else "At Risk",
            "drivers": [
                {"name": "Sales momentum", "score": round(growth_score), "detail": f"{s['sevenDayTrendPct']}% vs recent average"},
                {"name": "Repeat customers", "score": round(repeat_score), "detail": f"{s['repeatCustomerRate']}% repeat customer share"},
                {"name": "Stock readiness", "score": round(stock_score), "detail": f"{s['lowStockCount']} low-stock products"},
                {"name": "Basket value", "score": round(aov_score), "detail": f"Rs {s['avgOrderValue']} average order value"},
            ],
        }

    def forecast(self) -> dict:
        daily = self.transactions().groupby("date", as_index=False)["amount"].sum().sort_values("date")
        rolling = daily["amount"].rolling(window=4, min_periods=1).mean()
        last_date = daily["date"].max()
        future = []
        for offset in range(1, 8):
            seasonal_lift = 1.06 if (last_date.day + offset) % 7 in (0, 6) else 1.0
            value = float(rolling.iloc[-1] * seasonal_lift)
            future.append({"date": (last_date + pd.Timedelta(days=offset)).strftime("%d %b"), "forecast": round(value)})
        return {
            "history": [{"date": row.date.strftime("%d %b"), "sales": round(row.amount)} for row in daily.itertuples()],
            "forecast": future,
            "note": "Forecast is based on recent synthetic transaction patterns, not product-level POS data.",
        }

    def customer_intelligence(self) -> dict:
        df = self.transactions()
        by_customer = df.groupby("customer_id").agg(spend=("amount", "sum"), visits=("transaction_id", "count")).reset_index()
        high_value = by_customer.sort_values("spend", ascending=False).head(5)
        visits_by_customer = df.groupby("customer_id")["Invoice_ID"].nunique()
        repeat_customer_ids = visits_by_customer[visits_by_customer > 1].index
        repeat_share = df[df["customer_id"].isin(repeat_customer_ids)]["amount"].sum() / df["amount"].sum() * 100
        return {
            "repeatRevenueShare": round(repeat_share, 1),
            "newCustomerCount": int((visits_by_customer == 1).sum()),
            "repeatCustomerCount": int((visits_by_customer > 1).sum()),
            "topCustomers": [
                {"customerId": row.customer_id, "spend": round(row.spend), "visits": int(row.visits)}
                for row in high_value.itertuples()
            ],
            "insights": [
                "Repeat customers are driving a meaningful share of digital payment revenue.",
                "Evening transactions show larger baskets, useful for bundle offers.",
                "Customer IDs are synthetic prototype identifiers and do not expose personal data.",
            ],
        }
