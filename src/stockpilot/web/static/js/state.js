/* StockPilot workspace state */

(() => {
    const STORAGE_KEY = 'stockpilot.workspace.v3';
    const defaults = {
        activeSymbol: '',
        activeName: '',
        activeMarket: 'a_share',
        symbolMeta: {},
        watchlist: [],
        compareSymbols: [],
        portfolioBasket: [],
        recentSymbols: [],
        backtestHistory: [],
        agentSessions: [],
    };

    const listeners = new Set();
    let state = structuredClone(defaults);

    function save() {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    }

    function emit() {
        save();
        listeners.forEach(fn => fn(structuredClone(state)));
    }

    function upsertMeta(symbol, meta = {}) {
        if (!symbol) return;
        state.symbolMeta[symbol] = {
            ...(state.symbolMeta[symbol] || {}),
            symbol,
            name: meta.name || state.symbolMeta[symbol]?.name || '',
            market: meta.market || state.symbolMeta[symbol]?.market || state.activeMarket || 'a_share',
        };
    }

    function touchRecent(symbol) {
        if (!symbol) return;
        const meta = state.symbolMeta[symbol] || { symbol, name: '', market: state.activeMarket };
        state.recentSymbols = [
            { symbol, name: meta.name || '', market: meta.market || 'a_share', timestamp: new Date().toISOString() },
            ...state.recentSymbols.filter(item => item.symbol !== symbol),
        ].slice(0, 8);
    }

    function addUnique(listName, symbol, meta = {}) {
        if (!symbol) return;
        upsertMeta(symbol, meta);
        state[listName] = [symbol, ...state[listName].filter(item => item !== symbol)].slice(0, 10);
        touchRecent(symbol);
        emit();
    }

    function removeFrom(listName, symbol) {
        state[listName] = state[listName].filter(item => item !== symbol);
        emit();
    }

    const AppState = {
        load() {
            try {
                const raw = localStorage.getItem(STORAGE_KEY);
                if (raw) {
                    state = { ...structuredClone(defaults), ...JSON.parse(raw) };
                }
            } catch {
                state = structuredClone(defaults);
            }
            return state;
        },
        get state() {
            return state;
        },
        subscribe(fn) {
            listeners.add(fn);
            return () => listeners.delete(fn);
        },
        setActiveSymbol(symbol, meta = {}) {
            if (!symbol) return;
            upsertMeta(symbol, meta);
            state.activeSymbol = symbol;
            state.activeName = meta.name || state.symbolMeta[symbol]?.name || '';
            state.activeMarket = meta.market || state.symbolMeta[symbol]?.market || state.activeMarket || 'a_share';
            touchRecent(symbol);
            emit();
        },
        addWatchlist(symbol, meta = {}) {
            addUnique('watchlist', symbol, meta);
        },
        addCompareSymbol(symbol, meta = {}) {
            addUnique('compareSymbols', symbol, meta);
        },
        addPortfolioSymbol(symbol, meta = {}) {
            addUnique('portfolioBasket', symbol, meta);
        },
        setPortfolioBasket(symbols = []) {
            state.portfolioBasket = [];
            symbols.forEach(symbol => {
                if (!symbol) return;
                upsertMeta(symbol);
                state.portfolioBasket = [symbol, ...state.portfolioBasket.filter(item => item !== symbol)].slice(0, 10);
                touchRecent(symbol);
            });
            emit();
        },
        removeWatchlist(symbol) {
            removeFrom('watchlist', symbol);
        },
        removeCompareSymbol(symbol) {
            removeFrom('compareSymbols', symbol);
        },
        removePortfolioSymbol(symbol) {
            removeFrom('portfolioBasket', symbol);
        },
        pushBacktestRun(run) {
            state.backtestHistory = [
                { ...run, createdAt: new Date().toISOString() },
                ...state.backtestHistory,
            ].slice(0, 8);
            emit();
        },
        pushAgentSession(session) {
            state.agentSessions = [
                { ...session, createdAt: new Date().toISOString() },
                ...state.agentSessions,
            ].slice(0, 8);
            emit();
        },
    };

    AppState.load();
    window.AppState = AppState;
})();
