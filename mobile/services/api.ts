import type { ForecastResponse, HomeOverview, InventoryAlert, InventoryDataSummary, InventoryResponse, Recommendation } from '../types/business';
const baseUrl = process.env.EXPO_PUBLIC_API_BASE_URL?.replace(/\/$/, '');
const demoHomeOverview: HomeOverview = { source: 'demo', merchantName: 'there', businessHealth: { score: 82, message: 'Your business is performing well this week.' }, todaySales: 12400, transactions: 42, salesGrowth: 8.2, aiInsight: 'Weekend beverage demand is expected to increase. Consider checking your Cold Drinks stock.', alerts: [{ id: 'restock', severity: 'high', title: 'Restock recommended', detail: 'Cold Drinks may run low before the weekend.' }, { id: 'customers', severity: 'medium', title: 'Customer opportunity', detail: "12 repeat customers haven't purchased recently." }], snapshot: { topCategory: 'Beverages', topProduct: 'Biscuits', repeatCustomerPercentage: 42 } };
class ApiService {
  private async request<T>(path: string): Promise<T> { if (!baseUrl) throw new Error('API base URL is not configured. Set EXPO_PUBLIC_API_BASE_URL.'); const response = await fetch(`${baseUrl}${path}`); if (!response.ok) throw new Error(`Request failed (${response.status}).`); return response.json() as Promise<T>; }
  getInventorySummary = () => this.request<unknown>('/api/inventory/summary');
  getInventoryAlerts = () => this.request<InventoryAlert[]>('/api/inventory/alerts');
  getInventoryRecommendations = () => this.request<Recommendation[]>('/api/inventory/recommendations');
  getInventory = () => this.request<InventoryResponse>('/api/inventory');
  getInventoryDataSummary = () => this.request<InventoryDataSummary>('/api/inventory/data-summary');
  getForecast = (horizon: 7 | 14 | 30) => this.request<ForecastResponse>(`/api/forecast?horizon=${horizon}`);
  /** Integration seam for future analytics/recommendation APIs. Demo data is explicit. */
  getHomeOverview = async (): Promise<HomeOverview> => {
    if (!baseUrl) return demoHomeOverview;
    const [summary, health, recommendations] = await Promise.all([
      this.request<Partial<HomeOverview>>('/api/analytics/summary'),
      this.request<HomeOverview['businessHealth']>('/api/analytics/business-health'),
      this.request<HomeOverview['alerts']>('/api/recommendations'),
    ]);
    return { ...summary, businessHealth: health ?? summary.businessHealth, alerts: recommendations ?? [], source: 'live' };
  };
}
export const api = new ApiService();
