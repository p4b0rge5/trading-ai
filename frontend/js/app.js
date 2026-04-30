/**
 * Trading AI — Core App (Vanilla SPA)
 * Router, Auth, API client, Toast notifications, Page rendering
 */

// ── API Client ─────────────────────────────────────────────────────────
// Auto-detect base path: if URL is /trading/..., use '/trading' as base
const _segments = window.location.pathname.split('/').filter(s => s);
const _basePath = _segments.length > 0 && !_segments[0].includes('.') ? '/' + _segments[0] : '';

const API = {
    base: _basePath,  // e.g. '' or '/trading'

    async request(path, options = {}) {
        const token = localStorage.getItem('token');
        const headers = {
            'Content-Type': 'application/json',
            ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
            ...options.headers,
        };
        const res = await fetch(this.base + path, {
            method: 'GET',
            ...options,
            headers,
        });
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail || `HTTP ${res.status}`);
        }
        return res.json();
    },

    async get(path) { return this.request(path); },
    async post(path, body) { return this.request(path, { method: 'POST', body: JSON.stringify(body) }); },
    async put(path, body) { return this.request(path, { method: 'PUT', body: JSON.stringify(body) }); },
    async delete(path) { return this.request(path, { method: 'DELETE' }); },
};

// ── Auth Service ───────────────────────────────────────────────────────
const Auth = {
    token: () => localStorage.getItem('token'),
    user: () => {
        try { return JSON.parse(localStorage.getItem('user') || 'null'); }
        catch { return null; }
    },

    async login(email, password) {
        const formData = new URLSearchParams({ username: email, password });
        const token = localStorage.getItem('token');
        const headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(`${API.base}/api/v1/auth/login`, {
            method: 'POST',
            headers,
            body: formData,
        });
        if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            throw new Error(body.detail || 'Login failed');
        }
        const data = await res.json();
        localStorage.setItem('token', data.access_token);
        return data;
    },

    async register(email, username, password, fullName) {
        console.log('[Auth] Registering:', { email, username, fullName });
        const data = await API.post('/api/v1/auth/register', {
            email, username, password, full_name: fullName || '',
        });
        console.log('[Auth] Register response:', data);
        localStorage.removeItem('token');
        return data;
    },

    async me() {
        const data = await API.get('/api/v1/auth/me');
        localStorage.setItem('user', JSON.stringify(data));
        return data;
    },

    logout() {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
    },
};

// ── Toast Notifications ────────────────────────────────────────────────
const Toast = {
    el: null,
    init() {
        this.el = document.createElement('div');
        this.el.className = 'toast-container';
        document.body.appendChild(this.el);
    },
    show(message, type = 'info') {
        if (!this.el) this.init();
        const t = document.createElement('div');
        t.className = `toast toast-${type}`;
        t.textContent = message;
        this.el.appendChild(t);
        setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 300); }, 4000);
    },
    success(msg) { this.show(msg, 'success'); },
    error(msg) { this.show(msg, 'error'); },
    info(msg) { this.show(msg, 'info'); },
};

// ── Simple Router (with dynamic route support) ─────────────────────────
const Router = {
    current: '',
    routes: [],  // [{ pattern, regex, fn }]

    register(path, fn) {
        // Detect dynamic segments like :id
        const regex = new RegExp('^' + path.replace(/:(\w+)/g, '(?<$1>[^/]+)') + '$');
        this.routes.push({ path, regex, fn });
    },

    navigate(path) {
        window.location.hash = path;
    },

    init() {
        window.addEventListener('hashchange', () => this.handle());
        this.handle();
    },

    handle() {
        let hash = window.location.hash.slice(1) || '/dashboard';
        // Normalize: ensure hash starts with '/'
        if (hash && !hash.startsWith('/')) hash = '/' + hash;

        // Auth guard
        if (hash !== '/login' && hash !== '/register' && !Auth.token()) {
            window.location.hash = '/login';
            return;
        }

        // Show auth pages without sidebar
        if (hash === '/login' || hash === '/register') {
            this.renderPage(hash, this.matchRoute(hash));
            return;
        }

        // Show app layout for authenticated pages
        this.renderPage(hash, this.matchRoute(hash));
    },

    matchRoute(hash) {
        for (const route of this.routes) {
            if (route.regex.test(hash)) return route.fn;
        }
        return null;
    },

    renderPage(path, fn) {
        const app = document.getElementById('app');
        if (fn) {
            app.innerHTML = '';
            fn(app);
        } else {
            app.innerHTML = `<div class="auth-page"><div class="auth-card" style="text-align:center">
                <h2>404</h2><p class="subtitle">Página não encontrada</p>
            </div></div>`;
        }
        this.current = path;
    },
};

// ── Helpers ────────────────────────────────────────────────────────────
function formatCurrency(n) {
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'USD' }).format(n);
}

function formatPct(n) {
    return `${(n >= 0 ? '+' : '')}${n.toFixed(2)}%`;
}

function formatNumber(n, d = 2) {
    return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d }).format(n);
}

function formatDate(d) {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('pt-BR', {
        day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
    });
}

function classNames(...args) {
    return args.filter(Boolean).join(' ');
}

// ── Boot ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    Toast.init();
    Router.init();
});
