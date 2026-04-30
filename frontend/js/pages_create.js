/**
 * Create Strategy Page: Natural language prompt → Strategy + Backtest
 */
Router.register('/create', (app) => {
    app.innerHTML = renderLayout(`
        <div class="page-header">
            <div>
                <h2>Criar Estratégia</h2>
                <p>Descreva em linguagem natural e o AI gera, valida e testa automaticamente</p>
            </div>
        </div>

        <div class="two-col-grid">
            <!-- Left: Form -->
            <div>
                <div class="card">
                    <h3 style="margin-bottom:4px">📝 Descreva sua estratégia</h3>
                    <p class="text-sm" style="color:var(--text-secondary);margin-bottom:16px">
                        Seja específico: par de moedas, timeframe, indicadores, condições de entrada/saída e gestão de risco.
                    </p>
                    <div class="form-group">
                        <label for="create-prompt">Prompt</label>
                        <textarea class="form-textarea" id="create-prompt" rows="7"
                            placeholder="Ex: Quero operar EURUSD no gráfico de 4 horas. Comprar quando RSI passar de 30 para cima e a média móvel de 50 cruzar acima da média de 200. Vender quando RSI passar de 70 para baixo. Stop loss de 50 pips, take profit de 100 pips. Risco máximo de 2% por trade."></textarea>
                    </div>
                    <div class="form-group">
                        <label for="create-symbol">Símbolo (opcional)</label>
                        <select class="form-select" id="create-symbol">
                            <option value="">Selecione o ativo...</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="create-symbol-search">🔍 Buscar ativo</label>
                        <input type="text" class="form-input" id="create-symbol-search"
                            placeholder="Digite para filtrar (ex: PETR4, EURUSD, BTC)..." oninput="filterSymbolSelect()">
                    </div>
                    <div class="form-group">
                        <label for="create-bars">Barras para backtest</label>
                        <select class="form-select" id="create-bars">
                            <option value="1000">1000 barras (rápido)</option>
                            <option value="2000" selected>2000 barras</option>
                            <option value="5000">5000 barras (recomendado)</option>
                            <option value="10000">10000 barras (completo)</option>
                        </select>
                    </div>
                    <button class="btn btn-primary btn-full" onclick="doCreate()" id="create-btn">
                        🤖 Gerar com AI e Backtest
                    </button>
                    <div id="create-error" class="alert alert-error" style="display:none;margin-top:12px"></div>
                </div>

                <!-- Tips -->
                <div class="card mt-16">
                    <h3 style="margin-bottom:10px">💡 Dicas de prompts</h3>
                    <div class="text-sm" style="color:var(--text-secondary);line-height:2.2">
                        <div>✅ <strong>Mencione o ativo:</strong> EURUSD, BTCUSD, PETR4, VALE3</div>
                        <div>✅ <strong>Especifique o timeframe:</strong> 1m, 5m, 15m, 1h, 4h, 1d</div>
                        <div>✅ <strong>Seja claro nos indicadores:</strong> "RSI período 14", "Média 200"</div>
                        <div>✅ <strong>Defina entry/exit:</strong> "comprar quando X cruzar Y"</div>
                        <div>✅ <strong>Gestão de risco:</strong> "stop loss 50 pips", "risco 2%"</div>
                    </div>
                </div>
            </div>

            <!-- Right: Result -->
            <div>
                <div class="card" id="create-result">
                    <div class="empty-state">
                        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                            <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
                        </svg>
                        <h3>Resultado aparece aqui</h3>
                        <p>Após gerar a estratégia, os detalhes e resultados do backtest serão exibidos</p>
                    </div>
                </div>
            </div>
        </div>
    `);
    setActiveNav('/create');

    // Load symbols grouped by category
    API.get('/api/v1/data/symbols').then(symbols => {
        const sel = document.getElementById('create-symbol');
        if (!sel) return;

        // Group by type
        const groups = { b3: [], forex: [], crypto: [] };
        for (const s of symbols) {
            const t = s.type || 'forex';
            if (groups[t]) groups[t].push(s);
            else groups.forex.push(s);
        }

        sel.innerHTML = '<option value="">Selecione o ativo...</option>';
        const labels = { b3: '🇧🇷 Ações B3 (BRL)', forex: '💱 Forex', crypto: '₿ Cripto' };
        for (const [type, items] of Object.entries(groups)) {
            if (!items.length) continue;
            const og = document.createElement('optgroup');
            og.label = labels[type] || type;
            for (const s of items) {
                const opt = document.createElement('option');
                opt.value = s.symbol;
                const cur = s.currency || (s.type === 'b3' ? 'R$' : '$');
                opt.textContent = `${s.symbol} (${s.ticker}) — ${cur}`;
                og.appendChild(opt);
            }
            sel.appendChild(og);
        }

        // Show search box if many symbols
        const searchBox = document.getElementById('create-symbol-search');
        if (searchBox && symbols.length > 15) searchBox.style.display = 'block';
    }).catch(() => {});
});

