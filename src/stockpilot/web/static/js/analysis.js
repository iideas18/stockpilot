/* StockPilot analysis workbench */

document.getElementById('analysis-btn').addEventListener('click', () => runAnalysis());
document.getElementById('analysis-symbol').addEventListener('keydown', e => {
    if (e.key === 'Enter') runAnalysis();
});

document.getElementById('analysis-add-watchlist').addEventListener('click', () => {
    const symbol = document.getElementById('analysis-symbol').value.trim() || AppState.state.activeSymbol;
    if (!symbol) return toast('先选择一个标的', 'error');
    AppState.addWatchlist(symbol, { market: document.getElementById('analysis-market').value });
    toast('已加入关注列表', 'success');
});

document.getElementById('analysis-add-compare').addEventListener('click', () => {
    const symbol = document.getElementById('analysis-symbol').value.trim() || AppState.state.activeSymbol;
    if (!symbol) return toast('先选择一个标的', 'error');
    AppState.addCompareSymbol(symbol, { market: document.getElementById('analysis-market').value });
    toast('已加入对比列表', 'success');
});

document.getElementById('analysis-add-basket').addEventListener('click', () => {
    const symbol = document.getElementById('analysis-symbol').value.trim() || AppState.state.activeSymbol;
    if (!symbol) return toast('先选择一个标的', 'error');
    AppState.addPortfolioSymbol(symbol, { market: document.getElementById('analysis-market').value });
    toast('已加入组合候选', 'success');
});

document.getElementById('analysis-send-backtest').addEventListener('click', () => {
    const symbol = document.getElementById('analysis-symbol').value.trim() || AppState.state.activeSymbol;
    if (!symbol) return toast('先选择一个标的', 'error');
    document.getElementById('bt-symbol').value = symbol;
    document.getElementById('bt-market').value = document.getElementById('analysis-market').value;
    navigateTo('backtest');
});

document.getElementById('analysis-send-agent').addEventListener('click', () => {
    const symbol = document.getElementById('analysis-symbol').value.trim() || AppState.state.activeSymbol;
    if (!symbol) return toast('先选择一个标的', 'error');
    document.getElementById('agent-symbol').value = symbol;
    document.getElementById('agent-market').value = document.getElementById('analysis-market').value;
    navigateTo('agent');
});

function resetAnalysisPanels(patternMessage = '尚未加载') {
    document.getElementById('analysis-signal').classList.add('hidden');
    document.getElementById('analysis-signal').innerHTML = '';
    document.getElementById('analysis-indicators').classList.add('hidden');
    document.getElementById('indicator-scores').innerHTML = '';
    document.getElementById('analysis-patterns').innerHTML = `<div class="empty-state">${escapeHtml(patternMessage)}</div>`;
}

function renderAnalysisSignal(data, lastRow) {
    const signal = (data.signal || 'hold').toLowerCase();
    const signalLabel = signal === 'buy' ? '买入' : signal === 'sell' ? '卖出' : '持有';
    const signalClass = signal === 'buy' ? 'text-emerald-400' : signal === 'sell' ? 'text-rose-400' : 'text-amber-400';
    const indicatorScores = data.indicator_scores || {};
    const avg = Object.values(indicatorScores).reduce((a, b) => a + b, 0) / Math.max(Object.keys(indicatorScores).length, 1);
    const grid = document.getElementById('analysis-signal');
    grid.classList.remove('hidden');
    grid.innerHTML = `
        <div class="metric-card"><div class="metric-label">信号</div><div class="metric-value ${signalClass}">${signalLabel}</div></div>
        <div class="metric-card"><div class="metric-label">综合评分</div><div class="metric-value text-brand-400">${(data.combined_score ?? 0).toFixed(4)}</div></div>
        <div class="metric-card"><div class="metric-label">指标均值</div><div class="metric-value">${avg.toFixed(4)}</div></div>
        <div class="metric-card"><div class="metric-label">最新价</div><div class="metric-value">¥${Number(lastRow?.close || 0).toFixed(2)}</div></div>
    `;
}

