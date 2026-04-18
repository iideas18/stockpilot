/* StockPilot main app */

const API = '/api/v1';
let bootstrapCache = { strategies: [], personas: [] };

function formatApiError(detail) {
    if (!detail || typeof detail !== 'object') {
        return String(detail || 'Request failed');
    }
    const parts = [];
    if (detail.message) parts.push(detail.message);
    if (detail.code) parts.push(`[${detail.code}]`);
    if (detail.retry_after_seconds != null) {
        parts.push(`(retry in ${detail.retry_after_seconds}s)`);
    }
    return parts.join(' ') || 'Request failed';
}

const _dataStatusSeen = new Set();

function consumeDataStatus(payload, { dedupeKey } = {}) {
    if (!payload || !payload.data_status) return null;
    const status = payload.data_status;
    if (status.status === 'stale' && dedupeKey) {
        if (_dataStatusSeen.has(dedupeKey)) return status;
        _dataStatusSeen.add(dedupeKey);
        const reason = status.degraded_reason || '数据源返回缓存副本';
        if (typeof toast === 'function') {
            toast(`数据可能过期: ${reason}`, 'error');
        }
    }
    return status;
}

async function api(path, options = {}) {
    const res = await fetch(`${API}${path}`, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        if (err && err.detail && typeof err.detail === 'object') {
            const message = formatApiError(err.detail);
            const error = new Error(message);
            error.detail = err.detail;
            throw error;
        }
        throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
}

function toast(msg, type = 'info') {
    const el = document.getElementById('toast');
    document.getElementById('toast-msg').textContent = msg;
    el.classList.remove('border-blue-500', 'border-red-500', 'border-green-500');
    el.classList.add(type === 'error' ? 'border-red-500' : type === 'success' ? 'border-green-500' : 'border-blue-500');
    el.style.transform = 'translateY(0)';
    el.style.opacity = '1';
    setTimeout(() => {
        el.style.transform = 'translateY(80px)';
        el.style.opacity = '0';
    }, 2600);
}

function escapeHtml(value) {
    if (value == null) return '';
    const div = document.createElement('div');
    div.textContent = String(value);
    return div.innerHTML;
}

function renderMarkdown(value) {
    if (value == null) return '';
    const text = typeof value === 'string' ? value : (() => {
        try { return '```json\n' + JSON.stringify(value, null, 2) + '\n```'; }
        catch (_) { return String(value); }
    })();
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
        return escapeHtml(text).replace(/\n/g, '<br>');
    }
    try {
        const html = marked.parse(text, { breaks: true, gfm: true });
        return DOMPurify.sanitize(html);
    } catch (_) {
        return escapeHtml(text).replace(/\n/g, '<br>');
    }
}

function navigateTo(page) {
    document.querySelectorAll('.page').forEach(el => el.classList.add('hidden'));
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.getElementById(`page-${page}`)?.classList.remove('hidden');
    document.querySelector(`[data-page="${page}"]`)?.classList.add('active');
    window.location.hash = page;
    if (page === 'news' && !document.getElementById('news-list').children.length) {
        loadNews();
    }
}

function setHeaderStock(symbol, name = '') {
    if (!symbol) return;
    document.getElementById('header-stock').classList.remove('hidden');
    document.getElementById('header-symbol').textContent = symbol;
    document.getElementById('header-name').textContent = name || '';
}

function fillInputsFromState({ forceSymbol = false, forceMarket = false } = {}) {
    const s = AppState.state;
    if (!s.activeSymbol) return;
    ['analysis-symbol', 'bt-symbol', 'agent-symbol'].forEach(id => {
        const input = document.getElementById(id);
        if (input && (forceSymbol || !input.value)) input.value = s.activeSymbol;
    });
    ['analysis-market', 'bt-market', 'agent-market'].forEach(id => {
        const input = document.getElementById(id);
        if (input && (forceMarket || !input.value)) input.value = s.activeMarket || 'a_share';
    });
}

