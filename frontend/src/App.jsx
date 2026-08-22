import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  Bot,
  Boxes,
  FileText,
  Gauge,
  IndianRupee,
  MessageSquareText,
  RefreshCw,
  Settings,
  ShoppingBag,
  Sparkles,
  TrendingUp,
  Upload,
  Users,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from './api';
import { Card } from './components/Card';
import { EmptyBlock, ErrorBlock, LoadingBlock } from './components/StateBlock';
import { MetricCard } from './components/MetricCard';

const navItems = [
  ['Dashboard', BarChart3],
  ['Health Score', Gauge],
  ['Forecasting', TrendingUp],
  ['Customers', Users],
  ['Inventory AI', Boxes],
  ['Invoice OCR', FileText],
  ['Ask AI', MessageSquareText],
  ['Recommendations', Sparkles],
  ['Settings', Settings],
];

const colors = ['#00baf2', '#002970', '#20bf55', '#f5a623', '#d64550'];

function currency(value) {
  return `Rs ${Number(value || 0).toLocaleString('en-IN')}`;
}

function useBusinessData(refreshKey) {
  const [state, setState] = useState({ loading: true, error: null, data: null });

  useEffect(() => {
    let active = true;
    setState({ loading: true, error: null, data: null });
    Promise.all([
      api.merchant(),
      api.dashboard(),
      api.healthScore(),
      api.customers(),
      api.inventory(),
    ])
      .then(([merchant, dashboard, health, customers, inventory]) => {
        if (active) {
          setState({
            loading: false,
            error: null,
            data: { merchant, dashboard, health, customers, inventory },
          });
        }
      })
      .catch((error) => {
        if (active) setState({ loading: false, error: error.message, data: null });
      });
    return () => {
      active = false;
    };
  }, [refreshKey]);

  return state;
}

