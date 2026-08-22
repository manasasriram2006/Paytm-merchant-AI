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