// Global: filter symbol select by search text
window.filterSymbolSelect = function() {
    const q = (document.getElementById('create-symbol-search')?.value || '').toUpperCase();
    const sel = document.getElementById('create-symbol');
    if (!sel) return;
    const opts = sel.querySelectorAll('option');
    opts.forEach(o => {
        if (!o.value) return; // skip placeholder
        const text = (o.textContent + ' ' + o.value).toUpperCase();
        o.style.display = q === '' || text.includes(q) ? '' : 'none';
    });
};

async function doCreate() {
    const prompt = document.getElementById('create-prompt')?.value?.trim();
    const bars = parseInt(document.getElementById('create-bars')?.value || '2000');
    const btn = document.getElementById('create-btn');
    const errEl = document.getElementById('create-error');
    const result = document.getElementById('create-result');

    if (!prompt || prompt.length < 10) {
        Toast.error('Prompt muito curto (mínimo 10 caracteres)');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Gerando estratégia com AI...';
    if (errEl) errEl.style.display = 'none';
    result.innerHTML = '<div class="loading-overlay" style="padding:80px"><span class="spinner"></span> Gerando estratégia...</div>';

    try {
        const data = await API.post('/api/v1/strategies/from-prompt', {
            prompt, run_backtest: true, bars,
        });

        const bt = data.backtest || {};
        result.innerHTML = `
            <div class="alert alert-success">✅ Estratégia gerada com sucesso!</div>

            <div style="margin-bottom:16px">
                <h3 style="font-size:18px;margin-bottom:6px">${data.strategy.name}</h3>
                <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">
                    <span class="badge badge-blue">${data.strategy.symbol}</span>
                    <span class="badge badge-purple">${data.strategy.timeframe}</span>
                    <span class="badge badge-yellow">${data.llm_calls} LLM calls</span>
                </div>
                ${data.strategy.description ? `<p class="text-sm" style="color:var(--text-secondary);margin-bottom:16px">${data.strategy.description}</p>` : ''}
            </div>

            <div class="stats-grid" style="margin-bottom:0">
                <div class="stat-card">
                    <div class="stat-label">Retorno</div>
                    <div class="stat-value ${bt.total_return_pct >= 0 ? 'green' : 'red'}" class="">${formatPct(bt.total_return_pct)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Win Rate</div>
                    <div class="stat-value ${bt.win_rate >= 0.5 ? 'green' : 'red'}" class="">${formatPct(bt.win_rate * 100)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Trades</div>
                    <div class="stat-value accent" class="">${bt.total_trades}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Max Drawdown</div>
                    <div class="stat-value red" class="">${formatPct(bt.max_drawdown_pct)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Sharpe Ratio</div>
                    <div class="stat-value ${bt.sharpe_ratio >= 1 ? 'green' : 'red'}" class="">${formatNumber(bt.sharpe_ratio)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Profit Factor</div>
                    <div class="stat-value ${bt.profit_factor >= 1 ? 'green' : 'red'}" class="">${formatNumber(bt.profit_factor)}</div>
                </div>
            </div>

            <div class="btn-group mt-16">
                <button class="btn btn-primary" onclick="Router.navigate('/strategy/${data.strategy.id}')">Ver Detalhes</button>
                <button class="btn btn-secondary" onclick="Router.navigate('/dashboard')">Dashboard</button>
            </div>
        `;
        Toast.success('Estratégia criada!');
    } catch (err) {
        if (errEl) { errEl.style.display = 'block'; errEl.textContent = err.message; }
        result.innerHTML = `<div class="alert alert-error">Erro: ${err.message}</div>`;
        Toast.error('Falha ao criar estratégia');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🤖 Gerar com AI e Backtest';
    }
}