function selectStock(symbol, name = '', market = 'a_share', { navigate = true, run = true } = {}) {
    AppState.setActiveSymbol(symbol, { name, market });
    setHeaderStock(symbol, name);
    fillInputsFromState({ forceSymbol: true, forceMarket: true });
    if (navigate) navigateTo('analysis');
    if (run && typeof runAnalysis === 'function') runAnalysis();
}

function renderSymbolItems(containerId, symbols, emptyText, type) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!symbols.length) {
        container.innerHTML = `<div class="empty-state">${emptyText}</div>`;
        return;
    }
    container.innerHTML = symbols.map(symbol => {
        const meta = AppState.state.symbolMeta[symbol] || { symbol, name: '', market: '' };
        return `
            <div class="context-item">
                <div class="context-item-main">
                    <button class="action-link font-medium" data-action="activate-symbol" data-symbol="${symbol}">${symbol}</button>
                    <div class="context-item-sub">${escapeHtml(meta.name || meta.market || '')}</div>
                </div>
                <button class="mini-button" data-action="remove-${type}" data-symbol="${symbol}">
                    <i class="fas fa-xmark"></i>
                </button>
            </div>
        `;
    }).join('');
}

function renderBacktestHistory() {
    const rail = document.getElementById('rail-backtests');
    if (!AppState.state.backtestHistory.length) {
        rail.innerHTML = '<div class="empty-state">还没有回测记录。</div>';
        return;
    }
    rail.innerHTML = AppState.state.backtestHistory.map((run, idx) => `
        <div class="history-item">
            <div class="context-item-main">
                <button class="action-link font-medium" data-action="use-backtest-run" data-index="${idx}">
                    ${escapeHtml(run.symbol)} · ${escapeHtml(run.strategy)}
                </button>
                <div class="context-item-sub">
                    ${run.metrics?.total_return_pct ?? 0}% · ${new Date(run.createdAt).toLocaleString()}
                </div>
            </div>
        </div>
    `).join('');
}

async function refreshWatchlistQuotes() {
    const rail = document.getElementById('rail-watchlist');
    if (!rail) return;
    const s = AppState.state;
    if (!s.watchlist || s.watchlist.length === 0) {
        return;
    }
    try {
        const payload = await api('/quotes', {
            method: 'POST',
            body: JSON.stringify({
                symbols: s.watchlist,
                market: s.activeMarket || 'a_share',
            }),
        });
        consumeDataStatus(payload, { dedupeKey: 'watchlist-quotes' });
        const quotes = payload.quotes || [];
        const quotesHtml = quotes.map(q => {
            const pct = (q.change_pct != null)
                ? `${q.change_pct > 0 ? '+' : ''}${q.change_pct}%`
                : '';
            const pctClass = (q.change_pct != null && q.change_pct < 0)
                ? 'text-red-400'
                : 'text-emerald-400';
            return `
                <div class="context-item">
                    <div class="context-item-main">
                        <div class="font-medium text-brand-300">${escapeHtml(q.symbol)}</div>
                        <div class="context-item-sub">${escapeHtml(q.price != null ? q.price : '-')}</div>
                    </div>
                    <div class="${pctClass} text-sm">${escapeHtml(pct)}</div>
                </div>
            `;
        }).join('');
        const missing = (payload.data_status && payload.data_status.missing_symbols) || [];
        const missingPanel = missing.length
            ? `<div class="degraded-panel text-xs text-amber-300 px-2 py-1">missing: ${missing.map(escapeHtml).join(', ')}</div>`
            : '';
        if (quotesHtml || missingPanel) {
            rail.innerHTML = quotesHtml + missingPanel;
        }
    } catch (e) {
        if (e && e.detail) {
            const msg = formatApiError(e.detail);
            rail.innerHTML = `<div class="degraded-panel text-xs text-red-400 px-2 py-2">${escapeHtml(msg)}</div>`;
        }
    }
}

