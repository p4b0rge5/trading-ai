/**
 * Dashboard Page: Stats, recent strategies, quick-create prompt
 */
Router.register('/dashboard', async (app) => {
    app.innerHTML = renderLayout(`
        <div class="page-header">
            <h2>Dashboard</h2>
            <p>Visão geral das suas estratégias e backtests</p>
        </div>
        <div id="dashboard-content">
            <div class="loading-overlay"><span class="spinner"></span> Carregando...</div>
        </div>
    `);
    setActiveNav('/dashboard');
    await renderDashboard();
});

async function renderDashboard() {
    const container = document.getElementById('dashboard-content');
    if (!container) {
        console.error('[Dashboard] container not found');
        return;
    }
    try {
        // Fetch user, strategies, backtests in parallel
        const [user, strategies, backtests] = await Promise.all([
            Auth.me(),
            API.get('/api/v1/strategies/').catch(() => []),
            API.get('/api/v1/backtests/summary').catch(() => []),
        ]);
        localStorage.setItem('user', JSON.stringify(user));

        // Aggregate stats
        const totalStrategies = strategies.length;
        const totalBacktests = backtests.length;
        const bestReturn = backtests.length
            ? Math.max(...backtests.map(b => b.total_return_pct), 0)
            : 0;
        const avgWinRate = backtests.length
            ? backtests.reduce((s, b) => s + b.win_rate, 0) / backtests.length
            : 0;
        const totalTrades = backtests.reduce((s, b) => s + b.total_trades, 0);

        container.innerHTML = `
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Estratégias</div>
                    <div class="stat-value accent">${totalStrategies}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Backtests</div>
                    <div class="stat-value accent">${totalBacktests}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Total de Trades</div>
                    <div class="stat-value">${formatNumber(totalTrades, 0)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Melhor Retorno</div>
                    <div class="stat-value ${bestReturn >= 0 ? 'green' : 'red'}">${formatPct(bestReturn)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Win Rate Médio</div>
                    <div class="stat-value ${avgWinRate >= 0.5 ? 'green' : 'red'}">${formatPct(avgWinRate * 100)}</div>
                </div>
            </div>

            <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
                <!-- Quick Create -->
                <div class="card">
                    <div class="card-header">
                        <h3>⚡ Criar Rápido</h3>
                    </div>
                    <p style="font-size:13px;color:var(--text-secondary);margin-bottom:14px">
                        Descreva sua estratégia em linguagem natural e o AI vai criar e testar automaticamente.
                    </p>
                    <textarea class="form-textarea" id="quick-prompt" placeholder="Ex: Quero operar RSI sobre 30 no BTCUSD com stop loss de 100 pips..."></textarea>
                    <div style="margin-top:12px;display:flex;gap:10px">
                        <button class="btn btn-primary" onclick="quickCreate()">
                            Criar e Testar
                        </button>
                    </div>
                    <div id="quick-result" style="margin-top:16px"></div>
                </div>

                <!-- Recent Backtests -->
                <div class="card">
                    <div class="card-header">
                        <h3>📊 Últimos Backtests</h3>
                        <a class="btn btn-sm btn-secondary" onclick="Router.navigate('/backtests')">Ver todos</a>
                    </div>
                    ${backtests.length === 0
                        ? '<div class="empty-state"><h3>Sem backtests</h3><p>Crie uma estratégia e rode um backtest</p></div>'
                        : `<div class="table-wrap"><table>
                            <thead><tr><th>Retorno</th><th>Win Rate</th><th>Trades</th><th>Sharpe</th><th>Data</th></tr></thead>
                            <tbody>
                                ${backtests.slice(0, 8).map(b => `
                                    <tr style="cursor:pointer" onclick="Router.navigate('/backtest/${b.id}')">
                                        <td><span class="badge ${b.total_return_pct >= 0 ? 'badge-green' : 'badge-red'}">${formatPct(b.total_return_pct)}</span></td>
                                        <td>${formatPct(b.win_rate * 100)}</td>
                                        <td>${b.total_trades}</td>
                                        <td>${formatNumber(b.sharpe_ratio)}</td>
                                        <td style="color:var(--text-muted)">${formatDate(b.created_at)}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table></div>`
                    }
                </div>
            </div>

            <!-- Strategies List -->
            <div class="card" style="margin-top:20px">
                <div class="card-header">
                    <h3>📁 Suas Estratégias</h3>
                    <button class="btn btn-sm btn-primary" onclick="Router.navigate('/create')">+ Nova Estratégia</button>
                </div>
                ${strategies.length === 0
                    ? '<div class="empty-state"><h3>Nenhuma estratégia</h3><p>Vá para "Criar Estratégia" para começar</p></div>'
                    : `<div class="table-wrap"><table>
                        <thead><tr><th>Nome</th><th>Symbol</th><th>Timeframe</th><th>Criada em</th><th>Ações</th></tr></thead>
                        <tbody>
                            ${strategies.map(s => `
                                <tr>
                                    <td>
                                        <strong style="cursor:pointer;color:var(--accent)" onclick="Router.navigate('/strategy/${s.id}')">${s.name}</strong>
                                        ${s.description ? `<div style="font-size:12px;color:var(--text-muted);max-width:300px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${s.description}</div>` : ''}
                                    </td>
                                    <td><span class="badge badge-blue">${s.symbol}</span></td>
                                    <td>${s.timeframe}</td>
                                    <td style="color:var(--text-muted)">${formatDate(s.created_at)}</td>
                                    <td>
                                        <button class="btn btn-sm btn-secondary" onclick="Router.navigate('/strategy/${s.id}')">Ver</button>
                                    </td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table></div>`
                }
            </div>
        `;
    } catch (err) {
        console.error('[Dashboard] Load error:', err);
        container.innerHTML = `<div class="alert alert-error">Erro ao carregar: ${err.message}</div>`;
    }
}

async function quickCreate() {
    const prompt = document.getElementById('quick-prompt').value.trim();
    const result = document.getElementById('quick-result');
    if (!prompt || prompt.length < 10) {
        Toast.error('Prompt muito curto. Mínimo 10 caracteres.');
        return;
    }
    result.innerHTML = '<div class="loading-overlay"><span class="spinner"></span> IA criando estratégia...</div>';

    try {
        const data = await API.post('/api/v1/strategies/from-prompt', {
            prompt, run_backtest: true, bars: 2000,
        });
        if (data.backtest) {
            result.innerHTML = `
                <div class="alert alert-success">✅ Estratégia criada com sucesso!</div>
                <div class="stats-grid" style="margin:0">
                    <div class="stat-card" style="padding:12px">
                        <div class="stat-label">Retorno</div>
                        <div class="stat-value ${data.backtest.total_return_pct >= 0 ? 'green' : 'red'}" style="font-size:20px">${formatPct(data.backtest.total_return_pct)}</div>
                    </div>
                    <div class="stat-card" style="padding:12px">
                        <div class="stat-label">Win Rate</div>
                        <div class="stat-value green" style="font-size:20px">${formatPct(data.backtest.win_rate * 100)}</div>
                    </div>
                    <div class="stat-card" style="padding:12px">
                        <div class="stat-label">Trades</div>
                        <div class="stat-value accent" style="font-size:20px">${data.backtest.total_trades}</div>
                    </div>
                </div>
                <div style="margin-top:12px;display:flex;gap:8px">
                    <button class="btn btn-primary" onclick="Router.navigate('/strategy/${data.strategy.id}')">Ver Estratégia</button>
                    <button class="btn btn-secondary" onclick="renderDashboard()">Atualizar</button>
                </div>`;
        }
        Toast.success('Estratégia criada!');
    } catch (err) {
        result.innerHTML = `<div class="alert alert-error">Erro: ${err.message}</div>`;
        Toast.error('Falha ao criar estratégia');
    }
}
