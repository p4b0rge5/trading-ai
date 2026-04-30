/**
 * Backtest Pages: Run + Results with TradingView Chart
 */

// ── Run Backtest ───────────────────────────────────────────────────────
Router.register('/backtest/run/:id', async (app) => {
    const id = window.location.hash.match(/\/backtest\/run\/(\d+)/)?.[1];
    if (!id) { Router.navigate('/strategies'); return; }

    const strategy = await API.get(`/api/v1/strategies/${id}`).catch(() => null);
    if (!strategy) { Router.navigate('/strategies'); return; }

    app.innerHTML = renderLayout(`
        <div class="page-header">
            <h2>🚀 Rodar Backtest</h2>
            <p>Estratégia: <strong style="color:var(--accent)">${strategy.name}</strong> (${strategy.symbol})</p>
        </div>
        <div class="card" style="max-width:600px">
            <div class="form-group">
                <label>Número de barras</label>
                <select class="form-select" id="bt-bars">
                    <option value="1000">1000 (rápido)</option>
                    <option value="2000" selected>2000</option>
                    <option value="5000">5000 (recomendado)</option>
                    <option value="10000">10000 (completo)</option>
                </select>
            </div>
            <button class="btn btn-primary" onclick="runBacktestFor(${id})" id="bt-btn" style="width:100%;justify-content:center">
                🚀 Executar Backtest
            </button>
            <div id="bt-error" class="alert alert-error" style="display:none;margin-top:12px"></div>
            <div id="bt-result" style="margin-top:16px"></div>
        </div>
    `);
});

async function runBacktestFor(strategyId) {
    const bars = parseInt(document.getElementById('bt-bars').value);
    const btn = document.getElementById('bt-btn');
    const errEl = document.getElementById('bt-error');
    const result = document.getElementById('bt-result');

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Executando backtest...';
    errEl.style.display = 'none';
    result.innerHTML = '<div class="loading-overlay"><span class="spinner"></span> Calculando trades e métricas...</div>';

    try {
        const bt = await API.post('/api/v1/backtests/', { strategy_id: strategyId, bars });
        result.innerHTML = `
            <div class="alert alert-success">✅ Backtest concluído!</div>
            <div class="stats-grid" style="margin:0">
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Retorno</div>
                    <div class="stat-value ${bt.total_return_pct >= 0 ? 'green' : 'red'}" style="font-size:22px">${formatPct(bt.total_return_pct)}</div>
                </div>
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Win Rate</div>
                    <div class="stat-value green" style="font-size:22px">${formatPct(bt.win_rate * 100)}</div>
                </div>
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Trades</div>
                    <div class="stat-value accent" style="font-size:22px">${bt.total_trades}</div>
                </div>
                <div class="stat-card" style="padding:14px">
                    <div class="stat-label">Sharpe</div>
                    <div class="stat-value ${bt.sharpe_ratio >= 1 ? 'green' : 'red'}" style="font-size:22px">${formatNumber(bt.sharpe_ratio)}</div>
                </div>
            </div>
            <div style="margin-top:16px">
                <button class="btn btn-primary" onclick="Router.navigate('/backtest/${bt.id}')">Ver Resultado Completo →</button>
            </div>`;
        Toast.success('Backtest concluído!');
    } catch (err) {
        errEl.style.display = 'block';
        errEl.textContent = err.message;
        Toast.error('Falha no backtest');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🚀 Executar Backtest';
    }
}

