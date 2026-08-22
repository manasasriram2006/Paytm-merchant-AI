from __future__ import annotations

from abc import ABC, abstractmethod


class LlmProvider(ABC):
    @abstractmethod
    def answer(self, question: str, context: dict) -> str:
        raise NotImplementedError


class MockLlmProvider(LlmProvider):
    def answer(self, question: str, context: dict) -> str:
        summary = context["summary"]
        low_stock = context["low_stock"]
        if "stock" in question.lower() or "inventory" in question.lower():
            if low_stock:
                names = ", ".join(item["name"] for item in low_stock[:3])
                return f"Focus on replenishing {names}. These are at or below reorder level, so sales may be constrained if demand continues."
            return "Stock looks stable in the merchant-entered inventory list. Keep updating items through invoices or voice notes for better advice."
        if "customer" in question.lower():
            return f"Repeat customers currently make up {summary['repeatCustomerRate']}% of known customer IDs. Try evening bundle offers for frequent buyers."
        return (
            f"Sales are Rs {summary['totalSales']} across {summary['transactionCount']} synthetic transactions. "
            f"The recent trend is {summary['sevenDayTrendPct']}%, so the next action is to protect best-selling categories and fix low-stock items."
        )


def get_llm_provider(provider_name: str) -> LlmProvider:
    if provider_name != "mock":
        return MockLlmProvider()
    return MockLlmProvider()
