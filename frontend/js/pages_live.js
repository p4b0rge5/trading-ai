/**
 * Live Trading Page — manage and monitor live trading sessions in real time.
 */

// ── Toggle account ID field based on mode ────────────────────────────
function toggleAccountIdField() {
    const mode = document.getElementById('live-mode-select').value;
    const group = document.getElementById('live-account-group');
    if (group) {
        group.style.display = (mode === 'live') ? '' : 'none';
    }
}

// ── Start a new session ──────────────────────────────────────────────
async function createSession() {
    const strategyId = parseInt(document.getElementById('live-strategy-select').value);
    const mode = document.getElementById('live-mode-select').value;
    const accountIdInput = document.getElementById('live-account-id')?.value;
    const accountId = (mode === 'live' && accountIdInput) ? parseInt(accountIdInput) : null;

    if (!strategyId) {
        Toast.error('Selecione uma estratégia');
        return;
    }

    const btn = document.getElementById('btn-start-session');
    btn.disabled = true;
    btn.textContent = 'Iniciando...';

    try {
        const payload = {
            strategy_id: strategyId,
            mode: mode,
        };
        if (accountId) {
            payload.account_id = accountId;
        }
        const data = await API.post('/api/v1/live/sessions', payload);
        Toast.success(`Sessão ${data.id} iniciada!`);
        closeLiveModal();
        loadLiveSessions();
    } catch (e) {
        Toast.error(e.message || 'Falha ao iniciar sessão');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Iniciar Sessão';
    }
}

// ── Polling: auto-refresh running sessions ──────────────────────────
let _pollTimers = {};

async function loadLiveSessions() {
    try {
        const sessions = await API.get('/api/v1/live/sessions');
        // Only show running sessions
        const running = sessions.filter(s => s.status === 'running');
        renderSessionsList(running);

        // Clear old timers, start fresh polling for running sessions
        for (const id in _pollTimers) clearInterval(_pollTimers[id]);
        _pollTimers = {};

        for (const s of sessions) {
            if (s.status === 'running') {
                _pollTimers[s.id] = setInterval(async () => {
                    try {
                        const data = await API.get(`/api/v1/live/sessions/${s.id}`);
                        updateSessionCard(s.id, data.session);

                        // Check for new trades → play sound
                        if (data.open_trades && data.open_trades.length > 0) {
                            TradeAudio.checkNewTrades(s.id, data.open_trades);
                        }
                    } catch (e) {
                        console.warn(`[Live] Poll error session ${s.id}:`, e.message);
                    }
                }, 10000); // Refresh every 10s for running sessions
            }
        }
    } catch (e) {
        document.getElementById('live-sessions-list').innerHTML = `
            <div class="empty-state">Erro ao carregar sessões: ${e.message}</div>`;
    }
}

// ── Format helpers ───────────────────────────────────────────────────
function formatPnL(val) {
    const num = typeof val === 'number' ? val : 0;
    const sign = num >= 0 ? '+' : '';
    return `${sign}${formatCurrency(num)}`;
}

function formatWinRate(winRate, closedCount) {
    if (closedCount === 0) {
        return '<span title="Sem trades fechados">N/A</span>';
    }
    return `${winRate.toFixed(1)}%`;
}

function tradeAge(entryTime) {
    if (!entryTime) return '—';
    const elapsed = Date.now() - new Date(entryTime).getTime();
    const mins = Math.floor(elapsed / 60000);
    if (mins < 1) return '< 1 min';
    if (mins < 60) return `${mins}min`;
    const hrs = Math.floor(mins / 60);
    const rm = mins % 60;
    return rm > 0 ? `${hrs}h ${rm}m` : `${hrs}h`;
}

// ── Update a single session card in-place ────────────────────────────
function updateSessionCard(sessionId, session) {
    const card = document.querySelector(`[data-session-id="${sessionId}"]`);
    if (!card) return;

    // Update highlights (Equity + Balance)
    const highlightsRow = card.querySelector('.live-session-highlights');
    if (highlightsRow) {
        highlightsRow.innerHTML = `
            <div class="live-highlight">
                <div class="stat-label">Equity</div>
                <div class="live-highlight-value">${formatCurrency(session.equity || 0)}</div>
            </div>
            <div class="live-highlight">
                <div class="stat-label">Balance</div>
                <div class="live-highlight-value">${formatCurrency(session.balance || 0)}</div>
            </div>
        `;
    }

    // Update stats row (Daily PnL, Unrealized, Abertas, Total, Win Rate)
    const statsRow = card.querySelector('.live-session-stats');
    if (statsRow) {
        const closedCount = session.closed_trades_count || 0;
        const unrealized = session.unrealized_pnl || 0;
        const unrealizedClass = unrealized >= 0 ? 'text-green' : 'text-red';
        const dailyClass = session.daily_pnl > 0 ? 'text-green' : session.daily_pnl < 0 ? 'text-red' : '';

        statsRow.innerHTML = `
            <div class="stat-item">
                <div class="stat-label">Daily P&L</div>
                <div class="stat-value ${dailyClass}">${formatPnL(session.daily_pnl)}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Unrealized</div>
                <div class="stat-value ${unrealizedClass}">${formatPnL(unrealized)}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Abertas</div>
                <div class="stat-value stat-accent">${session.open_trades_count || 0}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Total</div>
                <div class="stat-value">${session.total_trades || 0}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Win Rate</div>
                <div class="stat-value">${formatWinRate(session.win_rate || 0, closedCount)}</div>
            </div>
        `;
    }
}

