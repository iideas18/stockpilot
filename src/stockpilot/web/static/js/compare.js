/* StockPilot compare lab */

document.getElementById('compare-btn').addEventListener('click', runCompare);
document.getElementById('compare-use-active').addEventListener('click', () => {
    if (!AppState.state.activeSymbol) return toast('先选择一个标的', 'error');
    const current = document.getElementById('compare-symbols').value.split(/[,，\s]+/).filter(Boolean);
    if (!current.includes(AppState.state.activeSymbol)) current.push(AppState.state.activeSymbol);
    document.getElementById('compare-symbols').value = current.join(', ');
});
document.getElementById('compare-use-basket').addEventListener('click', () => {
    const symbols = AppState.state.compareSymbols.length ? AppState.state.compareSymbols : AppState.state.portfolioBasket;
    if (!symbols.length) return toast('对比列表或组合候选为空', 'error');
    document.getElementById('compare-symbols').value = symbols.join(', ');
});

async function runCompare() {
    const symbols = document.getElementById('compare-symbols').value.split(/[,，\s]+/).filter(Boolean);
    if (symbols.length < 2) return toast('请输入至少 2 个股票代码', 'error');

    const market = document.getElementById('compare-market').value;
    const days = Number(document.getElementById('compare-days').value) || 120;
    const chartEl = document.getElementById('compare-chart');
    const cards = document.getElementById('compare-cards');
    chartEl.innerHTML = '<div class="text-center py-16 text-slate-500"><i class="fas fa-spinner fa-spin text-2xl"></i></div>';
    cards.innerHTML = '';

    try {
        const data = await api('/compare/symbols', {
            method: 'POST',
            body: JSON.stringify({ symbols, market, days }),
        });
        data.summaries.forEach(item => AppState.addCompareSymbol(item.symbol, { market }));

        createLineComparisonChart(
            'compare-chart',
            data.series.map(item => ({ name: item.symbol, x: item.dates, y: item.normalized })),
            '标准化收益对比（起点 = 100）',
            '标准化价格',
        );

        cards.innerHTML = data.summaries.map(item => {
            const signalClass = item.signal === 'buy' ? 'signal-buy' : item.signal === 'sell' ? 'signal-sell' : 'signal-hold';
            return `
                <div class="compare-card">
                    <div class="flex items-center justify-between mb-2">
                        <div class="text-lg font-semibold">${escapeHtml(item.symbol)}</div>
                        <span class="${signalClass}">${escapeHtml(item.signal.toUpperCase())}</span>
                    </div>
                    <div class="space-y-2 text-sm">
                        <div class="flex justify-between"><span class="text-slate-400">最新价</span><span>¥${Number(item.last_close).toFixed(2)}</span></div>
                        <div class="flex justify-between"><span class="text-slate-400">区间涨跌</span><span class="${item.change_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}">${item.change_pct.toFixed(2)}%</span></div>
                        <div class="flex justify-between"><span class="text-slate-400">综合评分</span><span class="text-brand-400">${Number(item.combined_score).toFixed(4)}</span></div>
                    </div>
                    <div class="quick-actions mt-3">
                        <button class="mini-button compare-activate" data-symbol="${item.symbol}">设为当前</button>
                        <button class="mini-button compare-basket" data-symbol="${item.symbol}">加入组合</button>
                    </div>
                </div>
            `;
        }).join('');

        cards.querySelectorAll('.compare-activate').forEach(btn => btn.addEventListener('click', () => {
            selectStock(btn.dataset.symbol, '', market, { navigate: false, run: false });
            toast(`已切换 ${btn.dataset.symbol}`, 'success');
        }));
        cards.querySelectorAll('.compare-basket').forEach(btn => btn.addEventListener('click', () => {
            AppState.addPortfolioSymbol(btn.dataset.symbol, { market });
            toast(`已把 ${btn.dataset.symbol} 加入组合候选`, 'success');
        }));
    } catch (e) {
        chartEl.innerHTML = `<div class="text-center py-16 text-rose-400">${escapeHtml(e.message)}</div>`;
        cards.innerHTML = `<div class="card text-rose-400 md:col-span-2 xl:col-span-4">${escapeHtml(e.message)}</div>`;
        toast(e.message, 'error');
    }
}
