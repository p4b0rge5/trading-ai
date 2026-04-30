/**
 * Strategies List Page
 */
Router.register('/strategies', async (app) => {
    app.innerHTML = renderLayout(`
        <div class="page-header">
            <div>
                <h2>Estratégias</h2>
                <p>Gerencie suas estratégias de trading</p>
            </div>
            <button class="btn btn-primary" onclick="Router.navigate('/create')">+ Nova Estratégia</button>
        </div>
        <div id="strategies-content">
            <div class="loading-overlay"><span class="spinner"></span> Carregando...</div>
        </div>
    `);
    setActiveNav('/strategies');
    await renderStrategies();
});

async function renderStrategies() {
    const container = document.getElementById('strategies-content');
    try {
        const strategies = await API.get('/api/v1/strategies/');
        container.innerHTML = strategies.length === 0
            ? `<div class="card"><div class="empty-state">
                <h3>Nenhuma estratégia</h3>
                <p>Crie sua primeira estratégia com AI</p>
                <button class="btn btn-primary" style="margin-top:16px" onclick="Router.navigate('/create')">Criar Estratégia</button>
            </div></div>`
            : `<div class="table-wrap"><table>
                <thead><tr><th>Nome</th><th>Symbol</th><th>Timeframe</th><th>Indicadores</th><th>Criada em</th><th>Ações</th></tr></thead>
                <tbody>
                    ${strategies.map(s => `
                        <tr>
                            <td>
                                <strong style="cursor:pointer;color:var(--accent)" onclick="Router.navigate('/strategy/${s.id}')">${s.name}</strong>
                                ${s.description ? `<div class="text-sm text-muted" style="max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${s.description}</div>` : ''}
                            </td>
                            <td data-label="Symbol"><span class="badge badge-blue">${s.symbol}</span></td>
                            <td data-label="Timeframe">${s.timeframe}</td>
                            <td data-label="Indicadores">${s.spec_json?.indicators ? s.spec_json.indicators.length + ' indic.' : '—'}</td>
                            <td data-label="Criada em" class="text-muted">${formatDate(s.created_at)}</td>
                            <td data-label="Ações">
                                <div class="btn-group">
                                    <button class="btn btn-sm btn-secondary" onclick="Router.navigate('/strategy/${s.id}')">Ver</button>
                                    <button class="btn btn-sm btn-danger" onclick="deleteStrategy(${s.id})">Apagar</button>
                                </div>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table></div>`;
    } catch (err) {
        container.innerHTML = `<div class="alert alert-error">Erro: ${err.message}</div>`;
    }
}

async function deleteStrategy(id) {
    if (!confirm('Tem certeza? Isso apaga a estratégia e todos os backtests.')) return;
    try {
        await API.delete(`/api/v1/strategies/${id}`);
        Toast.success('Estratégia apagada');
        renderStrategies();
    } catch (err) {
        Toast.error('Falha ao apagar: ' + err.message);
    }
}

async function exportMQL5(id) {
    try {
        const token = Auth.token();
        const resp = await fetch(`${API.base}/api/v1/strategies/${id}/export/mql5`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!resp.ok) throw new Error('Export failed');
        const blob = await resp.blob();
        const filename = resp.headers.get('Content-Disposition')
            ?.match(/filename="(.+)"/)?.[1] || `strategy_${id}.mq5`;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = filename;
        document.body.appendChild(a); a.click();
        document.body.removeChild(a); URL.revokeObjectURL(url);
        Toast.success('MQL5 exportado: ' + filename);
    } catch (err) {
        Toast.error('Falha ao exportar: ' + err.message);
    }
}
