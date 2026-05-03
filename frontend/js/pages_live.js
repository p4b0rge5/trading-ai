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
        renderSessionsList(sessions);

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

// ── Update a single session card in-place ────────────────────────────
function updateSessionCard(sessionId, session) {
    const card = document.querySelector(`[data-session-id="${sessionId}"]`);
    if (!card) return;

    const statsRow = card.querySelector('.live-session-stats');
    if (statsRow) {
        statsRow.innerHTML = `
            <div class="stat-item">
                <div class="stat-label">Equity</div>
                <div class="stat-value">${formatCurrency(session.equity || 0)}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Balance</div>
                <div class="stat-value">${formatCurrency(session.balance || 0)}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Daily PnL</div>
                <div class="stat-value ${session.daily_pnl >= 0 ? 'text-green' : 'text-red'}">
                    ${formatPct(session.daily_pnl || 0)}
                </div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Trades</div>
                <div class="stat-value">${session.total_trades || 0}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Win Rate</div>
                <div class="stat-value">${(session.win_rate || 0).toFixed(1)}%</div>
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
                <p>Crie uma estratégia e inicie uma sessão de trading ao vivo.</p>
                <button class="btn btn-primary" onclick="openLiveModal()">
                    Criar Sessão
                </button>
            </div>`;
        return;
    }

    container.innerHTML = sessions.map(s => {
        const statusClass = s.status === 'running' ? 'badge-green' : 'badge-gray';
        const modeIcon = s.mode === 'live' ? '🔴' : '🟡';
        return `
        <div class="live-session-card" data-session-id="${s.id}">
            <div class="live-session-header">
                <div class="live-session-title">
                    <span style="font-size:20px">${modeIcon}</span>
                    <span>${s.strategy_name || 'Sem estratégia'}</span>
                    <span class="badge ${statusClass}">${s.status === 'running' ? 'Rodando' : 'Parada'}</span>
                </div>
                <div class="live-session-actions">
                    ${s.status === 'running' ? `
                        <button class="btn btn-sm btn-secondary" onclick="viewSessionDetail(${s.id})">Detalhes</button>
                        <button class="btn btn-sm btn-danger" onclick="stopSession(${s.id})">Parar</button>
                    ` : `
                        <button class="btn btn-sm btn-secondary" onclick="viewSessionDetail(${s.id})">Ver</button>
                    `}
                </div>
            </div>
            <div class="live-session-stats">
                <div class="stat-item">
                    <div class="stat-label">Equity</div>
                    <div class="stat-value">${formatCurrency(s.equity || 0)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Balance</div>
                    <div class="stat-value">${formatCurrency(s.balance || 0)}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Daily PnL</div>
                    <div class="stat-value ${s.daily_pnl >= 0 ? 'text-green' : 'text-red'}">
                        ${formatPct(s.daily_pnl || 0)}
                    </div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Trades</div>
                    <div class="stat-value">${s.total_trades || 0}</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Win Rate</div>
                    <div class="stat-value">${(s.win_rate || 0).toFixed(1)}%</div>
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

    // Check for new trades → play sound
    if (openTrades.length > 0) {
        TradeAudio.checkNewTrades(session.id, openTrades);
    }

    const tradesHtml = openTrades.length > 0 ? openTrades.map(t => `
        <tr>
            <td>${t.side.toUpperCase()}</td>
            <td>${formatNumber(t.entry_price, 5)}</td>
            <td>${t.volume}</td>
            <td>${t.sl ? formatNumber(t.sl, 5) : '—'}</td>
            <td>${t.tp ? formatNumber(t.tp, 5) : '—'}</td>
            <td class="${t.profit >= 0 ? 'text-green' : 'text-red'}">
                ${t.profit !== null ? formatCurrency(t.profit) : '—'}
            </td>
        </tr>
    `).join('') : `<tr><td colspan="6" class="empty-state">Nenhuma ordem aberta</td></tr>`;

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
                <div class="stat-label">Daily PnL</div>
                <div class="stat-value ${session.daily_pnl >= 0 ? 'text-green' : 'text-red'}">
                    ${formatPct(session.daily_pnl || 0)}
                </div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Trades</div>
                <div class="stat-value">${session.total_trades || 0}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Win Rate</div>
                <div class="stat-value">${(session.win_rate || 0).toFixed(1)}%</div>
            </div>
        </div>

        <h3 class="section-title">Ordens Abertas</h3>
        <div class="table-wrapper">
            <table>
                <thead>
                    <tr>
                        <th>Lado</th>
                        <th>Entry</th>
                        <th>Volume</th>
                        <th>SL</th>
                        <th>TP</th>
                        <th>Profit</th>
                    </tr>
                </thead>
                <tbody>${tradesHtml}</tbody>
            </table>
        </div>

        <div class="detail-info">
            <p><strong>Modo:</strong> ${session.mode === 'live' ? '🔴 LIVE' : '🟡 Paper'}</p>
            <p><strong>Status:</strong> ${session.status}</p>
            <p><strong>Iniciada:</strong> ${formatDate(session.start_time)}</p>
        </div>`;

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
            <div class="modal-content" style="max-width:800px">
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
