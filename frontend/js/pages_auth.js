/**
 * Auth Pages: Login & Register
 */
Router.register('/login', (app) => {
    app.innerHTML = `
    <div class="auth-page">
        <div class="auth-card">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:24px">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.5">
                    <path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/>
                    <circle cx="18" cy="6" r="2" fill="#3b82f6"/>
                </svg>
                <h2 style="font-size:20px;margin:0">Trading AI</h2>
            </div>
            <h2 style="font-size:18px;font-weight:600">Entrar</h2>
            <p class="subtitle">Acesse sua conta para gerenciar estratégias</p>

            <div id="login-error" class="alert alert-error" style="display:none"></div>

            <div class="form-group">
                <label for="login-email">Email</label>
                <input type="email" class="form-input" id="login-email" name="email" placeholder="seu@email.com" autocomplete="email">
            </div>
            <div class="form-group">
                <label for="login-password">Senha</label>
                <input type="password" class="form-input" id="login-password" name="password" placeholder="••••••••" autocomplete="current-password">
            </div>
            <button class="btn btn-primary btn-full" id="login-btn" onclick="doLogin()">Entrar</button>

            <div class="auth-link">
                Não tem conta? <a onclick="Router.navigate('/register')">Crie uma</a>
            </div>
        </div>
    </div>`;

    // Auto-focus email
    setTimeout(() => {
        const el = document.getElementById('login-email');
        if (el) el.focus();
    }, 100);

    // Enter key
    document.getElementById('login-password')?.addEventListener('keydown', e => {
        if (e.key === 'Enter') doLogin();
    });
});

async function doLogin() {
    const email = document.getElementById('login-email')?.value?.trim();
    const password = document.getElementById('login-password')?.value;
    const errEl = document.getElementById('login-error');
    const btn = document.getElementById('login-btn');

    if (!email || !password) {
        if (errEl) { errEl.style.display = 'flex'; errEl.textContent = 'Preencha todos os campos.'; }
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Entrando...';
    if (errEl) errEl.style.display = 'none';

    try {
        await Auth.login(email, password);
        Toast.success('Login realizado!');
        Router.navigate('/dashboard');
    } catch (err) {
        if (errEl) { errEl.style.display = 'flex'; errEl.textContent = err.message; }
        btn.disabled = false;
        btn.innerHTML = 'Entrar';
    }
}

// ── Register ───────────────────────────────────────────────────────────
Router.register('/register', (app) => {
    app.innerHTML = `
    <div class="auth-page">
        <div class="auth-card">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:24px">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.5">
                    <path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/>
                    <circle cx="18" cy="6" r="2" fill="#3b82f6"/>
                </svg>
                <h2 style="font-size:20px;margin:0">Trading AI</h2>
            </div>
            <h2 style="font-size:18px;font-weight:600">Criar Conta</h2>
            <p class="subtitle">Crie sua conta e comece a operar</p>

            <div id="register-error" class="alert alert-error" style="display:none"></div>

            <div class="form-group">
                <label for="reg-fullname">Nome</label>
                <input type="text" class="form-input" id="reg-fullname" name="fullName" placeholder="Seu nome completo" autocomplete="name">
            </div>
            <div class="form-group">
                <label for="reg-email">Email</label>
                <input type="email" class="form-input" id="reg-email" name="email" placeholder="seu@email.com" autocomplete="email">
            </div>
            <div class="form-group">
                <label for="reg-username">Usuário</label>
                <input type="text" class="form-input" id="reg-username" name="username" placeholder="Escolha um username" autocomplete="username">
            </div>
            <div class="form-group">
                <label for="reg-password">Senha</label>
                <input type="password" class="form-input" id="reg-password" name="password" placeholder="Mínimo 6 caracteres" autocomplete="new-password">
            </div>
            <button class="btn btn-primary btn-full" id="register-btn" onclick="doRegister()">Criar Conta</button>

            <div class="auth-link">
                Já tem conta? <a onclick="Router.navigate('/login')">Faça login</a>
            </div>
        </div>
    </div>`;

    setTimeout(() => {
        const el = document.getElementById('reg-fullname');
        if (el) el.focus();
    }, 100);

    document.getElementById('reg-password')?.addEventListener('keydown', e => {
        if (e.key === 'Enter') doRegister();
    });
});

async function doRegister() {
    const fullName = document.getElementById('reg-fullname')?.value?.trim();
    const email = document.getElementById('reg-email')?.value?.trim();
    const username = document.getElementById('reg-username')?.value?.trim();
    const password = document.getElementById('reg-password')?.value;
    const errEl = document.getElementById('register-error');
    const btn = document.getElementById('register-btn');

    if (!email || !username || !password) {
        if (errEl) { errEl.style.display = 'flex'; errEl.textContent = 'Preencha todos os campos.'; }
        return;
    }
    if (password.length < 6) {
        if (errEl) { errEl.style.display = 'flex'; errEl.textContent = 'Senha deve ter no mínimo 6 caracteres.'; }
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Criando conta...';
    if (errEl) errEl.style.display = 'none';

    try {
        await Auth.register(email, username, password, fullName);
        Toast.success('Conta criada! Faça login.');
        Router.navigate('/login');
    } catch (err) {
        if (errEl) { errEl.style.display = 'flex'; errEl.textContent = err.message; }
        btn.disabled = false;
        btn.innerHTML = 'Criar Conta';
    }
}
