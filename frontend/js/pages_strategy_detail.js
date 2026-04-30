/**
 * Strategy Detail Page
 */
Router.register('/strategy/:id', async (app) => {
    const id = window.location.hash.match(/\/strategy\/(\d+)/)?.[1];
    if (!id) { Router.navigate('/strategies'); return; }

    app.innerHTML = renderLayout(`
        <div class="page-header">
            <h2>Detalhes da Estratégia</h2>
            <p>Indicadores, regras, gestão de risco e resultados</p>
        </div>
        <div id="strategy-detail">
            <div class="loading-overlay"><span class="spinner"></span> Carregando estratégia...</div>
        </div>
    `);

    try {
        const strategy = await API.get(`/api/v1/strategies/${id}`);
        const spec = strategy.spec_json || {};

        const renderIndicator = (ind) => {
            const icons = { sma: '📈', ema: '📈', wma: '📈', rsi: '📊', macd: '📉',
                           bollinger: '📉', stochastic: '📊', atr: '📏', adx: '📈' };
            return `<span class="badge badge-blue">${icons[ind.indicator_type] || '📊'} ${ind.indicator_type.toUpperCase()}(${ind.period})</span>`;
        };

        const renderCondition = (c, prefix) => {
            const type = prefix === 'entry' ? 'entry' : 'exit';
            const badge = type === 'entry' ? 'badge-green' : 'badge-red';
            const label = c.description || c.condition_type || c.exit_type || '';
            return `<span class="badge ${badge}">${label}</span>`;
        };

        document.getElementById('strategy-detail').innerHTML = `
            <!-- Header -->
            <div class="card" style="margin-bottom:20px">
                <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div>
                        <h3 style="font-size:20px;margin-bottom:4px">${strategy.name}</h3>
                        <div style="display:flex;gap:8px;margin-bottom:8px">
                            <span class="badge badge-blue">${strategy.symbol}</span>
                            <span class="badge badge-purple">${strategy.timeframe}</span>
                            <span class="badge badge-yellow">${spec.indicators?.length || 0} indicadores</span>
                        </div>
                        ${strategy.description ? `<p style="font-size:13px;color:var(--text-secondary)">${strategy.description}</p>` : ''}
                    </div>
                    <div style="display:flex;gap:8px">
                        <button class="btn btn-secondary" onclick="exportMQL5(${strategy.id})">⚙️ Exportar MQL5</button>
                        <button class="btn btn-secondary" onclick="Router.navigate('/backtest/run/${id}')">🚀 Novo Backtest</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteStrategy(${strategy.id})">🗑️</button>
                    </div>
                </div>
            </div>

            <!-- Indicators & Rules -->
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
                <div class="card">
                    <h3 style="margin-bottom:12px">📊 Indicadores</h3>
                    <div style="display:flex;flex-wrap:wrap;gap:6px">
                        ${(spec.indicators || []).map(renderIndicator).join('') || '<span style="color:var(--text-muted)">Nenhum</span>'}
                    </div>
                </div>

                <div class="card">
                    <h3 style="margin-bottom:12px">🎯 Regras de Entrada</h3>
                    <div style="display:flex;flex-wrap:wrap;gap:6px">
                        ${(spec.entry_conditions || []).map(c => renderCondition(c, 'entry')).join('') || '<span style="color:var(--text-muted)">Nenhuma</span>'}
                    </div>
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px">
                <div class="card">
                    <h3 style="margin-bottom:12px">🚪 Regras de Saída</h3>
                    <div style="display:flex;flex-wrap:wrap;gap:6px">
                        ${(spec.exit_conditions || []).map(c => renderCondition(c, 'exit')).join('') || '<span style="color:var(--text-muted)">Nenhuma</span>'}
                    </div>
                </div>

                <div class="card">
                    <h3 style="margin-bottom:12px">🛡️ Gestão de Risco</h3>
                    ${spec.risk_management ? `
                        <div style="font-size:13px;line-height:2">
                            <div>Risk per trade: <strong>${spec.risk_management.position_size_pct}%</strong></div>
                            <div>Max open trades: <strong>${spec.risk_management.max_open_trades}</strong></div>
                            <div>Max daily loss: <strong>${spec.risk_management.max_daily_loss_pct}%</strong></div>
                            <div>Max drawdown: <strong>${spec.risk_management.max_drawdown_pct}%</strong></div>
                        </div>
                    ` : '<span style="color:var(--text-muted)">Default</span>'}
                </div>
            </div>

            <!-- Backtest History -->
            <div class="card">
                <h3 style="margin-bottom:12px">📋 Histórico de Backtests</h3>
                <div id="strategy-backtests">
                    <div class="loading-overlay"><span class="spinner"></span> Carregando...</div>
                </div>
            </div>
        `;

        // Load backtests for this strategy
        const backtests = await API.get(`/api/v1/backtests/summary?strategy_id=${id}`).catch(() => []);
        const btContainer = document.getElementById('strategy-backtests');

        if (backtests.length === 0) {
            btContainer.innerHTML = `<div class="empty-state"><h3>Sem backtests</h3>
                <p>Rode o primeiro backtest</p>
                <button class="btn btn-primary" style="margin-top:12px" onclick="Router.navigate('/backtest/run/${id}')">🚀 Backtest</button>
            </div>`;
        } else {
            btContainer.innerHTML = `<div class="table-wrap"><table>
                <thead><tr><th>Barras</th><th>Trades</th><th>Win Rate</th><th>Retorno</th><th>Drawdown</th><th>Sharpe</th><th>Data</th></tr></thead>
                <tbody>
                    ${backtests.map(b => `
                        <tr style="cursor:pointer" onclick="Router.navigate('/backtest/${b.id}')">
                            <td>${formatNumber(b.bars_count, 0)}</td>
                            <td>${b.total_trades}</td>
                            <td><span class="badge ${b.win_rate >= 0.5 ? 'badge-green' : 'badge-red'}">${formatPct(b.win_rate * 100)}</span></td>
                            <td><span class="badge ${b.total_return_pct >= 0 ? 'badge-green' : 'badge-red'}">${formatPct(b.total_return_pct)}</span></td>
                            <td>${formatPct(b.max_drawdown_pct)}</td>
                            <td>${formatNumber(b.sharpe_ratio)}</td>
                            <td style="color:var(--text-muted)">${formatDate(b.created_at)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table></div>`;
        }
    } catch (err) {
        document.getElementById('strategy-detail').innerHTML = `<div class="alert alert-error">Erro: ${err.message}</div>`;
    }
});
