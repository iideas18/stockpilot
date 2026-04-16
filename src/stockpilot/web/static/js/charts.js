/* StockPilot charts */

const CHART_LAYOUT = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'rgba(30,41,59,0.5)',
    font: { color: '#94a3b8', size: 11 },
    margin: { t: 30, r: 30, b: 40, l: 50 },
    xaxis: { gridcolor: 'rgba(71,85,105,0.3)', rangeslider: { visible: false } },
    yaxis: { gridcolor: 'rgba(71,85,105,0.3)' },
    legend: { orientation: 'h', y: 1.08, x: 0.5, xanchor: 'center', font: { size: 10 } },
};

const PLOTLY_CONFIG = { responsive: true, displayModeBar: true, modeBarButtonsToRemove: ['lasso2d', 'select2d'] };
const SERIES_COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#06b6d4'];

function createKlineChart(container, data, symbol) {
    const dates = data.map(d => d.date);
    const traces = [
        {
            type: 'candlestick',
            x: dates,
            open: data.map(d => d.open),
            high: data.map(d => d.high),
            low: data.map(d => d.low),
            close: data.map(d => d.close),
            name: 'K线',
            increasing: { line: { color: '#ef5350' } },
            decreasing: { line: { color: '#26a69a' } },
            xaxis: 'x',
            yaxis: 'y',
        },
    ];

    const maColors = { ma_5: '#f59e0b', ma_10: '#3b82f6', ma_20: '#8b5cf6', ma_60: '#22c55e' };
    for (const [key, color] of Object.entries(maColors)) {
        const vals = data.map(d => d[key] ?? null);
        if (vals.some(v => v != null)) {
            traces.push({
                type: 'scatter',
                mode: 'lines',
                x: dates,
                y: vals,
                name: key.toUpperCase().replace('_', ''),
                line: { width: 1, color },
                xaxis: 'x',
                yaxis: 'y',
            });
        }
    }

    const bollUpper = data.map(d => d.boll_upper ?? null);
    const bollLower = data.map(d => d.boll_lower ?? null);
    if (bollUpper.some(v => v != null)) {
        traces.push({
            type: 'scatter',
            mode: 'lines',
            x: dates,
            y: bollUpper,
            name: 'BOLL上',
            line: { width: 0.7, color: 'rgba(168,85,247,0.45)', dash: 'dot' },
            xaxis: 'x',
            yaxis: 'y',
        });
        traces.push({
            type: 'scatter',
            mode: 'lines',
            x: dates,
            y: bollLower,
            name: 'BOLL下',
            line: { width: 0.7, color: 'rgba(168,85,247,0.45)', dash: 'dot' },
            fill: 'tonexty',
            fillcolor: 'rgba(168,85,247,0.04)',
            xaxis: 'x',
            yaxis: 'y',
        });
    }

    traces.push({
        type: 'bar',
        x: dates,
        y: data.map(d => d.volume),
        name: '成交量',
        marker: { color: data.map(d => d.close >= d.open ? '#ef5350' : '#26a69a') },
        xaxis: 'x2',
        yaxis: 'y2',
    });

    if (data.some(d => d.macd != null)) {
        traces.push({
            type: 'scatter',
            mode: 'lines',
            x: dates,
            y: data.map(d => d.macd ?? null),
            name: 'MACD',
            line: { width: 1, color: '#3b82f6' },
            xaxis: 'x3',
            yaxis: 'y3',
        });
        traces.push({
            type: 'scatter',
            mode: 'lines',
            x: dates,
            y: data.map(d => d.macd_signal ?? null),
            name: 'Signal',
            line: { width: 1, color: '#f59e0b' },
            xaxis: 'x3',
            yaxis: 'y3',
        });
        traces.push({
            type: 'bar',
            x: dates,
            y: data.map(d => d.macd_hist ?? null),
            name: 'Hist',
            marker: { color: data.map(d => (d.macd_hist ?? 0) >= 0 ? '#ef5350' : '#26a69a') },
            xaxis: 'x3',
            yaxis: 'y3',
        });
    }

    Plotly.newPlot(container, traces, {
        ...CHART_LAYOUT,
        height: 620,
        grid: { rows: 3, columns: 1, subplots: [['xy'], ['x2y2'], ['x3y3']], roworder: 'top to bottom' },
        xaxis: { ...CHART_LAYOUT.xaxis, domain: [0, 1], anchor: 'y' },
        yaxis: { ...CHART_LAYOUT.yaxis, domain: [0.42, 1], title: '价格' },
        xaxis2: { ...CHART_LAYOUT.xaxis, domain: [0, 1], anchor: 'y2', showticklabels: false },
        yaxis2: { ...CHART_LAYOUT.yaxis, domain: [0.22, 0.38], title: '成交量' },
        xaxis3: { ...CHART_LAYOUT.xaxis, domain: [0, 1], anchor: 'y3' },
        yaxis3: { ...CHART_LAYOUT.yaxis, domain: [0, 0.18], title: 'MACD' },
        title: { text: `${symbol} K线工作台`, font: { size: 14 } },
    }, PLOTLY_CONFIG);
}

function createLineComparisonChart(container, series, title, yTitle = '数值') {
    const traces = series.map((item, idx) => ({
        type: 'scatter',
        mode: 'lines',
        x: item.x,
        y: item.y,
        name: item.name,
        line: { width: 2, color: item.color || SERIES_COLORS[idx % SERIES_COLORS.length] },
    }));

    Plotly.newPlot(container, traces, {
        ...CHART_LAYOUT,
        height: 360,
        title: { text: title, font: { size: 14 } },
        yaxis: { ...CHART_LAYOUT.yaxis, title: yTitle },
    }, PLOTLY_CONFIG);
}

function createEquityCurve(container, dates, equity, initialCapital) {
    return createLineComparisonChart(
        container,
        [{ name: '组合净值', x: dates, y: equity, color: '#3b82f6' }],
        '资金曲线',
        '净值 (¥)',
    );
}

function createEquityComparison(container, runs, initialCapital) {
    const series = runs.map((run, idx) => ({
        name: run.label || `${run.symbol} · ${run.strategy}`,
        x: run.dates,
        y: run.equity_curve,
        color: SERIES_COLORS[idx % SERIES_COLORS.length],
    }));
    return createLineComparisonChart(container, series, '多组回测对比', '净值 (¥)');
}

function createPieChart(container, labels, values, title) {
    Plotly.newPlot(container, [{
        type: 'pie',
        labels,
        values,
        hole: 0.45,
        textinfo: 'label+percent',
        marker: { colors: SERIES_COLORS },
        textfont: { color: '#e2e8f0', size: 11 },
    }], {
        ...CHART_LAYOUT,
        height: 320,
        title: { text: title || '', font: { size: 13 } },
    }, PLOTLY_CONFIG);
}
