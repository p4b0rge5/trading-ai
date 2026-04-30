/**
 * App Layout: Sidebar + Content wrapper with mobile hamburger menu
 */
function renderLayout(content) {
    const user = Auth.user();
    const initial = user ? (user.full_name || user.username || '?')[0].toUpperCase() : '?';

    return `
    <div class="app-layout">
        <!-- Mobile Top Bar -->
        <div class="mobile-bar">
            <button class="hamburger" onclick="toggleSidebar()" aria-label="Menu">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 12h18M3 6h18M3 18h18"/>
                </svg>
            </button>
            <span class="brand">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.5">
                    <path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/>
                    <circle cx="18" cy="6" r="2" fill="#3b82f6"/>
                </svg>
                Trading AI
            </span>
            <div class="avatar" style="width:28px;height:28px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:white;flex-shrink:0">${initial}</div>
        </div>

        <!-- Overlay (mobile only) -->
        <div class="sidebar-overlay" id="sidebar-overlay" onclick="toggleSidebar()"></div>

        <!-- Sidebar -->
        <nav class="sidebar" id="sidebar">
            <div class="sidebar-brand">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.5">
                    <path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/>
                    <circle cx="18" cy="6" r="2" fill="#3b82f6"/>
                </svg>
                <div><h1>Trading AI</h1><span class="version">v0.2</span></div>
            </div>
            <div class="sidebar-nav">
                <button class="nav-link" onclick="Router.navigate('/dashboard')" data-page="/dashboard">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
                    Dashboard
                </button>
                <button class="nav-link" onclick="Router.navigate('/strategies')" data-page="/strategies">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
                    Estratégias
                </button>
                <button class="nav-link" onclick="Router.navigate('/create')" data-page="/create">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>
                    Criar Estratégia
                </button>
                <button class="nav-link" onclick="Router.navigate('/backtests')" data-page="/backtests">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
                    Backtests
                </button>
                <button class="nav-link" onclick="Router.navigate('/live')" data-page="/live">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="2"/><line x1="12" y1="2" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="22"/></svg>
                    Live Trading
                </button>
            </div>
            <div class="sidebar-user">
                <div class="avatar">${initial}</div>
                <div class="user-info">
                    <div class="user-name">${user?.full_name || user?.username || 'User'}</div>
                    <div class="user-email">${user?.email || ''}</div>
                </div>
                <button class="btn-logout" onclick="Auth.logout();Router.navigate('/login')" title="Sair">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16,17 21,12 16,7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                </button>
            </div>
        </nav>

        <main class="main-content">
            ${content}
        </main>
    </div>`;
}

// ── Toggle Sidebar (mobile) ─────────────────────────────────────────────
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    if (!sidebar || !overlay) return;
    sidebar.classList.toggle('open');
    overlay.classList.toggle('open');
}

// Close sidebar when navigating (mobile)
function closeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    if (sidebar) sidebar.classList.remove('open');
    if (overlay) overlay.classList.remove('open');
}

// ── Active Nav Helper ──────────────────────────────────────────────────
function setActiveNav(path) {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.dataset.page === path);
    });
    closeSidebar();
}

// ── Strategy Card Renderer (shared by dashboard + strategies page) ──────
function renderStrategyCard(s) {
    const spec = s.spec_json || {};
    const indicators = spec.indicators || [];
    const indLabels = indicators.slice(0, 3).map(ind => ind.indicator_type).join(', ');
    const indMore = indicators.length > 3 ? ` +${indicators.length - 3}` : '';
    const icon = s.symbol.includes('USD') && s.symbol.length === 6 ? '💱' : '📈';

    return `
        <div class="strategy-card" onclick="Router.navigate('/strategy/${s.id}')">
            <div class="strategy-card-body">
                <div class="strategy-card-main">
                    <span class="strategy-card-icon">${icon}</span>
                    <div class="strategy-card-info">
                        <div class="strategy-card-name">${s.name}</div>
                        ${s.description ? `<div class="strategy-card-desc">${s.description}</div>` : ''}
                    </div>
                </div>
                <div class="strategy-card-meta">
                    <span class="badge badge-blue">${s.symbol}</span>
                    <span class="badge badge-purple">${s.timeframe}</span>
                    <span class="badge badge-yellow">${indicators.length} indicador${indicators.length !== 1 ? 'es' : ''}${indMore}</span>
                    ${indLabels ? `<span class="strategy-card-indicators">${indLabels}</span>` : ''}
                </div>
            </div>
            <div class="strategy-card-footer">
                <span class="text-muted text-sm">${formatDate(s.created_at)}</span>
                <div class="strategy-card-actions">
                    <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); Router.navigate('/strategy/${s.id}')">Detalhes</button>
                    <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteStrategy(${s.id})">Apagar</button>
                </div>
            </div>
        </div>
    `;
}
