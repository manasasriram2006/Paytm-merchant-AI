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
