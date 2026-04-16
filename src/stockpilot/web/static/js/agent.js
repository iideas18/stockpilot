/* StockPilot agent workspace */

document.getElementById('agent-btn').addEventListener('click', runAgentAnalysis);
document.getElementById('agent-use-active').addEventListener('click', () => {
    if (!AppState.state.activeSymbol) return toast('先选择一个标的', 'error');
    document.getElementById('agent-symbol').value = AppState.state.activeSymbol;
    document.getElementById('agent-market').value = AppState.state.activeMarket || 'a_share';
});

async function runAgentAnalysis() {
    const symbol = document.getElementById('agent-symbol').value.trim() || AppState.state.activeSymbol;
    if (!symbol) return toast('请输入股票代码', 'error');

    const market = document.getElementById('agent-market').value;
    const debate = document.getElementById('agent-debate').checked;
    const personaKeys = Array.from(document.querySelectorAll('#agent-personas .persona-chip.selected')).map(el => el.dataset.key);
    if (!personaKeys.length) return toast('请至少选择一个人格', 'error');

    document.getElementById('agent-results').classList.add('hidden');
    document.getElementById('agent-loading').classList.remove('hidden');

    try {
        const data = await api('/agents/analyze', {
            method: 'POST',
            body: JSON.stringify({
                ticker: symbol,
                market,
                enable_personas: true,
                enable_debate: debate,
                persona_keys: personaKeys,
            }),
        });

        AppState.setActiveSymbol(symbol, { market });
        AppState.pushAgentSession({
            symbol,
            summary: (data.final_decision || data.risk_assessment || 'Agent run completed').slice(0, 80),
        });

        const personas = Object.entries(data.persona_analyses || {});
        const resultsEl = document.getElementById('agent-results');
        resultsEl.classList.remove('hidden');
        resultsEl.innerHTML = `
            <div class="metric-grid">
                <div class="metric-card"><div class="metric-label">人格数量</div><div class="metric-value text-brand-400">${personas.length}</div></div>
                <div class="metric-card"><div class="metric-label">风险辩论</div><div class="metric-value ${debate ? 'text-amber-400' : 'text-slate-400'}">${debate ? '开启' : '关闭'}</div></div>
                <div class="metric-card"><div class="metric-label">辩论轮次</div><div class="metric-value">${data.debate_history?.length || 0}</div></div>
            </div>
            <div class="card">
                <h3 class="text-lg font-semibold mb-3">分析时间线</h3>
                <div class="timeline">
                    <div class="timeline-step">
                        <div class="timeline-step-title">1. 最终决策</div>
                        <div class="timeline-step-body">${escapeHtml(data.final_decision || '未返回最终决策')}</div>
                    </div>
                    <div class="timeline-step">
                        <div class="timeline-step-title">2. 风险评估</div>
                        <div class="timeline-step-body">${escapeHtml(data.risk_assessment || '未返回风险评估')}</div>
                    </div>
                    <div class="timeline-step">
                        <div class="timeline-step-title">3. 技术/基本面总结</div>
                        <div class="timeline-step-body">${escapeHtml(
                            typeof data.technical_analysis === 'string'
                                ? data.technical_analysis
                                : JSON.stringify(data.technical_analysis || {}, null, 2)
                        )}</div>
                    </div>
                </div>
            </div>
            <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
                ${personas.map(([name, analysis]) => `
                    <div class="card">
                        <details open>
                            <summary class="cursor-pointer font-semibold text-purple-300">${escapeHtml(name)}</summary>
                            <div class="timeline-step-body mt-3">${escapeHtml(analysis)}</div>
                        </details>
                    </div>`).join('')}
            </div>
            <div class="card">
                <h3 class="text-lg font-semibold mb-3">辩论记录</h3>
                ${(data.debate_history && data.debate_history.length) ? data.debate_history.map(round => `
                    <details class="mb-2">
                        <summary class="cursor-pointer text-slate-300">第 ${round.round || '?'} 轮</summary>
                        <div class="grid grid-cols-1 gap-2 mt-3 text-sm">
                            <div class="compare-card"><div class="font-medium text-emerald-300 mb-1">激进</div>${escapeHtml(round.aggressive || '')}</div>
                            <div class="compare-card"><div class="font-medium text-sky-300 mb-1">保守</div>${escapeHtml(round.conservative || '')}</div>
                            <div class="compare-card"><div class="font-medium text-slate-300 mb-1">中立</div>${escapeHtml(round.neutral || '')}</div>
                        </div>
                    </details>`).join('') : '<div class="empty-state">没有辩论记录。</div>'}
            </div>
        `;

        toast('Agent 分析完成', 'success');
    } catch (e) {
        document.getElementById('agent-results').classList.remove('hidden');
        document.getElementById('agent-results').innerHTML = `<div class="card text-rose-400">${escapeHtml(e.message)}</div>`;
        toast(e.message, 'error');
    } finally {
        document.getElementById('agent-loading').classList.add('hidden');
    }
}
