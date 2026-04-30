/**
 * Dashboard Page: Stats, recent strategies, quick-create prompt
 */
Router.register('/dashboard', async (app) => {
    app.innerHTML = renderLayout(`
        <div class="page-header">
            <div>
                <h2>Dashboard</h2>
                <p>Visão geral das suas estratégias e backtests</p>
            </div>
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
    if (!container) return;
    try {
        const [user, strategies, backtests] = await Promise.all([
            Auth.me(),
            API.get('/api/v1/strategies/').catch(() => []),
            API.get('/api/v1/backtests/summary').catch(() => []),
        ]);
        localStorage.setItem('user', JSON.stringify(user));

        const totalStrategies = strategies.length;
        const totalBacktests = backtests.length;
        const bestReturn = backtests.length ? Math.max(...backtests.map(b => b.total_return_pct), 0) : 0;
        const avgWinRate = backtests.length ? backtests.reduce((s, b) => s + b.win_rate, 0) / backtests.length : 0;
        const totalTrades = backtests.reduce((s, b) => s + b.total_trades, 0);

        container.innerHTML = `
            <!-- Stats Row -->
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
                    <div class="stat-label">Trades Totais</div>
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

            <!-- Two Column: Quick Create + Recent Backtests -->
            <div class="two-col-grid">
                <!-- Quick Create -->
                <div class="card">
                    <div class="card-header">
                        <h3>⚡ Criar Rápido</h3>
                    </div>
                    <p class="text-sm" style="color:var(--text-secondary);margin-bottom:14px">
                        Descreva sua estratégia em linguagem natural. O AI gera, valida e testa automaticamente.
                    </p>
                    <div class="form-group" style="margin-bottom:12px">
                        <textarea class="form-textarea" id="quick-prompt" rows="3"
                            placeholder="Ex: Quero operar RSI sobre 30 no BTCUSD com stop loss de 100 pips..."></textarea>
                    </div>
                    <button class="btn btn-primary btn-full" onclick="quickCreate()">
                        Criar e Testar
                    </button>
                    <div id="quick-result" class="mt-12"></div>
                </div>

                <!-- Recent Backtests -->
                <div class="card">
                    <div class="card-header">
                        <h3>📊 Últimos Backtests</h3>
                        <button class="btn btn-sm btn-secondary" onclick="Router.navigate('/backtests')">Ver todos</button>
                    </div>
                    ${backtests.length === 0
                        ? '<div class="empty-state"><h3>Sem backtests</h3><p>Crie uma estratégia e rode um backtest</p></div>'
                        : `<div class="table-wrap"><table>
                            <thead><tr><th>Retorno</th><th>Win Rate</th><th>Trades</th><th>Sharpe</th><th>Data</th></tr></thead>
                            <tbody>
                                ${backtests.slice(0, 6).map(b => `
                                    <tr onclick="Router.navigate('/backtest/${b.id}')">
                                        <td data-label="Retorno"><span class="badge ${b.total_return_pct >= 0 ? 'badge-green' : 'badge-red'}">${formatPct(b.total_return_pct)}</span></td>
                                        <td data-label="Win Rate">${formatPct(b.win_rate * 100)}</td>
                                        <td data-label="Trades">${b.total_trades}</td>
                                        <td data-label="Sharpe">${formatNumber(b.sharpe_ratio)}</td>
                                        <td data-label="Data" style="color:var(--text-muted)">${formatDate(b.created_at)}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table></div>`
                    }
                </div>
            </div>

            <!-- Strategies List -->
            <div class="card mt-20">
                <div class="card-header">
                    <h3>📁 Suas Estratégias</h3>
                    <button class="btn btn-sm btn-primary" onclick="Router.navigate('/create')">+ Nova</button>
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
                                        ${s.description ? `<div class="text-sm text-muted" style="max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${s.description}</div>` : ''}
                                    </td>
                                    <td data-label="Symbol"><span class="badge badge-blue">${s.symbol}</span></td>
                                    <td data-label="Timeframe">${s.timeframe}</td>
                                    <td data-label="Criada em" class="text-muted">${formatDate(s.created_at)}</td>
                                    <td data-label="Ações">
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
        container.innerHTML = `<div class="alert alert-error">Erro ao carregar: ${err.message}</div>`;
    }
}

async function quickCreate() {
    const prompt = document.getElementById('quick-prompt')?.value?.trim();
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
        const bt = data.backtest || {};
        result.innerHTML = `
            <div class="alert alert-success" style="margin-top:12px">✅ Estratégia criada com sucesso!</div>
            <div class="stats-grid" style="margin-top:12px;margin-bottom:0">
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
            </div>
            <div class="btn-group mt-12">
                <button class="btn btn-primary" onclick="Router.navigate('/strategy/${data.strategy.id}')">Ver Estratégia</button>
                <button class="btn btn-secondary" onclick="renderDashboard()">Atualizar</button>
            </div>`;
        Toast.success('Estratégia criada!');
    } catch (err) {
        result.innerHTML = `<div class="alert alert-error">Erro: ${err.message}</div>`;
        Toast.error('Falha ao criar estratégia');
    }
}