function renderSessionsList(sessions) {
    const container = document.getElementById('live-sessions-list');
    if (!sessions || sessions.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📡</div>
                <h3>Nenhuma sessão ativa</h3>
                <p>Inicie uma sessão de trading para acompanhar em tempo real.</p>
                <button class="btn btn-primary" onclick="openLiveModal()">
                    Criar Sessão
                </button>
            </div>`;
        return;
    }

    container.innerHTML = sessions.map(s => {
        const modeIcon = s.mode === 'live' ? '🔴' : '🟡';
        const modeLabel = s.mode === 'live' ? 'LIVE' : 'Paper';
        const unrealized = s.unrealized_pnl || 0;
        const unrealizedClass = unrealized >= 0 ? 'text-green' : 'text-red';
        const dailyClass = s.daily_pnl > 0 ? 'text-green' : s.daily_pnl < 0 ? 'text-red' : '';
        const closedCount = s.closed_trades_count || 0;

        return `
        <div class="live-session-card" data-session-id="${s.id}">
            <div class="live-session-header">
                <div class="live-session-title">
                    <span style="font-size:20px">${modeIcon}</span>
                    <span>${s.strategy_name || 'Sem estratégia'}</span>
                    <span class="badge badge-yellow" style="font-size:0.7rem">${modeLabel}</span>
                    <span class="badge badge-green">● Rodando</span>
                </div>
                <div class="live-session-actions">
                    <button class="btn btn-sm btn-secondary" onclick="viewSessionDetail(${s.id})">Detalhes</button>
                    <button class="btn btn-sm btn-danger" onclick="stopSession(${s.id})">Parar</button>
                </div>
            </div>
            <div class="live-session-highlights">
                <div class="live-highlight">
                    <div class="stat-label">Equity</div>
                    <div class="live-highlight-value">${formatCurrency(s.equity || 0)}</div>
                </div>
                <div class="live-highlight">
                    <div class="stat-label">Balance</div>
                    <div class="live-highlight-value">${formatCurrency(s.balance || 0)}</div>
                </div>
            </div>
            <div class="live-session-stats">
                <div class="stat-item">
                    <div class="stat-label">Daily P&L</div>
                    <div class="stat-value ${dailyClass}">${formatPnL(s.daily_pnl)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Unrealized</div>
                    <div class="stat-value ${unrealizedClass}">${formatPnL(unrealized)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Abertas</div>
                    <div class="stat-value stat-accent">${s.open_trades_count || 0}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Total</div>
                    <div class="stat-value">${s.total_trades || 0}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Win Rate</div>
                    <div class="stat-value">${formatWinRate(s.win_rate || 0, closedCount)}</div>
                </div>
            </div>
        </div>`;
    }).join('');
}

// ── View session detail ──────────────────────────────────────────────
async function viewSessionDetail(sessionId) {
    try {
        const data = await API.get(`/api/v1/live/sessions/${sessionId}`);
        renderSessionDetail(data);
    } catch (e) {
        Toast.error(e.message || 'Falha ao carregar detalhes');
    }
}

function renderSessionDetail(data) {
    const session = data.session;
    const openTrades = data.open_trades || [];
    const closedTrades = data.closed_trades || [];

    // Check for new trades → play sound
    if (openTrades.length > 0) {
        TradeAudio.checkNewTrades(session.id, openTrades);
    }

    // Open trades table
    const openTradesHtml = openTrades.length > 0 ? openTrades.map(t => `
        <tr class="trade-open">
            <td><span class="badge ${t.side === 'buy' ? 'badge-green' : 'badge-red'}">${t.side.toUpperCase()}</span></td>
            <td>${formatNumber(t.entry_price, 2)}</td>
            <td>${t.current_price ? formatNumber(t.current_price, 2) : '—'}</td>
            <td>${t.volume}</td>
            <td>${t.sl ? formatNumber(t.sl, 2) : '—'}</td>
            <td>${t.tp ? formatNumber(t.tp, 2) : '—'}</td>
            <td class="${(t.profit || 0) >= 0 ? 'text-green' : 'text-red'}">
                ${formatPnL(t.profit || 0)}
            </td>
            <td class="trade-age">${tradeAge(t.entry_time)}</td>
        </tr>
    `).join('') : `<tr><td colspan="8" class="empty-state">Nenhuma ordem aberta</td></tr>`;

    // Closed trades table
    const closedTradesHtml = closedTrades.length > 0 ? closedTrades.map(t => `
        <tr class="trade-closed">
            <td><span class="badge ${t.side === 'buy' ? 'badge-green' : 'badge-red'}">${t.side.toUpperCase()}</span></td>
            <td>${formatNumber(t.entry_price, 2)}</td>
            <td>${t.exit_price ? formatNumber(t.exit_price, 2) : '—'}</td>
            <td>${t.volume}</td>
            <td>${t.sl ? formatNumber(t.sl, 2) : '—'}</td>
            <td>${t.tp ? formatNumber(t.tp, 2) : '—'}</td>
            <td class="${(t.profit || 0) >= 0 ? 'text-green' : 'text-red'}">
                ${formatPnL(t.profit || 0)}
            </td>
            <td>${t.exit_time ? formatDate(t.exit_time) : '—'}</td>
        </tr>
    `).join('') : `<tr><td colspan="8" class="empty-state">Nenhuma ordem fechada</td></tr>`;

    const unrealized = session.unrealized_pnl || 0;
    const unrealizedClass = unrealized >= 0 ? 'text-green' : 'text-red';
    const closedCount = session.closed_trades_count || 0;

    document.getElementById('detail-body').innerHTML = `
        <div class="detail-stats-row">
            <div class="stat-card">
                <div class="stat-label">Equity</div>
                <div class="stat-value">${formatCurrency(session.equity || 0)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Balance</div>
                <div class="stat-value">${formatCurrency(session.balance || 0)}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Daily P&L</div>
                <div class="stat-value ${session.daily_pnl > 0 ? 'text-green' : session.daily_pnl < 0 ? 'text-red' : ''}">
                    ${formatPnL(session.daily_pnl)} (${(session.daily_pnl_pct || 0).toFixed(2)}%)
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Unrealized P&L</div>
                <div class="stat-value ${unrealizedClass}">
                    ${formatPnL(unrealized)}
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Abertas / Total</div>
                <div class="stat-value">${session.open_trades_count || 0} / ${session.total_trades || 0}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Win Rate</div>
                <div class="stat-value">${formatWinRate(session.win_rate || 0, closedCount)}</div>
            </div>
        </div>

        <h3 class="section-title">Ordens Abertas (${openTrades.length})</h3>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Lado</th>
                        <th>Entry</th>
                        <th>Preço Atual</th>
                        <th>Vol</th>
                        <th>SL</th>
                        <th>TP</th>
                        <th>P&L</th>
                        <th>Tempo</th>
                    </tr>
                </thead>
                <tbody>${openTradesHtml}</tbody>
            </table>
        </div>

        ${closedTrades.length > 0 ? `
        <h3 class="section-title">Histórico Fechadas (${closedTrades.length})</h3>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Lado</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>Vol</th>
                        <th>SL</th>
                        <th>TP</th>
                        <th>P&L</th>
                        <th>Fechada em</th>
                    </tr>
                </thead>
                <tbody>${closedTradesHtml}</tbody>
            </table>
        </div>
        ` : ''}

        <div class="detail-info">
            <p><strong>Modo:</strong> ${session.mode === 'live' ? '🔴 LIVE' : '🟡 Paper (Simulação)'}</p>
            <p><strong>Status:</strong> ${session.status === 'running' ? '● Rodando' : 'Parada'}</p>
            <p><strong>Iniciada:</strong> ${formatDate(session.start_time)}</p>
            ${session.end_time ? `<p><strong>Encerrada:</strong> ${formatDate(session.end_time)}</p>` : ''}
        </div>
    `;

    // Open the detail panel modal
    const panel = document.getElementById('session-detail-panel');
    if (panel) panel.style.display = 'flex';
}

// ── Stop session ─────────────────────────────────────────────────────
async function stopSession(sessionId) {
    if (!confirm('Parar esta sessão e fechar todas as ordens abertas?')) return;

    try {
        await API.post(`/api/v1/live/sessions/${sessionId}/stop`);
        Toast.success('Sessão parada');
        loadLiveSessions();
    } catch (e) {
        Toast.error(e.message || 'Falha ao parar sessão');
    }
}

// ── Modal ────────────────────────────────────────────────────────────
function openLiveModal() {
    const select = document.getElementById('live-strategy-select');
    select.innerHTML = '<option value="">Carregando...</option>';

    API.get('/api/v1/strategies/').then(strategies => {
        select.innerHTML = '<option value="">Selecione uma estratégia...</option>' +
            (strategies.length > 0
                ? strategies.map(s => `<option value="${s.id}">${s.name} (${s.symbol})</option>`).join('')
                : '<option value="">Nenhuma estratégia encontrada — crie uma primeiro</option>');
    }).catch(e => {
        console.error('[Live] Failed to load strategies:', e);
        select.innerHTML = '<option value="">Erro ao carregar — verifique se está logado</option>';
        Toast.error(e.message || 'Falha ao carregar estratégias');
    });
    toggleAccountIdField();
    document.getElementById('live-modal').style.display = 'flex';
}

function closeLiveModal() {
    document.getElementById('live-modal').style.display = 'none';
}

// Close modal on backdrop click
document.addEventListener('click', (e) => {
    if (e.target.id === 'live-modal') closeLiveModal();
});

// ── Sound toggle helper ──────────────────────────────────────────────
function toggleTradeSound() {
    const on = TradeAudio.toggle();
    const btn = document.getElementById('sound-toggle-btn');
    if (btn) {
        btn.textContent = on ? '🔊 Sons: ON' : '🔇 Sons: OFF';
    }
    Toast.success(on ? 'Sons ativados 🔊' : 'Sons desativados 🔇');
}

// ── Page Render ──────────────────────────────────────────────────────
async function renderLivePage(app) {
    // Resume audio context on user interaction (browser policy)
    if (typeof TradeAudio !== 'undefined' && TradeAudio.context) {
        TradeAudio.context.resume?.();
    }

    const soundOn = typeof TradeAudio !== 'undefined' && TradeAudio.enabled;

    app.innerHTML = renderLayout(`
        <div class="page">
            <div class="page-header">
                <h1>📡 Live Trading</h1>
                <div style="display:flex;gap:8px;">
                    <button id="sound-toggle-btn" class="btn btn-sm btn-secondary" onclick="toggleTradeSound()">
                        ${soundOn ? '🔊 Sons: ON' : '🔇 Sons: OFF'}
                    </button>
                    <button class="btn btn-primary" onclick="openLiveModal()">+ Nova Sessão</button>
                </div>
            </div>

            <div id="live-sessions-list">
                <div class="loading"><span class="spinner"></span> Carregando sessões...</div>
            </div>
        </div>

        <!-- Create Session Modal -->
        <div id="live-modal" class="modal" style="display:none">
            <div class="modal-content">
                <div class="modal-header">
                    <h2>Iniciar Sessão de Trading</h2>
                    <button class="modal-close" onclick="closeLiveModal()">×</button>
                </div>
                <div class="modal-body">
                    <div class="form-group">
                        <label>Estratégia</label>
                        <select id="live-strategy-select" class="form-input">
                            <option value="">Carregando...</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Modo</label>
                        <select id="live-mode-select" class="form-input" onchange="toggleAccountIdField()">
                            <option value="paper">🟡 Paper (Simulação — dados reais yfinance)</option>
                            <option value="live">🔴 LIVE (MetaApi)</option>
                        </select>
                    </div>
                    <div class="form-group" id="live-account-group" style="display:none">
                        <label>Conta MetaApi (ID)</label>
                        <input id="live-account-id" type="number" class="form-input"
                            placeholder="ID da conta MetaApi" value="0">
                        <small style="color:var(--text-muted);display:block;margin-top:4px">
                            Necessário apenas no modo LIVE. Paper trading não precisa de conta.
                        </small>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" onclick="closeLiveModal()">Cancelar</button>
                        <button id="btn-start-session" class="btn btn-primary" onclick="createSession()">
                            Iniciar Sessão
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Session Detail Panel (hidden by default) -->
        <div id="session-detail-panel" class="modal" style="display:none">
            <div class="modal-content" style="max-width:900px">
                <div class="modal-header">
                    <h2>Detalhes da Sessão</h2>
                    <button class="modal-close" onclick="document.getElementById('session-detail-panel').style.display='none'">×</button>
                </div>
                <div class="modal-body" id="detail-body"></div>
            </div>
        </div>
    `);

    setActiveNav('/live');
    loadLiveSessions();
}

Router.register('/live', renderLivePage);
