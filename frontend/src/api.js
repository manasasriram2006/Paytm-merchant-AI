const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

export const api = {
  merchant: () => request('/api/merchant'),
  dashboard: () => request('/api/dashboard'),
  getTransactionSummary: () => request('/api/transactions/summary'),
  getDailyTransactions: () => request('/api/transactions/daily'),
  getWeeklyTransactions: () => request('/api/transactions/weekly'),
  getMonthlyTransactions: () => request('/api/transactions/monthly'),
  getProductAnalytics: () => request('/api/analytics/products'),
  getCategoryAnalytics: () => request('/api/analytics/categories'),
  getBrandAnalytics: () => request('/api/analytics/brands'),
  getPaymentAnalytics: () => request('/api/analytics/payments'),
  getBusinessAnalytics: () => request('/api/analytics/business'),
  healthScore: () => request('/api/health-score'),
  forecast: (horizon = 7) => request(`/api/forecast?horizon=${horizon}`),
  customers: () => request('/api/customers'),
  getCustomerSummary: () => request('/api/customers/summary'),
  getCustomerSegments: () => request('/api/customers/segments'),
  getTopCustomers: (limit = 10) => request(`/api/customers/top?limit=${limit}`),
  getAtRiskCustomers: (limit = 10) => request(`/api/customers/at-risk?limit=${limit}`),
  getCustomerDemographics: () => request('/api/customers/demographics'),
  getCustomerLoyalty: () => request('/api/customers/loyalty'),
  getCustomerInsights: () => request('/api/customers/insights'),
  getCustomerValue: () => request('/api/customers/value'),
  inventory: () => request('/api/inventory'),
  updateInventory: (text) =>
    request('/api/inventory/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }),
  ask: (question) =>
    request('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
    }),
  uploadInvoice: (file) => {
    const form = new FormData();
    form.append('file', file);
    return request('/api/invoice/ocr', { method: 'POST', body: form });
  },
};
