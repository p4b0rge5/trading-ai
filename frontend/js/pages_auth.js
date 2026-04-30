/**
 * Auth Pages: Login & Register
 */

// ── Login ──────────────────────────────────────────────────────────────
Router.register('/login', (app) => {
    app.innerHTML = `
    <div class="auth-page">
        <div class="auth-card">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2">
                    <path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/>
                    <circle cx="18" cy="6" r="2" fill="#3b82f6"/>
                </svg>
                <h2>Trading AI</h2>
            </div>
            <p class="subtitle">Entre na sua conta para continuar</p>
            <form id="login-form">
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" class="form-input" name="email" placeholder="trader@email.com" required>
                </div>
                <div class="form-group">
                    <label>Senha</label>
                    <input type="password" class="form-input" name="password" placeholder="••••••••" required>
                </div>
                <div id="login-error" class="alert alert-error" style="display:none"></div>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center" id="login-btn">
                    Entrar
                </button>
            </form>
            <div class="auth-link">
                Não tem conta? <a onclick="Router.navigate('/register')">Registre-se</a>
            </div>
        </div>
    </div>`;

    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('login-btn');
        const errEl = document.getElementById('login-error');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Entrando...';
        errEl.style.display = 'none';

        try {
            const form = e.target;
            await Auth.login(form.email.value, form.password.value);
            Toast.success('Login realizado com sucesso!');
            Router.navigate('/dashboard');
        } catch (error) {
            console.error('[Auth] Login error:', error);
            errEl.style.display = 'block';
            errEl.textContent = error.message;
            Toast.error('Falha no login');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Entrar';
        }
    });
});

// ── Register ───────────────────────────────────────────────────────────
Router.register('/register', (app) => {
    app.innerHTML = `
    <div class="auth-page">
        <div class="auth-card">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2">
                    <path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/>
                    <circle cx="18" cy="6" r="2" fill="#3b82f6"/>
                </svg>
                <h2>Trading AI</h2>
            </div>
            <p class="subtitle">Crie sua conta gratuita</p>
            <form id="register-form">
                <div class="form-group">
                    <label>Nome completo</label>
                    <input type="text" class="form-input" name="fullName" placeholder="João Trader">
                </div>
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" class="form-input" name="username" placeholder="trader1" required minlength="3">
                </div>
                <div class="form-group">
                    <label>Email</label>
                    <input type="email" class="form-input" name="email" placeholder="trader@email.com" required>
                </div>
                <div class="form-group">
                    <label>Senha</label>
                    <input type="password" class="form-input" name="password" placeholder="Mínimo 6 caracteres" required minlength="6">
                </div>
                <div id="register-error" class="alert alert-error" style="display:none"></div>
                <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center" id="register-btn">
                    Criar conta
                </button>
            </form>
            <div class="auth-link">
                Já tem conta? <a onclick="Router.navigate('/login')">Entrar</a>
            </div>
        </div>
    </div>`;

    document.getElementById('register-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('register-btn');
        const errEl = document.getElementById('register-error');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> Criando...';
        errEl.style.display = 'none';

        try {
            const form = e.target;
            await Auth.register(form.email.value, form.username.value, form.password.value, form.fullName.value);
            Toast.success('Conta criada! Faça login.');
            Router.navigate('/login');
        } catch (error) {
            console.error('[Auth] Register error:', error);
            errEl.style.display = 'block';
            errEl.textContent = error.message;
            Toast.error('Falha no cadastro');
        } finally {
            btn.disabled = false;
            btn.textContent = 'Criar conta';
        }
    });
});
