/* StockPilot agent workspace */

document.getElementById('agent-btn').addEventListener('click', runAgentAnalysis);
document.getElementById('agent-use-active').addEventListener('click', () => {
    if (!AppState.state.activeSymbol) return toast('先选择一个标的', 'error');
    document.getElementById('agent-symbol').value = AppState.state.activeSymbol;
    document.getElementById('agent-market').value = AppState.state.activeMarket || 'a_share';
});

// --- Signal / sentiment extraction --------------------------------------
// The backend returns free-form LLM text. We try to surface a few headline
// indicators by scanning the text for common Chinese / English signal words.
// These are best-effort hints, not authoritative.
function extractSignal(text) {
    if (!text || typeof text !== 'string') return null;
    const lower = text.toLowerCase();
    const patterns = [
        { keys: ['强烈买入', 'strong buy'], label: '强烈买入', tone: 'bullish-strong' },
        { keys: ['买入', 'buy', '看多', '做多', 'long'], label: '买入', tone: 'bullish' },
        { keys: ['强烈卖出', 'strong sell'], label: '强烈卖出', tone: 'bearish-strong' },
        { keys: ['卖出', 'sell', '看空', '做空', 'short'], label: '卖出', tone: 'bearish' },
        { keys: ['持有', 'hold', '观望', 'neutral', 'wait'], label: '持有/观望', tone: 'neutral' },
        { keys: ['减仓', 'reduce'], label: '减仓', tone: 'bearish' },
        { keys: ['加仓', 'increase position', 'add'], label: '加仓', tone: 'bullish' },
    ];
    for (const p of patterns) {
        if (p.keys.some(k => lower.includes(k.toLowerCase()))) {
            return p;
        }
    }
    return null;
}

function extractConfidence(text) {
    if (!text || typeof text !== 'string') return null;
    // Match "置信度 85%" / "confidence: 0.8" / "信心 7/10"
    const pctMatch = text.match(/(?:置信度|信心|confidence)[^\d%]{0,6}(\d{1,3})\s*%/i);
    if (pctMatch) return { value: Number(pctMatch[1]), display: `${pctMatch[1]}%` };
    const scoreMatch = text.match(/(?:置信度|信心|confidence)[^\d]{0,6}(\d(?:\.\d+)?)\s*\/\s*(10|5|100)/i);
    if (scoreMatch) {
        const v = Number(scoreMatch[1]);
        const base = Number(scoreMatch[2]);
        return { value: Math.round((v / base) * 100), display: `${scoreMatch[1]}/${scoreMatch[2]}` };
    }
    return null;
}

function extractRiskLevel(text) {
    if (!text || typeof text !== 'string') return null;
    const lower = text.toLowerCase();
    if (/(高风险|极高风险|high risk|very high risk)/i.test(text)) return { label: '高风险', tone: 'bearish' };
    if (/(中等风险|中度风险|medium risk|moderate risk)/i.test(text)) return { label: '中等风险', tone: 'neutral' };
    if (/(低风险|low risk)/i.test(text)) return { label: '低风险', tone: 'bullish' };
    return null;
}

function signalToneClass(tone) {
    switch (tone) {
        case 'bullish-strong': return 'text-emerald-300 border-emerald-500/50 bg-emerald-500/10';
        case 'bullish': return 'text-emerald-400 border-emerald-500/30 bg-emerald-500/5';
        case 'bearish-strong': return 'text-rose-300 border-rose-500/50 bg-rose-500/10';
        case 'bearish': return 'text-rose-400 border-rose-500/30 bg-rose-500/5';
        case 'neutral': return 'text-amber-300 border-amber-500/30 bg-amber-500/5';
        default: return 'text-slate-300 border-slate-500/30 bg-slate-500/5';
    }
}

// Guess a persona's stance from the opening lines of their analysis.
function inferPersonaStance(text) {
    const sig = extractSignal(text || '');
    if (!sig) return { label: '观望', tone: 'neutral' };
    return { label: sig.label, tone: sig.tone };
}

