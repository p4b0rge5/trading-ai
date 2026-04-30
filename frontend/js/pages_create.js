/**
 * Create Strategy Page: Natural language prompt → Strategy + Backtest
 */
Router.register('/create', (app) => {
    app.innerHTML = renderLayout(`
        <div class="page-header">
            <h2>Criar Estratégia</h2>
            <p>Descreva em linguagem natural e o AI gera, valida e testa automaticamente</p>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
            <div>
                <div class="card">
                    <h3 style="margin-bottom:16px">📝 Descreva sua estratégia</h3>
                    <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px">
                        Seja o mais específico possível. Indique par de moedas, timeframe, indicadores,
                        condições de entrada/saída, e gestão de risco.
                    </p>
                    <div class="form-group">
                        <label>Seu prompt</label>
                        <textarea class="form-textarea" id="create-prompt" rows="8"
                            placeholder="Ex: Quero operar EURUSD no gráfico de 4 horas. Comprar quando RSI passar de 30 para cima e a média móvel de 50 cruzar acima da média de 200. Vender quando RSI passar de 70 para baixo. Stop loss de 50 pips, take profit de 100 pips. Risco máximo de 2% por trade."></textarea>
                    </div>
                    <div class="form-group">
                        <label>Símbolo (opcional — inclua no prompt)</label>
                        <input type="text" class="form-input" id="create-symbol" list="symbol-list" placeholder="Ex: EURUSD, BTCUSD, GBPJPY...">
                        <datalist id="symbol-list"></datalist>
                    </div>
                    <div class="form-group">
                        <label>Número de barras para backtest</label>
                        <select class="form-select" id="create-bars">
                            <option value="1000">1000 barras (rápido)</option>
                            <option value="2000" selected>2000 barras</option>
                            <option value="5000">5000 barras (recomendado)</option>
                            <option value="10000">10000 barras (completo)</option>
                        </select>
                    </div>
                    <button class="btn btn-primary" onclick="doCreate()" id="create-btn" style="width:100%;justify-content:center">
                        🤖 Gerar com AI e Backtest
                    </button>
                    <div id="create-error" class="alert alert-error" style="display:none;margin-top:12px"></div>
                </div>

                <!-- Tips -->
                <div class="card" style="margin-top:20px">
                    <h3 style="margin-bottom:12px">💡 Dicas de prompts</h3>
                    <div style="font-size:13px;color:var(--text-secondary);line-height:2">
                        <div>✅ <strong>Mencione o par de moedas:</strong> EURUSD, GBPJPY, BTCUSD...</div>
                        <div>✅ <strong>Especifique o timeframe:</strong> 1m, 5m, 15m, 1h, 4h, 1d</div>
                        <div>✅ <strong>Seja claro nos indicadores:</strong> "RSI período 14", "Média 200", "Bollinger"</div>
                        <div>✅ <strong>Defina entry/exit:</strong> "comprar quando X cruzar Y", "vender quando RSI > 70"</div>
                        <div>✅ <strong>Gestão de risco:</strong> "stop loss 50 pips", "take profit 100 pips", "risco 2%"</div>
                    </div>
                </div>
            </div>

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

    // Load available symbols for autocomplete
    API.get('/api/v1/data/symbols').then(symbols => {
        const dl = document.getElementById('symbol-list');
        if (dl) {
            dl.innerHTML = symbols.map(s => `<option value="${s.symbol}">`).join('');
        }
    }).catch(() => {});
});

async function doCreate() {
    const prompt = document.getElementById('create-prompt').value.trim();
    const bars = parseInt(document.getElementById('create-bars').value);
    const btn = document.getElementById('create-btn');
    const errEl = document.getElementById('create-error');
    const result = document.getElementById('create-result');

    if (!prompt || prompt.length < 10) {
        Toast.error('Prompt muito curto (mínimo 10 caracteres)');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Gerando estratégia com AI...';
    errEl.style.display = 'none';
    result.innerHTML = '<div class="loading-overlay" style="padding:80px"><span class="spinner"></span> <span id="loading-text">Gerando estratégia...</span></div>';

    try {
        const data = await API.post('/api/v1/strategies/from-prompt', {
            prompt, run_backtest: true, bars,
        });

        const bt = data.backtest || {};
        result.innerHTML = `
            <div class="alert alert-success">✅ Estratégia gerada com sucesso!</div>

            <div style="margin-bottom:16px">
                <h3 style="margin-bottom:4px">${data.strategy.name}</h3>
                <span class="badge badge-blue">${data.strategy.symbol}</span>
                <span class="badge badge-purple">${data.strategy.timeframe}</span>
                <span class="badge badge-yellow">${data.llm_calls} LLM calls</span>
            </div>

            ${data.strategy.description ? `<p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px">${data.strategy.description}</p>` : ''}

            <div class="stats-grid" style="margin-bottom:20px">
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Retorno</div>
                    <div class="stat-value ${bt.total_return_pct >= 0 ? 'green' : 'red'}" style="font-size:22px">${formatPct(bt.total_return_pct)}</div>
                </div>
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Win Rate</div>
                    <div class="stat-value ${bt.win_rate >= 0.5 ? 'green' : 'red'}" style="font-size:22px">${formatPct(bt.win_rate * 100)}</div>
                </div>
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Trades</div>
                    <div class="stat-value accent" style="font-size:22px">${bt.total_trades}</div>
                </div>
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Max Drawdown</div>
                    <div class="stat-value red" style="font-size:22px">${formatPct(bt.max_drawdown_pct)}</div>
                </div>
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Sharpe Ratio</div>
                    <div class="stat-value ${bt.sharpe_ratio >= 1 ? 'green' : 'red'}" style="font-size:22px">${formatNumber(bt.sharpe_ratio)}</div>
                </div>
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Profit Factor</div>
                    <div class="stat-value ${bt.profit_factor >= 1 ? 'green' : 'red'}" style="font-size:22px">${formatNumber(bt.profit_factor)}</div>
                </div>
            </div>

            <div style="display:flex;gap:10px">
                <button class="btn btn-primary" onclick="Router.navigate('/strategy/${data.strategy.id}')">Ver Detalhes</button>
                <button class="btn btn-secondary" onclick="Router.navigate('/dashboard')">Dashboard</button>
            </div>
        `;
        Toast.success('Estratégia criada!');
    } catch (err) {
        errEl.style.display = 'block';
        errEl.textContent = err.message;
        result.innerHTML = `<div class="alert alert-error">Erro: ${err.message}</div>`;
        Toast.error('Falha ao criar estratégia');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🤖 Gerar com AI e Backtest';
    }
}
