/* StockPilot backtest studio */

document.getElementById('bt-btn').addEventListener('click', runBacktest);
document.getElementById('bt-compare-history').addEventListener('click', () => {
    const runs = AppState.state.backtestHistory
        .filter(run => Array.isArray(run?.dates) && Array.isArray(run?.equity_curve))
        .slice(0, 4);
    if (runs.length < 2) return toast('至少需要两次回测历史才能叠加', 'error');
    const bestReturn = Math.max(...runs.map(run => Number(run.metrics?.total_return_pct ?? 0)));
    document.getElementById('bt-loading').classList.add('hidden');
    document.getElementById('bt-results').classList.remove('hidden');
    document.getElementById('bt-metrics').innerHTML = `
        <div class="metric-card">
            <div class="metric-label">对比组数</div>
            <div class="metric-value text-brand-400">${runs.length}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">最佳总收益</div>
            <div class="metric-value ${bestReturn >= 0 ? 'text-emerald-400' : 'text-rose-400'}">${bestReturn.toFixed(2)}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">最近回测</div>
            <div class="metric-value text-slate-200">${escapeHtml(runs[0].label || `${runs[0].symbol} · ${runs[0].strategy}`)}</div>
        </div>
    `;
    document.getElementById('bt-trades').innerHTML = '<div class="empty-state">已叠加最近回测资金曲线；点击右侧历史记录可查看单次成交明细。</div>';
    renderBacktestHistoryList();
    createEquityComparison('bt-equity-chart', runs, runs[0].initial_capital || 1000000);
});
document.getElementById('bt-preset').addEventListener('change', e => {
    const preset = e.target.value;
    if (preset === 'swing') {
        document.getElementById('bt-days').value = 120;
        document.getElementById('bt-capital').value = 300000;
    } else if (preset === 'trend') {
        document.getElementById('bt-days').value = 365;
        document.getElementById('bt-capital').value = 1000000;
    } else if (preset === 'long') {
        document.getElementById('bt-days').value = 730;
        document.getElementById('bt-capital').value = 1000000;
    }
});

function renderBacktestHistoryList() {
    const historyEl = document.getElementById('bt-history');
    const runs = AppState.state.backtestHistory;
    if (!runs.length) {
        historyEl.innerHTML = '<div class="empty-state">运行回测后会出现在这里。</div>';
        return;
    }
    historyEl.innerHTML = runs.map((run, idx) => `
        <div class="history-item">
            <div class="context-item-main">
                <button class="action-link font-medium bt-history-open" data-index="${idx}">
                    ${escapeHtml(run.symbol)} · ${escapeHtml(run.strategy)}
                </button>
                <div class="context-item-sub">${Number(run.metrics?.total_return_pct ?? 0).toFixed(2)}% · ${new Date(run.createdAt).toLocaleString()}</div>
            </div>
        </div>
    `).join('');
    historyEl.querySelectorAll('.bt-history-open').forEach(btn => btn.addEventListener('click', () => {
        const run = AppState.state.backtestHistory[Number(btn.dataset.index)];
        if (run) renderBacktestResult(run, true);
    }));
}

function renderBacktestResult(data, fromHistory = false) {
    document.getElementById('bt-loading').classList.add('hidden');
    document.getElementById('bt-results').classList.remove('hidden');
    const capital = data.initial_capital || Number(document.getElementById('bt-capital').value) || 1000000;
    const m = data.metrics;
    document.getElementById('bt-metrics').innerHTML = [
        ['总收益', `${m.total_return_pct > 0 ? '+' : ''}${Number(m.total_return_pct).toFixed(2)}%`, m.total_return_pct > 0 ? 'text-emerald-400' : 'text-rose-400'],
        ['年化收益', `${Number(m.annual_return_pct).toFixed(2)}%`, m.annual_return_pct > 0 ? 'text-emerald-400' : 'text-rose-400'],
        ['夏普比率', Number(m.sharpe_ratio).toFixed(3), 'text-brand-400'],
        ['最大回撤', `${Number(m.max_drawdown_pct).toFixed(2)}%`, 'text-amber-400'],
        ['交易次数', String(m.total_trades), 'text-slate-200'],
        ['胜率', `${(Number(m.win_rate) * 100).toFixed(1)}%`, 'text-slate-200'],
        ['期末资金', `¥${Number(m.final_capital).toLocaleString()}`, Number(m.final_capital) > capital ? 'text-emerald-400' : 'text-rose-400'],
        ['策略', escapeHtml(data.strategy), 'text-slate-200'],
    ].map(([label, value, color]) => `
        <div class="metric-card">
            <div class="metric-label">${label}</div>
            <div class="metric-value ${color}">${value}</div>
        </div>`).join('');

    createEquityCurve('bt-equity-chart', data.dates, data.equity_curve, capital);
    document.getElementById('bt-trades').innerHTML = data.trades?.length ? `
        <table class="data-table">
            <thead><tr><th>日期</th><th>动作</th><th>数量</th><th>价格</th><th>原因</th></tr></thead>
            <tbody>
                ${data.trades.slice(-60).map(t => `
                    <tr>
                        <td>${escapeHtml(t.date)}</td>
                        <td class="${t.action === 'buy' ? 'text-emerald-400' : 'text-rose-400'}">${escapeHtml(t.action)}</td>
                        <td>${t.quantity}</td>
                        <td>¥${Number(t.price).toFixed(2)}</td>
                        <td class="text-slate-500">${escapeHtml(t.reason)}</td>
                    </tr>`).join('')}
            </tbody>
        </table>` : '<div class="empty-state">没有成交记录。</div>';

    renderBacktestHistoryList();
}

async function runBacktest() {
    const symbol = document.getElementById('bt-symbol').value.trim() || AppState.state.activeSymbol;
    if (!symbol) return toast('请输入股票代码', 'error');

    const strategy = document.getElementById('bt-strategy').value;
    const market = document.getElementById('bt-market').value;
    const days = Number(document.getElementById('bt-days').value) || 365;
    const capital = Number(document.getElementById('bt-capital').value) || 1000000;
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - days);
    const iso = d => d.toISOString().slice(0, 10);

    document.getElementById('bt-results').classList.add('hidden');
    document.getElementById('bt-loading').classList.remove('hidden');
    try {
        const data = await api('/backtest/run', {
            method: 'POST',
            body: JSON.stringify({
                symbol,
                market,
                strategy,
                start_date: iso(start),
                end_date: iso(end),
                initial_capital: capital,
            }),
        });
        data.initial_capital = capital;
        AppState.setActiveSymbol(symbol, { market });
        AppState.pushBacktestRun({
            ...data,
            initial_capital: capital,
            label: `${symbol} · ${strategy}`,
        });
        renderBacktestResult(data);
        toast('回测完成', 'success');
    } catch (e) {
        document.getElementById('bt-loading').classList.add('hidden');
        toast(e.message, 'error');
    }
}

window.renderBacktestResult = renderBacktestResult;
renderBacktestHistoryList();