export default function App() {
  const [active, setActive] = useState('Dashboard');
  const [refreshKey, setRefreshKey] = useState(0);
  const { loading, error, data } = useBusinessData(refreshKey);

  const recommendations = useMemo(() => {
    if (!data) return [];
    const lowStock = data.inventory.lowStock.map((item) => item.name).slice(0, 3).join(', ');
    return [
      {
        title: 'Restock before weekend demand',
        body: lowStock
          ? `${lowStock} are below reorder level. Update supplier order quantities from invoice OCR.`
          : 'Inventory looks stable. Keep voice updates flowing after deliveries.',
      },
      {
        title: 'Protect evening basket size',
        body: 'Evening payments have higher order values. Try a Paytm QR counter offer for grocery and household bundles.',
      },
      {
        title: 'Bring new buyers back',
        body: `${data.customers.newCustomerCount} new customers appeared in the sample. Send a simple return offer through existing merchant channels.`,
      },
    ];
  }, [data]);

  return (
    <div className="min-h-screen bg-slate-50">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-68 border-r border-slate-200 bg-white px-4 py-5 lg:block">
        <div className="mb-7 px-2">
          <div className="text-xl font-bold tracking-normal">
            <span className="paytm-text">Paytm</span> <span className="paytm-dark">Business AI</span>
          </div>
          <p className="mt-1 text-xs text-slate-500">Merchant co-pilot prototype</p>
        </div>
        <nav className="space-y-1">
          {navItems.map(([label, Icon]) => (
            <button
              key={label}
              onClick={() => setActive(label)}
              className={`flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-medium ${
                active === label ? 'bg-sky-50 text-sky-700' : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              <Icon size={18} />
              {label}
            </button>
          ))}
        </nav>
      </aside>

      <main className="lg:pl-68">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/95 px-4 py-4 backdrop-blur md:px-7">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-sky-600">Inside Paytm for Business</p>
              <h1 className="text-2xl font-semibold text-slate-950">{active}</h1>
              {data?.merchant && (
                <p className="text-sm text-slate-500">
                  {data.merchant.business_name} · {data.merchant.business_type} · {data.merchant.city}
                </p>
              )}
            </div>
            <button
              onClick={() => setRefreshKey((key) => key + 1)}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-[#002970] px-4 py-2 text-sm font-semibold text-white hover:bg-[#001f56]"
            >
              <RefreshCw size={16} />
              Refresh
            </button>
          </div>
          <div className="mt-4 flex gap-2 overflow-x-auto lg:hidden">
            {navItems.map(([label]) => (
              <button
                key={label}
                onClick={() => setActive(label)}
                className={`shrink-0 rounded-md px-3 py-2 text-sm ${active === label ? 'bg-sky-50 text-sky-700' : 'bg-slate-100 text-slate-600'}`}
              >
                {label}
              </button>
            ))}
          </div>
        </header>

        <div className="px-4 py-6 md:px-7">
          {loading && <LoadingBlock />}
          {error && <ErrorBlock message={`Backend unavailable: ${error}`} />}
          {data && (
            <>
              {active === 'Dashboard' && <DashboardView data={data} />}
              {active === 'Health Score' && <HealthScoreView health={data.health} />}
              {active === 'Forecasting' && <ForecastView forecast={data.forecast} />}
              {active === 'Customers' && <CustomersView customers={data.customers} />}
              {active === 'Inventory AI' && <InventoryView inventory={data.inventory} onChanged={() => setRefreshKey((key) => key + 1)} />}
              {active === 'Invoice OCR' && <InvoiceView />}
              {active === 'Ask AI' && <AskView />}
              {active === 'Recommendations' && <RecommendationsView recommendations={recommendations} />}
              {active === 'Settings' && <SettingsView />}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function DashboardView({ data }) {
  const summary = data.dashboard.summary;
  return (
    <div className="space-y-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Total Paytm GMV" value={currency(summary.totalSales)} detail="From representative transaction data" icon={IndianRupee} />
        <MetricCard label="Recent Trend" value={`${summary.sevenDayTrendPct}%`} detail="Latest day vs prior 7-day average" icon={TrendingUp} />
        <MetricCard label="Avg Order Value" value={currency(summary.avgOrderValue)} detail={`${summary.transactionCount} synthetic payments`} icon={ShoppingBag} />
        <MetricCard label="Repeat Customer Rate" value={`${summary.repeatCustomerRate}%`} detail="Based on prototype customer IDs" icon={Users} />
      </div>
      <div className="grid gap-5 xl:grid-cols-3">
        <Card title="Sales From Paytm Transactions" className="xl:col-span-2">
          <Chart height={320}>
            <AreaChart data={data.dashboard.dailySales}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value) => currency(value)} />
              <Area type="monotone" dataKey="sales" stroke="#00baf2" fill="#b9ecfb" />
            </AreaChart>
          </Chart>
        </Card>
        <Card title="Payment Mix">
          <Chart height={320}>
            <PieChart>
              <Pie data={data.dashboard.paymentMix} dataKey="sales" nameKey="method" innerRadius={72} outerRadius={105} paddingAngle={3}>
                {data.dashboard.paymentMix.map((entry, index) => <Cell key={entry.method} fill={colors[index % colors.length]} />)}
              </Pie>
              <Tooltip formatter={(value) => currency(value)} />
            </PieChart>
          </Chart>
        </Card>
      </div>
      <Card title="Category-Level Signal">
        <Chart height={300}>
          <BarChart data={data.dashboard.categorySales}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="category" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip formatter={(value) => currency(value)} />
            <Bar dataKey="sales" radius={[6, 6, 0, 0]} fill="#002970" />
          </BarChart>
        </Chart>
      </Card>
    </div>
  );
}

function HealthScoreView({ health }) {
  return (
    <div className="grid gap-5 xl:grid-cols-[360px_1fr]">
      <Card>
        <p className="text-sm text-slate-500">Business Health Score</p>
        <div className="mt-5 flex h-44 w-44 items-center justify-center rounded-full border-[18px] border-sky-400">
          <div className="text-center">
            <p className="text-5xl font-bold text-slate-950">{health.score}</p>
            <p className="text-sm font-semibold text-slate-500">{health.label}</p>
          </div>
        </div>
        <p className="mt-5 text-sm text-slate-600">The score blends transaction-level momentum with merchant-entered stock readiness.</p>
      </Card>
      <Card title="Score Drivers">
        <div className="space-y-4">
          {health.drivers.map((driver) => (
            <div key={driver.name}>
              <div className="mb-1 flex justify-between text-sm">
                <span className="font-medium text-slate-800">{driver.name}</span>
                <span className="text-slate-500">{driver.score}/100</span>
              </div>
              <div className="h-2 rounded-full bg-slate-100">
                <div className="h-2 rounded-full bg-sky-500" style={{ width: `${driver.score}%` }} />
              </div>
              <p className="mt-1 text-xs text-slate-500">{driver.detail}</p>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function ForecastView({ forecast: initialForecast }) {
  const [horizon, setHorizon] = useState(7);
  const [state, setState] = useState({ loading: !initialForecast, error: null, data: initialForecast || null });

  useEffect(() => {
    let active = true;
    if (horizon === 7 && initialForecast) {
      setState({ loading: false, error: null, data: initialForecast });
      return () => {
        active = false;
      };
    }

    setState({ loading: true, error: null, data: null });
    api.forecast(horizon)
      .then((data) => {
        if (active) setState({ loading: false, error: null, data });
      })
      .catch((error) => {
        if (active) setState({ loading: false, error: error.message, data: null });
      });

    return () => {
      active = false;
    };
  }, [horizon, initialForecast]);

  const forecast = state.data;
  const combined = useMemo(() => {
    if (!forecast) return [];
    return [
      ...(forecast.historical || []).slice(-45).map((item) => ({
        date: item.date,
        sales: item.revenue,
        units: item.units,
      })),
      ...(forecast.forecast || []).map((item) => ({
        date: item.date,
        forecast: item.revenue,
        forecastUnits: item.units,
        lowerBound: item.lower_bound,
        upperBound: item.upper_bound,
      })),
    ];
  }, [forecast]);

  const peakDay = forecast?.summary?.highest_expected_sales_day;

  return (
    <div className="space-y-5">
      <Card
        title="Sales Forecast"
        action={
          <div className="flex rounded-md bg-slate-100 p-1">
            {[7, 14, 30].map((days) => (
              <button
                key={days}
                onClick={() => setHorizon(days)}
                className={`rounded px-3 py-1.5 text-sm font-semibold ${
                  horizon === days ? 'bg-white text-sky-700 shadow-sm' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {days} Days
              </button>
            ))}
          </div>
        }
      >
        <p className="mb-4 text-sm text-slate-500">Plan ahead using your historical sales patterns.</p>
        {state.loading && <LoadingBlock label="Analyzing your sales history..." />}
        {state.error && (
          <div className="space-y-3">
            <ErrorBlock message="Unable to generate the forecast." />
            <button
              onClick={() => {
                setState({ loading: true, error: null, data: null });
                api.forecast(horizon)
                  .then((data) => setState({ loading: false, error: null, data }))
                  .catch((error) => setState({ loading: false, error: error.message, data: null }));
              }}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-[#002970] px-4 py-2 text-sm font-semibold text-white hover:bg-[#001f56]"
            >
              <RefreshCw size={16} />
              Retry
            </button>
          </div>
        )}
        {!state.loading && !state.error && forecast?.forecast_method === 'insufficient_data' && (
          <EmptyBlock message={forecast.message || 'Not enough historical sales data to generate a reliable forecast.'} />
        )}
        {!state.loading && !state.error && forecast?.forecast?.length > 0 && (
          <Chart height={380}>
            <LineChart data={combined}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value) => currency(value)} />
              <Line type="monotone" dataKey="sales" name="Historical Sales" stroke="#00baf2" strokeWidth={3} dot={false} />
              <Line type="monotone" dataKey="forecast" name="Forecast Sales" stroke="#20bf55" strokeWidth={3} strokeDasharray="6 4" dot />
              <Line type="monotone" dataKey="lowerBound" name="Forecast Range Low" stroke="#86efac" strokeWidth={1} strokeDasharray="3 3" dot={false} />
              <Line type="monotone" dataKey="upperBound" name="Forecast Range High" stroke="#86efac" strokeWidth={1} strokeDasharray="3 3" dot={false} />
            </LineChart>
          </Chart>
        )}
        {forecast?.note && <p className="mt-3 text-sm text-slate-500">{forecast.note}</p>}
      </Card>

      {forecast?.forecast?.length > 0 && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Expected Revenue" value={currency(forecast.summary.expected_revenue)} detail={`${horizon}-day forecast`} icon={IndianRupee} />
            <MetricCard label="Expected Units" value={Number(forecast.summary.expected_units || 0).toLocaleString('en-IN')} detail="Predicted units sold" icon={ShoppingBag} />
            <MetricCard label="Average Daily Sales" value={currency(forecast.summary.average_daily_revenue)} detail="Expected daily revenue" icon={TrendingUp} />
            <MetricCard label="Peak Expected Day" value={peakDay ? currency(peakDay.revenue) : 'N/A'} detail={peakDay ? peakDay.date : 'No forecast day'} icon={Gauge} />
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <Card title="How this forecast works">
              <div className="space-y-3 text-sm text-slate-600">
                <p>The forecast uses your historical sales patterns, recent sales activity, day-of-week patterns and rolling demand trends.</p>
                <p>Model: {forecast.forecast_method === 'ml_regression' ? 'ML regression' : 'Weekly average fallback'}</p>
                <p>Historical data: {forecast.model?.historical_days} days</p>
                <p>Forecast horizon: {forecast.horizon} days</p>
              </div>
            </Card>
            <Card title="Model Performance">
              <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
                <MiniStat label="MAE" value={currency(forecast.metrics?.revenue?.mae)} />
                <MiniStat label="RMSE" value={currency(forecast.metrics?.revenue?.rmse)} />
                <MiniStat label="MAPE" value={forecast.metrics?.revenue?.mape == null ? 'N/A' : `${forecast.metrics.revenue.mape}%`} />
              </div>
              <p className="mt-3 text-sm text-slate-500">These metrics show how closely the model matched historical sales during validation.</p>
            </Card>
            <Card title="Business Insight">
              <div className="space-y-2">
                {(forecast.insights || []).map((insight) => (
                  <p key={insight} className="rounded-md bg-slate-50 p-3 text-sm text-slate-600">{insight}</p>
                ))}
              </div>
            </Card>
          </div>

          <Card title="Why this matters">
            <p className="text-sm text-slate-600">
              Your sales forecast will be used by Smart Inventory Alert later to help estimate upcoming stock requirements.
            </p>
          </Card>
        </>
      )}
    </div>
  );
}