function renderAgentReport(data, opts = {}) {
    const { debate = false } = opts;
    const resultsEl = document.getElementById('agent-results');
    resultsEl.classList.remove('hidden');

    const personas = Object.entries(data.persona_analyses || {});
    const finalDecision = data.final_decision || '';
    const riskAssessment = data.risk_assessment || '';
    const technicalAnalysis = data.technical_analysis || '';

    const signal = extractSignal(finalDecision) || extractSignal(technicalAnalysis);
    const confidence = extractConfidence(finalDecision) || extractConfidence(technicalAnalysis);
    const risk = extractRiskLevel(riskAssessment);

    // ---- metric strip ------------------------------------------------
    const metricCards = [
        {
            label: '综合信号',
            value: signal ? signal.label : '—',
            extra: '',
            cls: signal ? signalToneClass(signal.tone) : '',
        },
        {
            label: '置信度',
            value: confidence ? confidence.display : '—',
            extra: confidence
                ? `<div class="mt-2 h-1.5 rounded-full bg-slate-700/60 overflow-hidden">
                       <div class="h-full bg-brand-400" style="width:${Math.min(100, Math.max(0, confidence.value))}%"></div>
                   </div>`
                : '',
            cls: '',
        },
        {
            label: '风险级别',
            value: risk ? risk.label : '—',
            extra: '',
            cls: risk ? signalToneClass(risk.tone) : '',
        },
        {
            label: '人格数量',
            value: personas.length.toString(),
            extra: '',
            cls: 'text-brand-400',
        },
        {
            label: '辩论轮次',
            value: (data.debate_history?.length || 0).toString(),
            extra: '',
            cls: debate ? 'text-amber-400' : 'text-slate-400',
        },
    ];

    const metricStrip = `
        <div class="grid grid-cols-2 md:grid-cols-5 gap-3">
            ${metricCards.map(m => `
                <div class="metric-card border ${m.cls}">
                    <div class="metric-label">${escapeHtml(m.label)}</div>
                    <div class="metric-value">${escapeHtml(m.value)}</div>
                    ${m.extra}
                </div>`).join('')}
        </div>`;

    // ---- decision / risk / technical cards ---------------------------
    const summarySection = `
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div class="card border border-emerald-500/20">
                <div class="flex items-center justify-between mb-2">
                    <h3 class="text-base font-semibold text-emerald-300">最终决策</h3>
                    ${signal ? `<span class="pill ${signalToneClass(signal.tone)} text-xs">${escapeHtml(signal.label)}</span>` : ''}
                </div>
                <div class="prose prose-invert prose-sm max-w-none">${renderMarkdown(finalDecision || '未返回最终决策')}</div>
            </div>
            <div class="card border border-rose-500/20">
                <div class="flex items-center justify-between mb-2">
                    <h3 class="text-base font-semibold text-rose-300">风险评估</h3>
                    ${risk ? `<span class="pill ${signalToneClass(risk.tone)} text-xs">${escapeHtml(risk.label)}</span>` : ''}
                </div>
                <div class="prose prose-invert prose-sm max-w-none">${renderMarkdown(riskAssessment || '未返回风险评估')}</div>
            </div>
            <div class="card border border-sky-500/20">
                <div class="flex items-center justify-between mb-2">
                    <h3 class="text-base font-semibold text-sky-300">技术 / 基本面</h3>
                </div>
                <div class="prose prose-invert prose-sm max-w-none">${renderMarkdown(technicalAnalysis || '未返回技术分析')}</div>
            </div>
        </div>`;

    // ---- persona comparison grid -------------------------------------
    const personaSection = personas.length
        ? `<div class="card">
                <h3 class="text-lg font-semibold mb-3">人格观点对比</h3>
                <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                    ${personas.map(([name, analysis]) => {
                        const stance = inferPersonaStance(analysis);
                        const cls = signalToneClass(stance.tone);
                        return `
                            <div class="persona-card border ${cls} rounded-lg p-3">
                                <div class="flex items-center justify-between mb-2">
                                    <div class="font-semibold text-purple-200">${escapeHtml(name)}</div>
                                    <span class="pill text-xs ${cls}">${escapeHtml(stance.label)}</span>
                                </div>
                                <details>
                                    <summary class="cursor-pointer text-xs text-slate-400 hover:text-slate-200">展开详情</summary>
                                    <div class="prose prose-invert prose-sm max-w-none mt-2">${renderMarkdown(analysis)}</div>
                                </details>
                            </div>`;
                    }).join('')}
                </div>
           </div>`
        : '';

    // ---- debate visual timeline --------------------------------------
    const debateRounds = data.debate_history || [];
    const debateSection = `
        <div class="card">
            <h3 class="text-lg font-semibold mb-3">辩论时间轴</h3>
            ${debateRounds.length ? `
                <div class="debate-timeline space-y-4">
                    ${debateRounds.map(round => `
                        <div class="debate-round">
                            <div class="flex items-center gap-2 mb-2">
                                <span class="round-pill">第 ${escapeHtml(String(round.round || '?'))} 轮</span>
                                <span class="flex-1 h-px bg-slate-700"></span>
                            </div>
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-2">
                                <div class="debate-bubble border border-emerald-500/30 bg-emerald-500/5 rounded-lg p-3">
                                    <div class="font-medium text-emerald-300 text-xs mb-1">激进 · Aggressive</div>
                                    <div class="prose prose-invert prose-sm max-w-none">${renderMarkdown(round.aggressive || '—')}</div>
                                </div>
                                <div class="debate-bubble border border-sky-500/30 bg-sky-500/5 rounded-lg p-3">
                                    <div class="font-medium text-sky-300 text-xs mb-1">保守 · Conservative</div>
                                    <div class="prose prose-invert prose-sm max-w-none">${renderMarkdown(round.conservative || '—')}</div>
                                </div>
                                <div class="debate-bubble border border-slate-500/30 bg-slate-500/5 rounded-lg p-3">
                                    <div class="font-medium text-slate-300 text-xs mb-1">中立 · Neutral</div>
                                    <div class="prose prose-invert prose-sm max-w-none">${renderMarkdown(round.neutral || '—')}</div>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>` : '<div class="empty-state">没有辩论记录。</div>'}
        </div>`;

    resultsEl.innerHTML = `
        <div class="space-y-4">
            ${metricStrip}
            ${summarySection}
            ${personaSection}
            ${debateSection}
        </div>
    `;
}

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
            market,
            debate,
            summary: (data.final_decision || data.risk_assessment || 'Agent run completed').slice(0, 80),
            data,
        });

        renderAgentReport(data, { debate });

        toast('Agent 分析完成', 'success');
    } catch (e) {
        document.getElementById('agent-results').classList.remove('hidden');
        document.getElementById('agent-results').innerHTML = `<div class="card text-rose-400">${escapeHtml(e.message)}</div>`;
        toast(e.message, 'error');
    } finally {
        document.getElementById('agent-loading').classList.add('hidden');
    }
}

window.renderAgentReport = renderAgentReport;
