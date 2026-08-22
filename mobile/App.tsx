import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, View } from 'react-native';
import { useState } from 'react';
import { BottomNavigation, Tab } from './components/BottomNavigation';
import { BusinessOverviewScreen } from './screens/BusinessOverviewScreen';
import { InventoryAiScreen } from './screens/InventoryAiScreen';
import { ForecastingScreen } from './screens/ForecastingScreen';
import { CustomersScreen } from './screens/CustomersScreen';
import { AskAiScreen } from './screens/AskAiScreen';
import { MorePage, MoreScreen } from './screens/MoreScreen';

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('Home');
  const [morePage, setMorePage] = useState<MorePage>('menu');
  const openMore = (page: MorePage) => { setMorePage(page); setActiveTab('More'); };
  const screens = { Home: <BusinessOverviewScreen onNavigate={setActiveTab} onOpenMore={openMore} />, Inventory: <InventoryAiScreen />, Forecast: <ForecastingScreen />, Customers: <CustomersScreen />, AskAI: <AskAiScreen />, More: <MoreScreen initialPage={morePage} /> };
  return <SafeAreaView style={styles.safeArea}><StatusBar style="dark" /><View style={styles.content}>{screens[activeTab]}</View><BottomNavigation activeTab={activeTab} onChange={setActiveTab} /></SafeAreaView>;
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#F6F8FA' },
  content: { flex: 1 },
});