function MiniStat({ label, value }) {
  return (
    <div className="rounded-md border border-slate-200 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-slate-950">{value}</p>
    </div>
  );
}

function CustomersView() {
  const [retryKey, setRetryKey] = useState(0);
  const [segmentFilter, setSegmentFilter] = useState('All');
  const [state, setState] = useState({
    summary: { loading: true, error: null, data: null },
    segments: { loading: true, error: null, data: null },
    top: { loading: true, error: null, data: null },
    atRisk: { loading: true, error: null, data: null },
    demographics: { loading: true, error: null, data: null },
    loyalty: { loading: true, error: null, data: null },
    insights: { loading: true, error: null, data: null },
    value: { loading: true, error: null, data: null },
  });

  useEffect(() => {
    let active = true;
    const loaders = {
      summary: api.getCustomerSummary,
      segments: api.getCustomerSegments,
      top: () => api.getTopCustomers(10),
      atRisk: () => api.getAtRiskCustomers(10),
      demographics: api.getCustomerDemographics,
      loyalty: api.getCustomerLoyalty,
      insights: api.getCustomerInsights,
      value: api.getCustomerValue,
    };

    setState(Object.fromEntries(Object.keys(loaders).map((key) => [key, { loading: true, error: null, data: null }])));
    Object.entries(loaders).forEach(([key, loader]) => {
      loader()
        .then((data) => {
          if (active) setState((current) => ({ ...current, [key]: { loading: false, error: null, data } }));
        })
        .catch((error) => {
          if (active) setState((current) => ({ ...current, [key]: { loading: false, error: error.message, data: null } }));
        });
    });
    return () => {
      active = false;
    };
  }, [retryKey]);

  const segments = state.segments.data || [];
  const segmentOptions = ['All', ...segments.map((item) => item.segment)];
  const topRows = (state.top.data || []).filter((customer) => segmentFilter === 'All' || customer.segment === segmentFilter);
  const atRiskRows = (state.atRisk.data?.items || []).filter((customer) => segmentFilter === 'All' || customer.segment === segmentFilter);

  return (
    <div className="space-y-5">
      <Card title="Customer Intelligence">
        <p className="text-sm text-slate-500">Understand your customers and build stronger relationships.</p>
        <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-sky-600">Representative customer IDs</p>
      </Card>

      <CustomerSectionFrame state={state.summary} onRetry={() => setRetryKey((key) => key + 1)} loadingLabel="Loading customer summary...">
        {state.summary.data && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard label="Total Customers" value={formatCount(state.summary.data.total_customers)} icon={Users} />
            <MetricCard label="Active Customers" value={formatCount(state.summary.data.active_customers)} detail={state.summary.data.definitions?.active_customer} icon={Users} />
            <MetricCard label="Repeat Customers" value={formatCount(state.summary.data.repeat_customers)} detail={`${state.summary.data.repeat_customer_rate}% repeat rate`} icon={RefreshCw} />
            <MetricCard label="Average Customer Value" value={currency(state.summary.data.average_customer_value)} icon={IndianRupee} />
            <MetricCard label="At-Risk Customers" value={formatCount(state.summary.data.at_risk_customers)} detail="At Risk or Needs Attention" icon={AlertTriangle} />
          </div>
        )}
      </CustomerSectionFrame>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_420px]">
        <CustomerSectionFrame state={state.segments} onRetry={() => setRetryKey((key) => key + 1)} loadingLabel="Loading customer segments...">
          <Card title="Customer Segments">
            {segments.length > 0 ? (
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_260px]">
                <Chart height={300}>
                  <BarChart data={segments} layout="vertical" margin={{ left: 24, right: 12 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 12 }} />
                    <YAxis type="category" dataKey="segment" tick={{ fontSize: 12 }} width={124} />
                    <Tooltip formatter={(value, name) => [name === 'customer_count' ? formatCount(value) : currency(value), name === 'customer_count' ? 'Customers' : 'Revenue']} />
                    <Bar dataKey="customer_count" fill="#002970" radius={[0, 6, 6, 0]} />
                  </BarChart>
                </Chart>
                <div className="space-y-2">
                  {segments.map((segment) => (
                    <div key={segment.segment} className="rounded-md border border-slate-200 p-3">
                      <p className="font-medium text-slate-900">{segment.segment}</p>
                      <p className="text-sm text-slate-500">{formatCount(segment.customer_count)} customers · {segment.percentage}%</p>
                      <p className="text-xs text-slate-500">{currency(segment.total_revenue)} revenue</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyBlock message="No customer data available." />
            )}
          </Card>
        </CustomerSectionFrame>

        <CustomerSectionFrame state={state.value} onRetry={() => setRetryKey((key) => key + 1)} loadingLabel="Loading customer value...">
          {state.value.data && (
            <Card title="Customer Value">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
                <MiniStat label="Total Customer Revenue" value={currency(state.value.data.total_customer_revenue)} />
                <MiniStat label="Average Revenue / Customer" value={currency(state.value.data.average_revenue_per_customer)} />
                <MiniStat label="Median Revenue / Customer" value={currency(state.value.data.median_revenue_per_customer)} />
                <MiniStat label="Avg Transactions / Customer" value={state.value.data.average_transactions_per_customer} />
                <MiniStat label="Avg Units / Customer" value={state.value.data.average_units_per_customer} />
              </div>
            </Card>
          )}
        </CustomerSectionFrame>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <span className="text-sm font-medium text-slate-700">Segment filter</span>
        <select
          value={segmentFilter}
          onChange={(event) => setSegmentFilter(event.target.value)}
          className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-sky-500"
        >
          {segmentOptions.map((segment) => <option key={segment}>{segment}</option>)}
        </select>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <CustomerSectionFrame state={state.top} onRetry={() => setRetryKey((key) => key + 1)} loadingLabel="Loading top customers...">
          <CustomerTable
            title="Top Customers"
            rows={topRows}
            emptyMessage="No top customer data available."
            helper="Representative customer IDs"
          />
        </CustomerSectionFrame>

        <CustomerSectionFrame state={state.atRisk} onRetry={() => setRetryKey((key) => key + 1)} loadingLabel="Loading customers needing attention...">
          <CustomerTable
            title="Customers Needing Attention"
            rows={atRiskRows}
            emptyMessage="No customers needing attention for this filter."
            helper={state.atRisk.data?.explanation}
            showAttentionAction
          />
        </CustomerSectionFrame>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <CustomerSectionFrame state={state.demographics} onRetry={() => setRetryKey((key) => key + 1)} loadingLabel="Loading demographics...">
          <DemographicsCard data={state.demographics.data} />
        </CustomerSectionFrame>
        <CustomerSectionFrame state={state.loyalty} onRetry={() => setRetryKey((key) => key + 1)} loadingLabel="Loading loyalty insights...">
          <LoyaltyCard data={state.loyalty.data} />
        </CustomerSectionFrame>
      </div>

      <CustomerSectionFrame state={state.insights} onRetry={() => setRetryKey((key) => key + 1)} loadingLabel="Loading customer insights...">
        <Card title="Customer Insights">
          {state.insights.data?.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {state.insights.data.map((insight) => (
                <p key={insight.type} className="rounded-md bg-slate-50 p-3 text-sm text-slate-600">
                  <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-sky-600">Data Insight</span>
                  {insight.message}
                </p>
              ))}
            </div>
          ) : (
            <EmptyBlock message="No customer insights available." />
          )}
        </Card>
      </CustomerSectionFrame>
    </div>
  );
}

