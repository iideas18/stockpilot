/* StockPilot portfolio studio */

document.getElementById('pf-btn').addEventListener('click', runPortfolioOpt);
document.getElementById('pf-use-basket').addEventListener('click', () => {
    const symbols = AppState.state.portfolioBasket.length ? AppState.state.portfolioBasket : AppState.state.watchlist;
    if (!symbols.length) return toast('组合候选或关注列表为空', 'error');
    document.getElementById('pf-symbols').value = symbols.join(', ');
});

async function runPortfolioOpt() {
    const symbols = document.getElementById('pf-symbols').value.split(/[,，\s]+/).filter(Boolean);
    if (symbols.length < 2) return toast('请输入至少两个股票代码', 'error');

    const method = document.getElementById('pf-method').value;
    const capital = Number(document.getElementById('pf-capital').value) || 1000000;
    const riskFreeRate = Number(document.getElementById('pf-risk-free').value) || 0.03;
    const methods = ['max_sharpe', 'min_variance', 'risk_parity', 'equal_weight'];

    document.getElementById('pf-results').classList.add('hidden');
    document.getElementById('pf-loading').classList.remove('hidden');

    try {
        AppState.setPortfolioBasket(symbols);

        const responses = await Promise.all(methods.map(m => api('/portfolio/optimize', {
            method: 'POST',
            body: JSON.stringify({
                symbols,
                method: m,
                capital,
                days: 365,
                risk_free_rate: riskFreeRate,
            }),
        })));
        const selected = responses.find(item => item.method === method) || responses[0];

        const dataStatus = consumeDataStatus(selected, { dedupeKey: `portfolio:${symbols.join(',')}:${method}:${document.getElementById('pf-market') ? document.getElementById('pf-market').value : 'us'}` });

        document.getElementById('pf-results').classList.remove('hidden');
        createPieChart('pf-chart', Object.keys(selected.weights), Object.values(selected.weights), '配置比例');

        let staleNotice = '';
        if (dataStatus && dataStatus.status === 'stale') {
            const reason = dataStatus.degraded_reason || '数据源返回缓存副本';
            const source = dataStatus.source || 'cache';
            staleNotice = `<div class="metric-card border border-amber-500/50 bg-amber-500/10 text-amber-200 mb-3">
                <div class="metric-label">数据状态</div>
                <div class="text-sm">数据可能过期 · ${escapeHtml(source)} · ${escapeHtml(reason)}</div>
            </div>`;
        }

        document.getElementById('pf-metrics').innerHTML = staleNotice + `
            <div class="space-y-3 text-sm">
                <div class="flex justify-between"><span class="text-slate-400">优化方法</span><span class="font-medium">${escapeHtml(selected.method)}</span></div>
                <div class="flex justify-between"><span class="text-slate-400">预期收益</span><span class="font-medium ${selected.expected_return >= 0 ? 'text-emerald-400' : 'text-rose-400'}">${(selected.expected_return * 100).toFixed(2)}%</span></div>
                <div class="flex justify-between"><span class="text-slate-400">预期波动</span><span class="font-medium text-amber-400">${(selected.expected_volatility * 100).toFixed(2)}%</span></div>
                <div class="flex justify-between"><span class="text-slate-400">夏普比率</span><span class="font-medium text-brand-400">${Number(selected.sharpe_ratio).toFixed(4)}</span></div>
                <div class="flex justify-between"><span class="text-slate-400">无风险利率</span><span class="font-medium">${(selected.risk_free_rate * 100).toFixed(2)}%</span></div>
            </div>
        `;

        document.getElementById('pf-method-compare').innerHTML = responses.map(item => `
            <div class="metric-card">
                <div class="metric-label">${escapeHtml(item.method)}</div>
                <div class="metric-value text-brand-400">${Number(item.sharpe_ratio).toFixed(3)}</div>
                <div class="text-xs text-slate-400 mt-2">${(item.expected_return * 100).toFixed(1)}% / ${(item.expected_volatility * 100).toFixed(1)}%</div>
            </div>
        `).join('');

        document.getElementById('pf-allocations').innerHTML = `
            <table class="data-table">
                <thead><tr><th>股票</th><th>权重</th><th>金额</th></tr></thead>
                <tbody>
                    ${Object.entries(selected.allocations).map(([symbol, amount]) => `
                        <tr>
                            <td class="text-brand-400 font-mono">${escapeHtml(symbol)}</td>
                            <td>${(selected.weights[symbol] * 100).toFixed(1)}%</td>
                            <td>¥${Number(amount).toLocaleString()}</td>
                        </tr>`).join('')}
                </tbody>
            </table>
        `;

        toast('组合优化完成', 'success');
    } catch (e) {
        const message = formatApiError(e.detail || { message: e.message });
        const retryHint = e.detail && e.detail.retry_after_seconds
            ? `<div class="text-xs text-amber-300 mt-2">建议 ${e.detail.retry_after_seconds}s 后重试</div>`
            : '';
        document.getElementById('pf-results').classList.remove('hidden');
        const metrics = document.getElementById('pf-metrics');
        if (metrics) {
            metrics.innerHTML = `<div class="metric-card border border-rose-500/50 bg-rose-500/10 text-rose-200">
                <div class="metric-label">加载失败</div>
                <div class="text-sm">${escapeHtml(message)}${retryHint}</div>
            </div>`;
        }
        toast(message, 'error');
    } finally {
        document.getElementById('pf-loading').classList.add('hidden');
    }
}
