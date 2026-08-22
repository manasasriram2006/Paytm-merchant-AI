export type BusinessHealth = { score?: number; label?: string };
export type HomeSummary = { merchantName?: string; health?: BusinessHealth; todayRevenue?: number; transactions?: number; inventoryAlert?: string; aiInsight?: string };
export type InventoryAlert = { title: string; detail: string; severity: 'low' | 'high' };
export type Recommendation = { title: string; detail: string };

export type AlertSeverity = 'high' | 'medium' | 'low';
export type BusinessAlert = { id: string; severity: AlertSeverity; title: string; detail: string };
export type HomeOverview = {
  merchantName?: string;
  businessHealth?: { score: number; message: string };
  todaySales?: number;
  transactions?: number;
  salesGrowth?: number;
  aiInsight?: string;
  alerts: BusinessAlert[];
  snapshot?: { topCategory?: string; topProduct?: string; repeatCustomerPercentage?: number };
  /** Demo data is intentionally labelled until authorized business data is connected. */
  source: 'live' | 'demo';
};

export type InventoryItem = {
  id: number;
  name: string;
  category: string;
  current_stock: number;
  reorder_level: number;
  supplier_lead_time_days?: number;
  sku?: string;
  last_updated?: string;
};

export type InventoryResponse = { items: InventoryItem[]; lowStock: InventoryItem[] };
export type InventoryRisk = { Brand?: string; Category?: string; Stock_On_Hand?: number; Reorder_Level?: number; Lead_Time_Days?: number; stock_gap?: number };
export type InventoryDataSummary = { inventory_records?: number; items_below_reorder_level?: number; potential_inventory_risk?: InventoryRisk[] };

export type ForecastPoint = { date: string; revenue: number; units: number; lower_bound?: number; upper_bound?: number };
export type ForecastResponse = {
  horizon: number;
  historical: ForecastPoint[];
  forecast: ForecastPoint[];
  summary?: { expected_revenue?: number; expected_units?: number; average_daily_revenue?: number };
  insights?: string[];
  note?: string;
  message?: string;
};

export type CustomerSummary = {
  total_customers?: number;
  active_customers?: number;
  repeat_customers?: number;
  at_risk_customers?: number;
  repeat_customer_rate?: number;
  definitions?: { active_customer?: string; at_risk_customer?: string; repeat_customer?: string };
  note?: string;
};
export type CustomerRecord = {
  customer_id: string | number;
  total_revenue?: number;
  transaction_count?: number;
  total_units?: number;
  first_purchase_date?: string;
  last_purchase_date?: string;
  days_since_purchase?: number;
  /** Backend RFM segment; the source for customer status shown in the app. */
  segment?: string;
};
export type CustomerInsight = { type?: string; message?: string; value?: number };
export type AtRiskCustomersResponse = { explanation?: string; items?: CustomerRecord[] };
export type CustomerSegment = { segment?: string; customer_count?: number; percentage?: number; total_revenue?: number; average_revenue?: number };
