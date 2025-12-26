import { createChart, ColorType, CandlestickSeries, type IChartApi, type ISeriesApi, type Time } from 'lightweight-charts';
import React, { useEffect, useRef } from 'react';

interface Props {
    symbol: string;
    tf: string;
}

export const TVChart: React.FC<Props> = ({ symbol, tf }) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const wsRef = useRef<WebSocket | null>(null);

    // Initial Data Fetch
    useEffect(() => {
        if (!chartContainerRef.current) return;

        // 1. Create Chart
        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: '#1E1E1E' },
                textColor: '#DDD',
            },
            grid: {
                vertLines: { color: '#2B2B2B' },
                horzLines: { color: '#2B2B2B' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 500, // Fixed height or dynamic
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
            },
        });
        chartRef.current = chart;

        const candlestickSeries = chart.addSeries(CandlestickSeries, {
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderVisible: false,
            wickUpColor: '#26a69a',
            wickDownColor: '#ef5350',
        });
        candleSeriesRef.current = candlestickSeries;

        // 2. Fetch History
        const fetchHistory = async () => {
            try {
                const res = await fetch(`/api/markets/${symbol}/candles?tf=${tf}&limit=1000`);
                if (!res.ok) throw new Error("Failed to fetch history");
                const data = await res.json();

                // Sort and Format
                const formatted = data.map((d: any) => {
                    // Check if time is ISO string or timestamp
                    let timeVal = d.time;
                    if (typeof timeVal === 'string') {
                        timeVal = new Date(timeVal).getTime() / 1000;
                    } else if (typeof timeVal === 'number' && timeVal > 2000000000) {
                        // milliseconds
                        timeVal = timeVal / 1000;
                    }
                    return {
                        time: timeVal as Time,
                        open: d.open,
                        high: d.high,
                        low: d.low,
                        close: d.close,
                    };
                }).sort((a: any, b: any) => a.time - b.time);

                candlestickSeries.setData(formatted);
                chart.timeScale().fitContent();
            } catch (e) {
                console.error(e);
            }
        };

        fetchHistory();

        // 3. Resize Observer
        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };
        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, [symbol, tf]); // Re-create chart on symbol change (simplest for now)

    // WebSocket Connection
    useEffect(() => {
        // Close previous
        if (wsRef.current) {
            wsRef.current.close();
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host; // includes port
        // If running vite dev server, we usually proxy /api to backend, 
        // but ws might need explicit url if proxy isn't setting upgrade headers correctly,
        // or we just assume vite proxy handles ws.
        // Let's try relative path first.
        const wsUrl = `${protocol}//${host}/ws/markets/${symbol}?tf=${tf}`;

        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            console.log(`WS Connected: ${symbol}`);
        };

        ws.onmessage = (event) => {
            if (!candleSeriesRef.current) return;
            try {
                const data = JSON.parse(event.data);
                // Format
                const candle = {
                    time: data.time as Time,
                    open: data.open,
                    high: data.high,
                    low: data.low,
                    close: data.close,
                };
                candleSeriesRef.current.update(candle);
            } catch (e) {
                console.error("WS Parse error", e);
            }
        };

        return () => {
            ws.close();
        };
    }, [symbol, tf]);

    return (
        <div className="relative w-full h-[500px]" ref={chartContainerRef}>
            {/* Overlay for drawings could go here */}
            {/* <div className="absolute top-0 left-0 z-10 p-2 text-white">Overlay</div> */}
        </div>
    );
};