function CustomerSectionFrame({ state, onRetry, loadingLabel, children }) {
  if (state.loading) return <LoadingBlock label={loadingLabel} />;
  if (state.error) {
    return (
      <div className="space-y-3">
        <ErrorBlock message="Unable to load customer data." />
        <button onClick={onRetry} className="inline-flex items-center justify-center gap-2 rounded-md bg-[#002970] px-4 py-2 text-sm font-semibold text-white hover:bg-[#001f56]">
          <RefreshCw size={16} />
          Retry
        </button>
      </div>
    );
  }
  return children;
}

function CustomerTable({ title, rows, emptyMessage, helper, showAttentionAction = false }) {
  return (
    <Card title={title}>
      {helper && <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-sky-600">{helper}</p>}
      {rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
              <tr>
                <th className="py-2">Customer</th>
                <th>Spend</th>
                <th>Orders</th>
                <th>Units</th>
                <th>Last Purchase</th>
                <th>Segment</th>
                {showAttentionAction && <th>Action</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((customer) => (
                <tr key={customer.customer_id} className="border-b border-slate-100">
                  <td className="py-3 font-medium text-slate-900">{customer.customer_id}</td>
                  <td>{currency(customer.total_revenue)}</td>
                  <td>{formatCount(customer.transaction_count)}</td>
                  <td>{formatCount(customer.total_units)}</td>
                  <td>{customer.last_purchase_date}</td>
                  <td>{customer.segment}</td>
                  {showAttentionAction && (
                    <td>
                      <button className="rounded-md bg-sky-50 px-3 py-1.5 text-xs font-semibold text-sky-700">
                        Review customer
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyBlock message={emptyMessage} />
      )}
    </Card>
  );
}

function DemographicsCard({ data }) {
  const gender = Array.isArray(data?.gender_distribution) ? data.gender_distribution : [];
  const age = Array.isArray(data?.age_distribution) ? data.age_distribution : [];
  return (
    <Card title="Customer Demographics">
      <div className="grid gap-5 md:grid-cols-2">
        <DistributionList title="Gender Distribution" items={gender} />
        <DistributionList title="Age Distribution" items={age} />
      </div>
      <p className="mt-3 text-xs text-slate-500">Aggregates only. No demographic predictions or sensitive inferences are made.</p>
    </Card>
  );
}

function LoyaltyCard({ data }) {
  const items = data?.items || [];
  return (
    <Card title="Loyalty Insights">
      {items.length ? (
        <div className="space-y-3">
          {items.map((item) => (
            <div key={item.loyalty_status} className="rounded-md border border-slate-200 p-3">
              <p className="font-medium text-slate-900">{item.loyalty_status}</p>
              <p className="text-sm text-slate-500">{formatCount(item.customer_count)} customers · {currency(item.total_revenue)} revenue</p>
              <p className="text-xs text-slate-500">{currency(item.average_transaction_value)} average transaction value</p>
            </div>
          ))}
          {data.note && <p className="text-xs text-slate-500">{data.note}</p>}
        </div>
      ) : (
        <EmptyBlock message="No loyalty data available." />
      )}
    </Card>
  );
}

function DistributionList({ title, items }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold text-slate-800">{title}</h3>
      {items.length ? (
        <div className="space-y-2">
          {items.map((item) => (
            <div key={item.label}>
              <div className="mb-1 flex justify-between text-sm">
                <span className="text-slate-700">{item.label}</span>
                <span className="text-slate-500">{item.percentage}%</span>
              </div>
              <div className="h-2 rounded-full bg-slate-100">
                <div className="h-2 rounded-full bg-sky-500" style={{ width: `${item.percentage}%` }} />
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyBlock message="No customer data available." />
      )}
    </div>
  );
}

function formatCount(value) {
  return Number(value || 0).toLocaleString('en-IN');
}

function InventoryView({ inventory, onChanged }) {
  const [text, setText] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!text.trim()) return;
    setBusy(true);
    setResult(null);
    try {
      const response = await api.updateInventory(text);
      setResult(response);
      setText('');
      if (response.status === 'updated') onChanged();
    } catch (error) {
      setResult({ status: 'error', message: error.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_420px]">
      <Card title="AI Inventory Copilot">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead className="border-b border-slate-200 text-xs uppercase text-slate-500">
              <tr><th className="py-2">Product</th><th>Category</th><th>Stock</th><th>Reorder</th><th>Source</th></tr>
            </thead>
            <tbody>
              {inventory.items.map((item) => (
                <tr key={item.sku} className="border-b border-slate-100">
                  <td className="py-3 font-medium text-slate-900">{item.name}</td>
                  <td>{item.category.replace('_', ' ')}</td>
                  <td className={item.current_stock <= item.reorder_level ? 'font-semibold text-red-600' : ''}>{item.current_stock}</td>
                  <td>{item.reorder_level}</td>
                  <td className="text-slate-500">{item.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Voice/Text Stock Update">
        <div className="space-y-3">
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Example: received 24 Amul Milk"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
          <button onClick={submit} disabled={busy} className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-[#00baf2] px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
            <Bot size={16} />
            {busy ? 'Updating...' : 'Update Stock'}
          </button>
          {result && <p className="rounded-md bg-slate-50 p-3 text-sm text-slate-700">{result.message}</p>}
          {inventory.lowStock.length === 0 ? <EmptyBlock message="No low-stock items right now." /> : (
            <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-800">
              <div className="mb-1 flex items-center gap-2 font-semibold"><AlertTriangle size={16} /> Low stock</div>
              {inventory.lowStock.map((item) => item.name).join(', ')}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function InvoiceView() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function upload(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const response = await api.uploadInvoice(file);
      setItems(response.items);
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Invoice OCR / Stock Update">
      <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center hover:bg-slate-100">
        <Upload className="mb-3 text-sky-600" />
        <span className="font-medium text-slate-900">{busy ? 'Reading invoice...' : 'Upload supplier invoice image or PDF'}</span>
        <span className="mt-1 text-sm text-slate-500">Mock OCR fallback keeps the demo usable without external APIs.</span>
        <input type="file" accept="image/*,.pdf" onChange={upload} className="hidden" />
      </label>
      {error && <div className="mt-4"><ErrorBlock message={error} /></div>}
      {items.length > 0 && (
        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {items.map((item) => (
            <div key={item.name} className="rounded-md border border-slate-200 p-4">
              <p className="font-medium text-slate-900">{item.name}</p>
              <p className="text-sm text-slate-500">Qty {item.quantity} · {Math.round(item.confidence * 100)}% confidence</p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function AskView() {
  const [question, setQuestion] = useState('Why did sales change this week?');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);

  async function ask() {
    setBusy(true);
    setAnswer('');
    try {
      const response = await api.ask(question);
      setAnswer(response.answer);
    } catch (error) {
      setAnswer(`Could not reach AI service: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Ask Your Business AI">
      <div className="grid gap-4 md:grid-cols-[1fr_auto]">
        <input value={question} onChange={(event) => setQuestion(event.target.value)} className="rounded-md border border-slate-300 px-3 py-2 outline-none focus:border-sky-500" />
        <button onClick={ask} className="inline-flex items-center justify-center gap-2 rounded-md bg-[#002970] px-4 py-2 font-semibold text-white">
          <MessageSquareText size={16} />
          {busy ? 'Thinking...' : 'Ask'}
        </button>
      </div>
      {answer && <div className="mt-5 rounded-lg bg-sky-50 p-5 text-slate-800">{answer}</div>}
    </Card>
  );
}

function RecommendationsView({ recommendations }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {recommendations.map((item) => (
        <Card key={item.title}>
          <Sparkles className="mb-4 text-sky-600" />
          <h2 className="text-base font-semibold text-slate-950">{item.title}</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">{item.body}</p>
        </Card>
      ))}
    </div>
  );
}

function SettingsView() {
  return (
    <Card title="Merchant Settings / Demo Data">
      <div className="space-y-3 text-sm text-slate-600">
        <p>Dataset mode: representative synthetic Paytm-style merchant transactions.</p>
        <p>Product-level inventory is merchant-entered through text, voice-style updates, or invoice OCR review.</p>
        <p>AI provider and OCR provider are backend-only abstractions configured by environment variables.</p>
      </div>
    </Card>
  );
}

function Chart({ height, children }) {
  return <ResponsiveContainer width="100%" height={height}>{children}</ResponsiveContainer>;
}
