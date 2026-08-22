import { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { AppHeader, PrimaryButton } from '../components/ui';
import { colors, radius, spacing } from '../constants/theme';
import { api } from '../services/api';
import type { InventoryDataSummary, InventoryItem, InventoryRisk } from '../types/business';

type LoadState = 'loading' | 'success' | 'empty' | 'error';
type Filter = 'All' | 'Low Stock' | 'Critical' | 'Healthy' | 'Overstock';
const filters: Filter[] = ['All', 'Low Stock', 'Critical', 'Healthy', 'Overstock'];

const statusOf = (item: InventoryItem): Exclude<Filter, 'All'> => {
  if (item.current_stock === 0) return 'Critical';
  if (item.current_stock <= item.reorder_level) return 'Low Stock';
  return 'Healthy';
};

export function InventoryAiScreen() {
  const [state, setState] = useState<LoadState>('loading');
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [summary, setSummary] = useState<InventoryDataSummary>();
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<Filter>('All');
  const [selected, setSelected] = useState<InventoryItem>();
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true); else setState('loading');
    try {
      const [inventory, dataSummary] = await Promise.all([api.getInventory(), api.getInventoryDataSummary().catch(() => undefined)]);
      setItems(inventory.items);
      setSummary(dataSummary);
      setState(inventory.items.length ? 'success' : 'empty');
    } catch { setState('error'); } finally { setRefreshing(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const visibleItems = useMemo(() => items.filter(item => {
    const matchesSearch = item.name.toLowerCase().includes(query.trim().toLowerCase());
    const status = statusOf(item);
    return matchesSearch && (filter === 'All' || filter === status || (filter === 'Overstock' && false));
  }), [filter, items, query]);

  if (selected) return <ProductDetails item={selected} onBack={() => setSelected(undefined)} />;
  if (state === 'loading') return <Loading />;
  if (state === 'error') return <StateMessage title="Inventory data is temporarily unavailable." button="Retry" onPress={() => void load()} />;
  if (state === 'empty') return <StateMessage title="Your inventory looks good." message="There are no inventory items to review." button="Refresh" onPress={() => void load()} />;

  const lowStock = items.filter(item => item.current_stock <= item.reorder_level).length;
  const critical = items.filter(item => statusOf(item) === 'Critical').length;
  return <ScrollView contentContainerStyle={s.page} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void load(true)} tintColor={colors.primary} />}>
    <AppHeader title="Inventory AI" subtitle="Know what to restock before you run out." />
    <View style={s.body}>
      <View style={s.summary}><SummaryCard label="Low Stock" value={lowStock} /><SummaryCard label="Critical Stock" value={critical} danger /><SummaryCard label="Overstock" value="--" /><SummaryCard label="Recommended Restocks" value="--" /></View>
      <Text style={s.note}>Overstock and reorder quantities need a backend recommendation feed.</Text>
      <Text style={s.section}>AI Inventory Alerts</Text>
      <Alerts risks={summary?.potential_inventory_risk} />
      <Text style={s.section}>Recommended Restocks</Text>
      <View style={s.emptyCard}><Text style={s.emptyTitle}>No restock recommendations available</Text><Text style={s.muted}>The current backend does not return recommended order quantities or AI reasons yet.</Text></View>
      <Text style={s.section}>Your inventory</Text>
      <TextInput accessibilityLabel="Search inventory" placeholder="Search products" value={query} onChangeText={setQuery} style={s.search} />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filters}>{filters.map(option => <Pressable key={option} accessibilityRole="button" onPress={() => setFilter(option)} style={[s.filter, filter === option && s.filterActive]}><Text style={[s.filterText, filter === option && s.filterTextActive]}>{option}</Text></Pressable>)}</ScrollView>
      {visibleItems.length ? visibleItems.map(item => <ProductRow key={item.id} item={item} onPress={() => setSelected(item)} />) : <View style={s.emptyCard}><Text style={s.muted}>No products match this search or filter.</Text></View>}
    </View>
  </ScrollView>;
}

