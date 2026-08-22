import { StatusBar } from 'expo-status-bar';
import { SafeAreaView, StyleSheet, View } from 'react-native';
import { useState } from 'react';
import { BottomNavigation, Route } from './components/BottomNavigation';
import { HomeScreen } from './screens/HomeScreen';
import { InventoryAiScreen } from './screens/InventoryAiScreen';
import { DemandForecastScreen } from './screens/DemandForecastScreen';
import { CustomersScreen } from './screens/CustomersScreen';
import { AskAiScreen } from './screens/AskAiScreen';
import { MorePage, MoreScreen } from './screens/MoreScreen';

export default function App() {
  const [activeTab, setActiveTab] = useState<Route>('Home');
  const [morePage, setMorePage] = useState<MorePage>('menu');
  const screens = { Home: <HomeScreen onNavigate={setActiveTab} />, Inventory: <InventoryAiScreen />, Forecast: <DemandForecastScreen />, Customers: <CustomersScreen />, AskAI: <AskAiScreen />, More: <MoreScreen initialPage={morePage} onNavigate={setActiveTab} /> };
  return <SafeAreaView style={styles.safeArea}><StatusBar style="dark" /><View style={styles.content}>{screens[activeTab]}</View><BottomNavigation activeTab={activeTab} onChange={setActiveTab} /></SafeAreaView>;
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: '#F6F8FA' },
  content: { flex: 1 },
});
