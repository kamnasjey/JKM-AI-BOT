import { useState, useEffect } from 'react';
import { ChartBoard } from './components/ChartBoard';
import { SignalDetail } from './pages/SignalDetail';
import { SignalsList } from './pages/SignalsList';
import './App.css';

function App() {
  const [symbols, setSymbols] = useState<string[]>([]);
  const [activeSymbol, setActiveSymbol] = useState<string>("EURUSD");
  const [view, setView] = useState<'chart' | 'signals' | 'signal_detail'>('chart');
  const [activeSignalId, setActiveSignalId] = useState<string | null>(null);
  // const [activeTf, setActiveTf] = useState<string>("5m"); // Removed as per instruction

  useEffect(() => {
    fetch('/api/markets/symbols')
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data) && data.length > 0) {
          setSymbols(data);
          setActiveSymbol(data[0]);
        }
      })
      .catch(console.error);
  }, []);

  return (
    <div className="flex flex-col h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="flex items-center gap-4 p-4 bg-gray-800 border-b border-gray-700">
        <h1 className="text-xl font-bold text-yellow-500">JKM Trading AI</h1>

        <button
          className={`px-3 py-1 rounded border ${view === 'chart' ? 'bg-yellow-500 text-black border-yellow-500' : 'bg-gray-700 border-gray-600'}`}
          onClick={() => setView('chart')}
        >
          Chart
        </button>
        <button
          className={`px-3 py-1 rounded border ${view === 'signals' || view === 'signal_detail' ? 'bg-yellow-500 text-black border-yellow-500' : 'bg-gray-700 border-gray-600'}`}
          onClick={() => setView('signals')}
        >
          Signals
        </button>

        {/* Symbol Selector */}
        {view === 'chart' && (
          <select
            className="p-2 bg-gray-700 rounded border border-gray-600 focus:outline-none focus:border-yellow-500"
            value={activeSymbol}
            onChange={(e) => setActiveSymbol(e.target.value)}
          >
            {symbols.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        )}

        {/* TF Selector (Fixed for now as per req 5m only base) */}
        {/* Replaced the dynamic TF selector with a fixed 5m button */}
        {view === 'chart' && (
          <button className="px-3 py-1 bg-yellow-500 text-black font-semibold rounded">
            5m
          </button>
        )}
      </header>

      {/* Main Content */}
      <main className="flex-1 flex overflow-hidden">
        {view === 'chart' && (
          <div className="flex-1 relative">
            <ChartBoard symbol={activeSymbol} />
          </div>
        )}

        {view === 'signals' && (
          <div className="flex-1 overflow-auto">
            <SignalsList
              onOpen={(id) => {
                setActiveSignalId(id);
                setView('signal_detail');
              }}
            />
          </div>
        )}

        {view === 'signal_detail' && activeSignalId && (
          <div className="flex-1 overflow-hidden">
            <SignalDetail
              signalId={activeSignalId}
              onBack={() => {
                setView('signals');
              }}
            />
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