function Loading() { return <View style={s.state}><ActivityIndicator size="large" color={colors.primary} /><Text style={s.muted}>Loading inventory…</Text></View>; }
function StateMessage({ title, message, button, onPress }: { title: string; message?: string; button: string; onPress: () => void }) { return <View style={s.state}><Text style={s.stateTitle}>{title}</Text>{message && <Text style={s.muted}>{message}</Text>}<PrimaryButton label={button} onPress={onPress} /></View>; }
function SummaryCard({ label, value, danger }: { label: string; value: number | string; danger?: boolean }) { return <View style={s.summaryCard}><Text style={s.summaryLabel}>{label}</Text><Text style={[s.summaryValue, danger && s.dangerText]}>{value}</Text></View>; }
function Alerts({ risks }: { risks?: InventoryRisk[] }) { if (!risks?.length) return <View style={s.emptyCard}><Text style={s.muted}>No inventory alerts are available from the backend.</Text></View>; return <View style={s.alertList}>{risks.slice(0, 3).map((risk, index) => <View key={`${risk.Brand ?? risk.Category ?? 'risk'}-${index}`} style={s.alert}><Text style={s.alertTitle}>{risk.Brand ?? risk.Category ?? 'Inventory item requires attention'}</Text><Text style={s.muted}>{risk.Stock_On_Hand !== undefined && risk.Reorder_Level !== undefined ? `Current stock: ${risk.Stock_On_Hand} · Reorder level: ${risk.Reorder_Level}` : 'Inventory risk reported by the backend.'}</Text></View>)}</View>; }
function ProductRow({ item, onPress }: { item: InventoryItem; onPress: () => void }) { const status = statusOf(item); return <Pressable accessibilityRole="button" onPress={onPress} style={s.product}><View style={s.productTop}><Text style={s.productName}>{item.name}</Text><Text style={[s.pill, status === 'Critical' ? s.critical : status === 'Low Stock' ? s.low : s.healthy]}>{status}</Text></View><Text style={s.muted}>Current stock: {item.current_stock}</Text><Text style={s.detail}>Reorder level: {item.reorder_level}</Text></Pressable>; }
function ProductDetails({ item, onBack }: { item: InventoryItem; onBack: () => void }) { const status = statusOf(item); return <ScrollView contentContainerStyle={s.page}><AppHeader title={item.name} subtitle="Inventory details" /><View style={s.body}><Pressable accessibilityRole="button" onPress={onBack} style={s.back}><Text style={s.backText}>← Back to inventory</Text></Pressable><ProductRow item={item} onPress={() => undefined} /><Detail label="Recent sales" value="--" /><Detail label="Demand trend" value="--" /><Detail label="Forecast" value="--" /><Detail label="Recommended reorder quantity" value="--" /><View style={s.emptyCard}><Text style={s.emptyTitle}>Why this recommendation?</Text><Text style={s.muted}>{status === 'Critical' || status === 'Low Stock' ? `Current stock (${item.current_stock}) is at or below the configured reorder level (${item.reorder_level}). No AI explanation was returned by the backend.` : 'No AI recommendation or explanation was returned by the backend.'}</Text></View></View></ScrollView>; }
function Detail({ label, value }: { label: string; value: string }) { return <View style={s.detailCard}><Text style={s.summaryLabel}>{label}</Text><Text style={s.detailValue}>{value}</Text></View>; }

const s = StyleSheet.create({ page: { paddingBottom: spacing.xl }, body: { paddingHorizontal: spacing.lg, gap: spacing.md }, state: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: spacing.xl, gap: spacing.md }, stateTitle: { color: colors.text, fontSize: 18, fontWeight: '800', textAlign: 'center' }, section: { color: colors.text, fontSize: 17, fontWeight: '800', marginTop: spacing.sm }, summary: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm }, summaryCard: { width: '48%', minHeight: 90, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.sm, justifyContent: 'space-between' }, summaryLabel: { color: colors.muted, fontSize: 12, fontWeight: '700' }, summaryValue: { color: colors.text, fontSize: 25, fontWeight: '800' }, dangerText: { color: colors.danger }, note: { color: colors.muted, fontSize: 12, lineHeight: 17 }, alertList: { gap: spacing.sm }, alert: { backgroundColor: '#FFF8E6', borderWidth: 1, borderColor: '#F3D98A', padding: spacing.md, borderRadius: radius.md, gap: 4 }, alertTitle: { color: colors.text, fontSize: 15, fontWeight: '800' }, emptyCard: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, gap: 5 }, emptyTitle: { color: colors.text, fontWeight: '800', fontSize: 15 }, muted: { color: colors.muted, fontSize: 13, lineHeight: 19 }, search: { minHeight: 48, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, paddingHorizontal: spacing.md, color: colors.text }, filters: { gap: spacing.sm }, filter: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, paddingVertical: 9, paddingHorizontal: 13, backgroundColor: colors.surface }, filterActive: { backgroundColor: colors.primary, borderColor: colors.primary }, filterText: { color: colors.muted, fontWeight: '700', fontSize: 13 }, filterTextActive: { color: '#FFF' }, product: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, gap: 5 }, productTop: { flexDirection: 'row', justifyContent: 'space-between', gap: spacing.sm }, productName: { flex: 1, color: colors.text, fontWeight: '800', fontSize: 16 }, pill: { alignSelf: 'flex-start', paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.sm, overflow: 'hidden', fontSize: 11, fontWeight: '800' }, critical: { backgroundColor: '#FFF0F0', color: colors.danger }, low: { backgroundColor: '#FFF8E6', color: colors.warning }, healthy: { backgroundColor: '#EAF7F0', color: colors.success }, detail: { color: colors.muted, fontSize: 12 }, back: { alignSelf: 'flex-start', paddingVertical: 4 }, backText: { color: colors.primary, fontWeight: '800' }, detailCard: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.md, flexDirection: 'row', justifyContent: 'space-between' }, detailValue: { color: colors.text, fontWeight: '800' } });