// ── Backtest Results ───────────────────────────────────────────────────
Router.register('/backtest/:id', async (app) => {
    const id = window.location.hash.match(/\/backtest\/(\d+)/)?.[1];
    if (!id) { Router.navigate('/backtests'); return; }

    app.innerHTML = renderLayout(`
        <div class="page-header">
            <h2>📊 Resultado do Backtest</h2>
            <p>Métricas, gráfico de equity e trades</p>
        </div>
        <div id="backtest-detail">
            <div class="loading-overlay"><span class="spinner"></span> Carregando resultados...</div>
        </div>
    `);

    try {
        const data = await API.get(`/api/v1/backtests/${id}`);
        const bt = data.backtest;
        const trades = data.trades || [];

        // Render metrics
        let html = `
            <div class="stats-grid" style="margin-bottom:24px">
                <div class="stat-card"><div class="stat-label">Retorno Total</div>
                    <div class="stat-value ${bt.total_return_pct >= 0 ? 'green' : 'red'}">${formatPct(bt.total_return_pct)}</div></div>
                <div class="stat-card"><div class="stat-label">Net Profit</div>
                    <div class="stat-value ${bt.net_profit >= 0 ? 'green' : 'red'}">${formatCurrency(bt.net_profit)}</div></div>
                <div class="stat-card"><div class="stat-label">Total Trades</div>
                    <div class="stat-value accent">${bt.total_trades}</div></div>
                <div class="stat-card"><div class="stat-label">Win Rate</div>
                    <div class="stat-value ${bt.win_rate >= 0.5 ? 'green' : 'red'}">${formatPct(bt.win_rate * 100)}</div></div>
                <div class="stat-card"><div class="stat-label">Max Drawdown</div>
                    <div class="stat-value red">${formatPct(bt.max_drawdown_pct)}</div></div>
                <div class="stat-card"><div class="stat-label">Sharpe Ratio</div>
                    <div class="stat-value ${bt.sharpe_ratio >= 1 ? 'green' : 'red'}">${formatNumber(bt.sharpe_ratio)}</div></div>
                <div class="stat-card"><div class="stat-label">Profit Factor</div>
                    <div class="stat-value ${bt.profit_factor >= 1 ? 'green' : 'red'}">${formatNumber(bt.profit_factor)}</div></div>
                <div class="stat-card"><div class="stat-label">Barras</div>
                    <div class="stat-value accent">${formatNumber(bt.bars_count, 0)}</div></div>
            </div>

            <!-- Chart -->
            <div class="card" style="margin-bottom:20px">
                <div class="card-header"><h3>📈 Equity Curve</h3></div>
                <div id="equity-chart" class="chart-container"></div>
            </div>

            <!-- Trades Table -->
            <div class="card">
                <div class="card-header">
                    <h3>📋 Trades (${trades.length})</h3>
                </div>
                ${trades.length === 0
                    ? '<p style="color:var(--text-muted)">Nenhum trade encontrado</p>'
                    : `<div class="table-wrap"><table>
                        <thead><tr><th>#</th><th>Side</th><th>Entry</th><th>Exit</th><th>Profit</th><th>Reason</th></tr></thead>
                        <tbody>
                            ${trades.map(t => `
                                <tr>
                                    <td>${t.trade_number}</td>
                                    <td><span class="badge ${t.side === 'BUY' ? 'badge-green' : 'badge-red'}">${t.side}</span></td>
                                    <td>${formatDate(t.entry_time)}</td>
                                    <td>${formatDate(t.exit_time)}</td>
                                    <td><span class="${t.profit >= 0 ? 'badge badge-green' : 'badge badge-red'}">${t.profit >= 0 ? '+' : ''}${formatNumber(t.profit)}</span></td>
                                    <td style="max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text-muted)">${t.reason || '—'}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table></div>`
                }
            </div>
        `;

        document.getElementById('backtest-detail').innerHTML = html;

        // Render equity chart
        renderEquityChart(trades);

    } catch (err) {
        document.getElementById('backtest-detail').innerHTML = `<div class="alert alert-error">Erro: ${err.message}</div>`;
    }
});

// ── Equity Chart with TradingView Lightweight Charts ──────────────────
async function renderEquityChart(trades) {
    const container = document.getElementById('equity-chart');
    if (!container || trades.length === 0) return;

    // Load TradingView Lightweight Charts
    const script = document.createElement('script');
    script.src = 'https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js';
    script.onload = () => {
        try {
            const { createChart } = LightweightCharts;

            // Build equity curve from trades
            let equity = 10000;
            const equityData = [{ time: 0, value: equity }];

            trades.forEach(t => {
                equity += (t.profit || 0);
                equityData.push({ time: t.trade_number, value: equity });
            });

            const chart = createChart(container, {
                width: container.clientWidth,
                height: container.clientHeight,
                layout: {
                    backgroundColor: '#1a2234',
                    textColor: '#94a3b8',
                    fontSize: 12,
                },
                grid: {
                    vertLines: { color: 'rgba(42,53,80,0.5)' },
                    horzLines: { color: 'rgba(42,53,80,0.5)' },
                },
                crosshair: { mode: 0 },
                rightPriceScale: { borderVisible: false },
                timeScale: { borderVisible: false, timeVisible: false },
            });

            const line = chart.addLineSeries({
                color: '#3b82f6',
                lineWidth: 2,
                lastValueVisible: true,
                priceLineVisible: true,
            });

            line.setData(equityData);

            // Add profit/loss markers
            const markers = trades.map(t => ({
                position: t.profit >= 0 ? 'below' : 'above',
                color: t.profit >= 0 ? '#22c55e' : '#ef4444',
                shape: t.profit >= 0 ? 'arrowUp' : 'arrowDown',
                text: `$${Math.abs(t.profit || 0).toFixed(0)}`,
                time: t.trade_number,
            }));
            line.setMarkers(markers);

            chart.timeScale().fitContent();

            // Responsive
            const resize = new ResizeObserver(entries => {
                if (entries.length === 0) return;
                chart.applyOptions({ width: entries[0].contentRect.width });
            });
            resize.observe(container);
        } catch (e) {
            container.innerHTML = `<div style="padding:20px;color:var(--text-muted)">Chart error: ${e.message}</div>`;
        }
    };
    document.head.appendChild(script);
}

// ── Backtests List Page ────────────────────────────────────────────────
Router.register('/backtests', async (app) => {
    app.innerHTML = renderLayout(`
        <div class="page-header">
            <h2>Backtests</h2>
            <p>Histórico de todos os seus backtests</p>
        </div>
        <div id="backtests-list">
            <div class="loading-overlay"><span class="spinner"></span> Carregando...</div>
        </div>
    `);
    setActiveNav('/backtests');

    try {
        const backtests = await API.get('/api/v1/backtests/summary');
        const container = document.getElementById('backtests-list');

        if (backtests.length === 0) {
            container.innerHTML = `<div class="card"><div class="empty-state">
                <h3>Nenhum backtest</h3>
                <p>Crie uma estratégia e rode um backtest</p>
            </div></div>`;
            return;
        }

        container.innerHTML = `<div class="card"><div class="table-wrap"><table>
            <thead><tr><th>ID</th><th>Barras</th><th>Trades</th><th>Win Rate</th><th>Retorno</th><th>Profit</th><th>DD</th><th>Sharpe</th><th>Data</th></tr></thead>
            <tbody>
                ${backtests.map(b => `
                    <tr style="cursor:pointer" onclick="Router.navigate('/backtest/${b.id}')">
                        <td>#${b.id}</td>
                        <td>${formatNumber(b.bars_count, 0)}</td>
                        <td>${b.total_trades}</td>
                        <td><span class="badge ${b.win_rate >= 0.5 ? 'badge-green' : 'badge-red'}">${formatPct(b.win_rate * 100)}</span></td>
                        <td><span class="badge ${b.total_return_pct >= 0 ? 'badge-green' : 'badge-red'}">${formatPct(b.total_return_pct)}</span></td>
                        <td>${formatCurrency(b.net_profit)}</td>
                        <td>${formatPct(b.max_drawdown_pct)}</td>
                        <td>${formatNumber(b.sharpe_ratio)}</td>
                        <td style="color:var(--text-muted)">${formatDate(b.created_at)}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table></div></div>`;
    } catch (err) {
        document.getElementById('backtests-list').innerHTML = `<div class="alert alert-error">Erro: ${err.message}</div>`;
    }
});