function renderAgentSessions() {
    const rail = document.getElementById('rail-agent-sessions');
    if (!AppState.state.agentSessions.length) {
        rail.innerHTML = '<div class="empty-state">还没有 Agent 会话。</div>';
        return;
    }
    rail.innerHTML = AppState.state.agentSessions.map((run, idx) => `
        <div class="history-item">
            <div class="context-item-main">
                <button class="action-link font-medium" data-action="use-agent-session" data-index="${idx}">
                    ${escapeHtml(run.symbol)}
                </button>
                <div class="context-item-sub">
                    ${escapeHtml(run.summary || '已完成')} · ${new Date(run.createdAt).toLocaleString()}
                </div>
            </div>
        </div>
    `).join('');
}

function renderWorkspace() {
    const s = AppState.state;
    document.getElementById('workspace-active-symbol').textContent = s.activeSymbol || '未选择标的';
    document.getElementById('workspace-active-market').textContent = s.activeMarket || 'a_share';

    const recentEl = document.getElementById('workspace-recent-symbols');
    recentEl.innerHTML = s.recentSymbols.length
        ? s.recentSymbols.map(item => `
            <button class="pill pill-muted" data-action="activate-symbol" data-symbol="${item.symbol}">
                ${item.symbol}
            </button>`).join('')
        : '<span class="empty-state">暂无历史</span>';

    const current = document.getElementById('rail-current-context');
    current.innerHTML = s.activeSymbol ? `
        <div class="context-item">
            <div class="context-item-main">
                <div class="font-semibold text-brand-300">${escapeHtml(s.activeSymbol)}</div>
                <div class="context-item-sub">${escapeHtml(s.activeName || s.activeMarket || '')}</div>
            </div>
        </div>
        <div class="quick-actions">
            <button class="mini-button" data-action="open-page" data-page="analysis">分析</button>
            <button class="mini-button" data-action="open-page" data-page="compare">对比</button>
            <button class="mini-button" data-action="open-page" data-page="backtest">回测</button>
            <button class="mini-button" data-action="open-page" data-page="agent">Agent</button>
        </div>
    ` : '<div class="empty-state">搜索股票后会出现在这里。</div>';

    renderSymbolItems('rail-watchlist', s.watchlist, '关注列表为空。', 'watchlist');
    renderSymbolItems('rail-compare', s.compareSymbols, '还没有对比标的。', 'compare');
    renderSymbolItems('rail-basket', s.portfolioBasket, '组合候选为空。', 'basket');
    renderBacktestHistory();
    renderAgentSessions();
    refreshWatchlistQuotes();

    document.getElementById('dash-watchlist-count').textContent = s.watchlist.length;
    document.getElementById('dashboard-context').innerHTML = `
        <div class="space-y-2">
            <div class="flex justify-between"><span class="text-slate-400">当前标的</span><span>${escapeHtml(s.activeSymbol || '—')}</span></div>
            <div class="flex justify-between"><span class="text-slate-400">关注列表</span><span>${s.watchlist.length}</span></div>
            <div class="flex justify-between"><span class="text-slate-400">对比候选</span><span>${s.compareSymbols.length}</span></div>
            <div class="flex justify-between"><span class="text-slate-400">组合候选</span><span>${s.portfolioBasket.length}</span></div>
            <div class="flex justify-between"><span class="text-slate-400">回测历史</span><span>${s.backtestHistory.length}</span></div>
            <div class="flex justify-between"><span class="text-slate-400">Agent 会话</span><span>${s.agentSessions.length}</span></div>
        </div>
    `;

    fillInputsFromState();
}

