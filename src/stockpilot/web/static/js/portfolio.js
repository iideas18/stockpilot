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

        document.getElementById('pf-results').classList.remove('hidden');
        createPieChart('pf-chart', Object.keys(selected.weights), Object.values(selected.weights), '配置比例');

        document.getElementById('pf-metrics').innerHTML = `
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
        toast(e.message, 'error');
    } finally {
        document.getElementById('pf-loading').classList.add('hidden');
    }
}
