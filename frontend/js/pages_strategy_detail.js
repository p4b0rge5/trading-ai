/**
 * Strategy Detail Page
 */
Router.register('/strategy/:id', async (app) => {
    const id = window.location.hash.match(/\/strategy\/(\d+)/)?.[1];
    if (!id) { Router.navigate('/strategies'); return; }

    app.innerHTML = renderLayout(`
        <div class="page-header">
            <div style="flex:1">
                <div class="breadcrumb">
                    <a onclick="Router.navigate('/strategies')">Estratégias</a>
                    <span class="sep">›</span>
                    <span class="current">...</span>
                </div>
                <h2 class="strategy-title">Carregando...</h2>
            </div>
        </div>
        <div id="strategy-detail">
            <div class="loading-overlay"><span class="spinner"></span> Carregando estratégia...</div>
        </div>
    `);
    setActiveNav('/strategies');

    try {
        const strategy = await API.get(`/api/v1/strategies/${id}`);
        const spec = strategy.spec_json || {};

        // Update page header with actual strategy name
        document.querySelector('.strategy-title').textContent = strategy.name;
        document.querySelector('.breadcrumb .current').textContent = strategy.name;

        const renderIndicator = (ind) => {
            const icons = { sma: '📈', ema: '📈', wma: '📈', rsi: '📊', macd: '📉',
                           bollinger: '📉', stochastic: '📊', atr: '📏', adx: '📈' };
            return `<span class="badge badge-blue">${icons[ind.indicator_type] || '📊'} ${ind.indicator_type}(${ind.period})</span>`;
        };

        const renderCondition = (c) => {
            const label = c.description || c.condition_type || c.exit_type || 'S/ descrição';
            return `<span class="badge badge-cyan">${label}</span>`;
        };

        const indicators = spec.indicators || [];
        const entryRules = spec.entry_conditions || [];
        const exitRules = spec.exit_conditions || [];
        const risk = spec.risk_management;

        document.getElementById('strategy-detail').innerHTML = `
            <!-- Action Bar -->
            <div class="card section-gap action-bar">
                <div class="action-bar-body">
                    <div class="action-bar-tags">
                        <span class="badge badge-blue">${strategy.symbol}</span>
                        <span class="badge badge-purple">${strategy.timeframe}</span>
                        <span class="badge badge-yellow">${indicators.length} indicadores</span>
                    </div>
                    ${strategy.description ? `<p class="strategy-desc">${strategy.description}</p>` : ''}
                    <div class="action-bar-buttons">
                        <button class="btn btn-secondary" onclick="exportMQL5(${strategy.id})">⚙️ Exportar MQL5</button>
                        <button class="btn btn-primary" onclick="Router.navigate('/backtest/run/${id}')">🚀 Backtest</button>
                        <button class="btn btn-danger" onclick="deleteStrategy(${strategy.id})">🗑️ Apagar</button>
                    </div>
                </div>
            </div>

            <!-- Specs Grid: Indicators, Entry, Exit, Risk -->
            <div class="two-col-grid section-gap">
                <div class="card">
                    <div class="card-header">
                        <h3>📊 Indicadores</h3>
                    </div>
                    <div class="flex flex-wrap gap-8">
                        ${indicators.map(renderIndicator).join('') || '<span class="text-muted">Nenhum</span>'}
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <h3>🎯 Regras de Entrada</h3>
                    </div>
                    <div class="flex flex-wrap gap-8">
                        ${entryRules.map(renderCondition).join('') || '<span class="text-muted">Nenhuma</span>'}
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <h3>🚪 Regras de Saída</h3>
                    </div>
                    <div class="flex flex-wrap gap-8">
                        ${exitRules.map(renderCondition).join('') || '<span class="text-muted">Nenhuma</span>'}
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <h3>🛡️ Gestão de Risco</h3>
                    </div>
                    ${risk ? `
                        <div class="risk-row"><span class="label">Risk per trade</span><span class="value">${risk.position_size_pct}%</span></div>
                        <div class="risk-row"><span class="label">Max open trades</span><span class="value">${risk.max_open_trades}</span></div>
                        <div class="risk-row"><span class="label">Max daily loss</span><span class="value">${risk.max_daily_loss_pct}%</span></div>
                        <div class="risk-row"><span class="label">Max drawdown</span><span class="value">${risk.max_drawdown_pct}%</span></div>
                    ` : '<span class="text-muted">Default</span>'}
                </div>
            </div>

            <!-- Backtest History -->
            <div class="card">
                <div class="card-header">
                    <h3>📋 Histórico de Backtests</h3>
                    <button class="btn btn-sm btn-primary" onclick="Router.navigate('/backtest/run/${id}')">+ Novo Backtest</button>
                </div>
                <div id="strategy-backtests">
                    <div class="loading-overlay"><span class="spinner"></span> Carregando...</div>
                </div>
            </div>
        `;

        // Load backtests for this strategy
        const backtests = await API.get(`/api/v1/backtests/summary?strategy_id=${id}`).catch(() => []);
        const btContainer = document.getElementById('strategy-backtests');

        if (backtests.length === 0) {
            btContainer.innerHTML = `<div class="empty-state">
                <h3>Sem backtests</h3>
                <p>Rode o primeiro backtest para ver resultados aqui</p>
                <button class="btn btn-primary" style="margin-top:12px" onclick="Router.navigate('/backtest/run/${id}')">🚀 Rodar Backtest</button>
            </div>`;
        } else {
            btContainer.innerHTML = `<div class="table-wrap"><table>
                <thead><tr><th>Barras</th><th>Trades</th><th>Win Rate</th><th>Retorno</th><th>Drawdown</th><th>Sharpe</th><th>Data</th></tr></thead>
                <tbody>
                    ${backtests.map(b => `
                        <tr onclick="Router.navigate('/backtest/${b.id}')">
                            <td data-label="Barras">${formatNumber(b.bars_count, 0)}</td>
                            <td data-label="Trades">${b.total_trades}</td>
                            <td data-label="Win Rate"><span class="badge ${b.win_rate >= 0.5 ? 'badge-green' : 'badge-red'}">${formatPct(b.win_rate * 100)}</span></td>
                            <td data-label="Retorno"><span class="badge ${b.total_return_pct >= 0 ? 'badge-green' : 'badge-red'}">${formatPct(b.total_return_pct)}</span></td>
                            <td data-label="Drawdown">${formatPct(b.max_drawdown_pct)}</td>
                            <td data-label="Sharpe">${formatNumber(b.sharpe_ratio)}</td>
                            <td data-label="Data" class="text-muted">${formatDate(b.created_at)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table></div>`;
        }
    } catch (err) {
        document.getElementById('strategy-detail').innerHTML = `<div class="alert alert-error">Erro: ${err.message}</div>`;
    }
});