async function initDashboard() {
    try {
        const [strats, personas] = await Promise.all([api('/strategies'), api('/personas')]);
        bootstrapCache = { strategies: strats.strategies, personas: personas.personas };
        window.bootstrapCache = bootstrapCache;
        document.getElementById('dash-strategies').textContent = strats.strategies.length;
        document.getElementById('dash-personas').textContent = personas.personas.length;
        document.getElementById('dash-strategy-list').innerHTML = strats.strategies.map(s => `
            <div class="flex justify-between items-center">
                <span><span class="text-brand-500">●</span> ${escapeHtml(s.name)}</span>
                <span class="text-slate-500 text-xs">${escapeHtml(s.type)}</span>
            </div>`).join('');
        document.getElementById('dash-persona-list').innerHTML = personas.personas.map(p => `
            <div class="flex justify-between items-center">
                <span><span class="text-purple-400">●</span> ${escapeHtml(p.name)}</span>
                <span class="text-slate-500 text-xs">${escapeHtml(p.type)}</span>
            </div>`).join('');
        document.getElementById('bt-strategy').innerHTML = strats.strategies.map(s => `
            <option value="${s.key}">${escapeHtml(s.name)} (${escapeHtml(s.type)})</option>`).join('');
        document.getElementById('agent-personas').innerHTML = personas.personas.map(p => `
            <span class="persona-chip ${['warren_buffett', 'nassim_taleb', 'cathie_wood'].includes(p.key) ? 'selected' : ''}" data-key="${p.key}">
                ${escapeHtml(p.name)}
            </span>`).join('');
        document.querySelectorAll('#agent-personas .persona-chip').forEach(chip => {
            chip.addEventListener('click', () => chip.classList.toggle('selected'));
        });
    } catch (e) {
        toast(`初始化失败: ${e.message}`, 'error');
    }
}

async function loadNews() {
    const loading = document.getElementById('news-loading');
    const list = document.getElementById('news-list');
    loading.classList.remove('hidden');
    list.innerHTML = '';
    try {
        const data = await api('/news/trending?limit=20');
        list.innerHTML = data.news.map(item => `
            <a href="${item.url}" target="_blank" rel="noopener noreferrer" class="card block hover:border-brand-500/50 transition-colors">
                <div class="flex justify-between items-start gap-4">
                    <span class="text-sm">${escapeHtml(item.title)}</span>
                    <span class="text-xs text-slate-500 whitespace-nowrap">${escapeHtml(item.source)}</span>
                </div>
            </a>
        `).join('');
    } catch (e) {
        toast(e.message, 'error');
    } finally {
        loading.classList.add('hidden');
    }
}

function bindSearch() {
    const input = document.getElementById('search-input');
    const dropdown = document.getElementById('search-dropdown');
    let timeout = null;

    input.addEventListener('input', () => {
        clearTimeout(timeout);
        const q = input.value.trim();
        if (!q) {
            dropdown.classList.add('hidden');
            return;
        }
        timeout = setTimeout(async () => {
            try {
                const data = await api(`/stocks/search?keyword=${encodeURIComponent(q)}`);
                dropdown.innerHTML = data.results.length ? data.results.map(item => `
                    <button class="w-full text-left px-4 py-2 hover:bg-slate-700/70 flex justify-between"
                            data-action="pick-search"
                            data-symbol="${item.symbol}"
                            data-name="${escapeHtml(item.name || '')}"
                            data-market="${escapeHtml(item.market || 'a_share')}">
                        <span class="text-brand-400 font-mono">${escapeHtml(item.symbol)}</span>
                        <span class="text-slate-400">${escapeHtml(item.name || '')}</span>
                    </button>`).join('') : '<div class="px-4 py-2 text-slate-500 text-sm">无结果</div>';
                dropdown.classList.remove('hidden');
            } catch (e) {
                dropdown.classList.add('hidden');
            }
        }, 250);
    });

    document.addEventListener('click', e => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.add('hidden');
        }
    });
}

