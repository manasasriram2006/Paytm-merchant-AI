export function LoadingBlock({ label = 'Loading latest business data...' }) {
  return <div className="rounded-lg border border-dashed border-slate-300 bg-white p-6 text-sm text-slate-500">{label}</div>;
}

export function ErrorBlock({ message = 'Something went wrong.' }) {
  return <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm text-red-700">{message}</div>;
}

export function EmptyBlock({ message = 'No data available yet.' }) {
  return <div className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-sm text-slate-500">{message}</div>;
}