function renderPatternSummary(summary) {
    const el = document.getElementById('analysis-patterns');
    if (!summary || !summary.patterns) {
        el.innerHTML = '<div class="empty-state">未获取到形态信息。</div>';
        return;
    }
    if (!summary.patterns.length) {
        el.innerHTML = '<div class="empty-state">最近未检测到明显 K 线形态。</div>';
        return;
    }
    el.innerHTML = `
        <div class="text-xs text-slate-400 mb-2">
            总数 ${summary.total_patterns} · 看多 ${summary.bullish_count} · 看空 ${summary.bearish_count}
        </div>
        <div class="space-y-2">
            ${summary.patterns.map(item => `
                <div class="compare-card">
                    <div class="flex justify-between items-center gap-3">
                        <span class="font-medium">${escapeHtml(item.pattern)}</span>
                        <span class="${item.signal === 'bullish' ? 'signal-buy' : 'signal-sell'}">${item.signal}</span>
                    </div>
                    <div class="context-item-sub mt-1">${escapeHtml(item.date)} · 强度 ${item.strength}</div>
                </div>`).join('')}
        </div>
    `;
}

function renderStaleNotice(status) {
    const grid = document.getElementById('analysis-signal');
    if (!grid || !status || status.status !== 'stale') return;
    const reason = status.degraded_reason || '数据源返回缓存副本';
    const source = status.source || 'cache';
    const notice = `<div class="metric-card col-span-full border border-amber-500/50 bg-amber-500/10 text-amber-200">
        <div class="metric-label">数据状态</div>
        <div class="text-sm">数据可能过期 · ${escapeHtml(source)} · ${escapeHtml(reason)}</div>
    </div>`;
    grid.innerHTML = notice + grid.innerHTML;
}

async function runAnalysis() {
    const symbol = document.getElementById('analysis-symbol').value.trim() || AppState.state.activeSymbol;
    if (!symbol) return toast('请输入股票代码', 'error');

    const market = document.getElementById('analysis-market').value;
    const days = document.getElementById('analysis-days').value;
    const chartEl = document.getElementById('analysis-chart');
    const patternsEl = document.getElementById('analysis-patterns');
    resetAnalysisPanels('正在加载形态信息...');
    chartEl.innerHTML = '<div class="text-center py-20 text-slate-500"><i class="fas fa-spinner fa-spin text-2xl"></i><p class="mt-2">加载中...</p></div>';

    try {
        const [data, patterns] = await Promise.all([
            api(`/stocks/${symbol}/chart-data?days=${days}&market=${market}`),
            api('/analysis/patterns', {
                method: 'POST',
                body: JSON.stringify({ symbol, market }),
            }),
        ]);

        AppState.setActiveSymbol(symbol, { market });
        document.getElementById('analysis-symbol').value = symbol;
        document.getElementById('analysis-market').value = market;
        document.getElementById('header-stock').classList.remove('hidden');
        document.getElementById('header-symbol').textContent = symbol;
        document.getElementById('header-name').textContent = '';

        const cleanData = data.data.map(row => Object.fromEntries(Object.entries(row).map(([k, v]) => [k, v === '' ? null : v])));
        renderAnalysisSignal(data, cleanData[cleanData.length - 1]);
        document.getElementById('analysis-indicators').classList.remove('hidden');
        document.getElementById('indicator-scores').innerHTML = Object.entries(data.indicator_scores || {}).map(([key, value]) => `
            <div class="metric-card">
                <div class="metric-label">${escapeHtml(key.toUpperCase())}</div>
                <div class="metric-value ${value > 0.6 ? 'text-emerald-400' : value < 0.4 ? 'text-rose-400' : 'text-amber-400'}">${Number(value).toFixed(2)}</div>
            </div>
        `).join('');
        renderPatternSummary(patterns.patterns || patterns);
        createKlineChart('analysis-chart', cleanData, symbol);

        const chartStatus = consumeDataStatus(data, { dedupeKey: `analysis-chart:${symbol}:${market}` });
        consumeDataStatus(patterns, { dedupeKey: `analysis-patterns:${symbol}:${market}` });
        const staleStatus =
            (chartStatus && chartStatus.status === 'stale' && chartStatus) ||
            (patterns && patterns.data_status && patterns.data_status.status === 'stale' && patterns.data_status) ||
            null;
        if (staleStatus) renderStaleNotice(staleStatus);
    } catch (e) {
        const message = formatApiError(e.detail || { message: e.message });
        const retryHint = e.detail && e.detail.retry_after_seconds
            ? `<div class="text-xs text-amber-300 mt-2">建议 ${e.detail.retry_after_seconds}s 后重试</div>`
            : '';
        resetAnalysisPanels(`加载失败: ${message}`);
        chartEl.innerHTML = `<div class="text-center py-20 text-rose-400">加载失败: ${escapeHtml(message)}${retryHint}</div>`;
        if (patternsEl) {
            patternsEl.innerHTML = `<div class="empty-state text-rose-400">加载失败: ${escapeHtml(message)}${retryHint}</div>`;
        }
        toast(message, 'error');
    }
}

window.runAnalysis = runAnalysis;