function bindGlobalActions() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', e => {
            e.preventDefault();
            navigateTo(item.dataset.page);
        });
    });

    document.addEventListener('click', e => {
        const actionEl = e.target.closest('[data-action]');
        if (!actionEl) return;
        const action = actionEl.dataset.action;
        const symbol = actionEl.dataset.symbol;

        if (action === 'pick-search') {
            document.getElementById('search-dropdown').classList.add('hidden');
            document.getElementById('search-input').value = '';
            selectStock(symbol, actionEl.dataset.name || '', actionEl.dataset.market || 'a_share');
        } else if (action === 'activate-symbol') {
            selectStock(symbol, AppState.state.symbolMeta[symbol]?.name || '', AppState.state.symbolMeta[symbol]?.market || 'a_share', { navigate: false, run: false });
            toast(`已切换到 ${symbol}`, 'success');
        } else if (action === 'remove-watchlist') {
            AppState.removeWatchlist(symbol);
        } else if (action === 'remove-compare') {
            AppState.removeCompareSymbol(symbol);
        } else if (action === 'remove-basket') {
            AppState.removePortfolioSymbol(symbol);
        } else if (action === 'open-page') {
            navigateTo(actionEl.dataset.page);
        } else if (action === 'use-backtest-run') {
            const run = AppState.state.backtestHistory[Number(actionEl.dataset.index)];
            if (run) {
                document.getElementById('bt-symbol').value = run.symbol;
                document.getElementById('bt-strategy').value = run.strategy;
                navigateTo('backtest');
                if (typeof renderBacktestResult === 'function') renderBacktestResult(run, true);
            }
        } else if (action === 'use-agent-session') {
            const run = AppState.state.agentSessions[Number(actionEl.dataset.index)];
            if (run) {
                document.getElementById('agent-symbol').value = run.symbol;
                if (run.market) {
                    const marketEl = document.getElementById('agent-market');
                    if (marketEl) marketEl.value = run.market;
                }
                navigateTo('agent');
                if (run.data && typeof renderAgentReport === 'function') {
                    renderAgentReport(run.data, { debate: !!run.debate });
                    toast('已恢复历史报告', 'success');
                } else {
                    toast('该历史仅保留摘要，请重新运行分析', 'info');
                }
            }
        }
    });

    document.getElementById('workspace-add-watchlist').addEventListener('click', () => {
        if (!AppState.state.activeSymbol) return toast('先选择一个标的', 'error');
        AppState.addWatchlist(AppState.state.activeSymbol, { name: AppState.state.activeName, market: AppState.state.activeMarket });
        toast('已加入关注列表', 'success');
    });
    document.getElementById('workspace-add-compare').addEventListener('click', () => {
        if (!AppState.state.activeSymbol) return toast('先选择一个标的', 'error');
        AppState.addCompareSymbol(AppState.state.activeSymbol, { name: AppState.state.activeName, market: AppState.state.activeMarket });
        toast('已加入对比列表', 'success');
    });
    document.getElementById('workspace-add-basket').addEventListener('click', () => {
        if (!AppState.state.activeSymbol) return toast('先选择一个标的', 'error');
        AppState.addPortfolioSymbol(AppState.state.activeSymbol, { name: AppState.state.activeName, market: AppState.state.activeMarket });
        toast('已加入组合候选', 'success');
    });
    document.getElementById('workspace-open-analysis').addEventListener('click', () => navigateTo('analysis'));
    document.getElementById('workspace-open-agent').addEventListener('click', () => navigateTo('agent'));
    document.getElementById('news-refresh').addEventListener('click', loadNews);

    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            document.getElementById('search-input').focus();
        }
    });
}

window.api = api;
window.toast = toast;
window.formatApiError = formatApiError;
window.consumeDataStatus = consumeDataStatus;
window.navigateTo = navigateTo;
window.selectStock = selectStock;
window.escapeHtml = escapeHtml;
window.renderMarkdown = renderMarkdown;
window.renderWorkspace = renderWorkspace;
window.bootstrapCache = bootstrapCache;

AppState.subscribe(() => renderWorkspace());

document.addEventListener('DOMContentLoaded', async () => {
    bindSearch();
    bindGlobalActions();
    await initDashboard();
    const hash = window.location.hash.replace('#', '') || 'dashboard';
    navigateTo(hash);
    renderWorkspace();
});
