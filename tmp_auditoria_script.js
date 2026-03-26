const API_BASE = '/api/crm/vendas';
        const API_AUX = '/api/crm';
        
        let vendas = [];
        let vendaEmAuditoria = null;
        let globalStatusOptions = [];
        let planosOptions = [];
        let formasPagamentoOptions = [];
        let debounceRepTimer; 

        const modalAuditoria = new bootstrap.Modal(document.getElementById('modalAuditoria'));
        const modalReprovacao = new bootstrap.Modal(document.getElementById('modal-reprovacao'));
        const modalAprovacao = new bootstrap.Modal(document.getElementById('modal-aprovacao'));
        const modalAgendamento = new bootstrap.Modal(document.getElementById('modal-agendamento'));
        const modalLigacoesAuditoria = new bootstrap.Modal(document.getElementById('modal-ligacoes-auditoria'));
        let auditoriaVoiceConfig = { voice_provider: 'zenvia', sonax_ramais: [] };

        // =========================================================================
        // FUNÇÃO FETCH PADRONIZADA (SUBSTITUI API CLIENT EXTERNO)
        // =========================================================================
        function extrairMensagemErroApi(errorText, statusText = 'Erro na requisição') {
            if (!errorText) return statusText;
            try {
                const parsed = JSON.parse(errorText);
                if (typeof parsed === 'string') return parsed;
                if (parsed.detail) return parsed.detail;
                if (parsed.error) return parsed.error;
                const primeiroCampo = Object.keys(parsed || {})[0];
                const valorCampo = parsed?.[primeiroCampo];
                if (Array.isArray(valorCampo) && valorCampo.length) return `${primeiroCampo}: ${valorCampo[0]}`;
                if (typeof valorCampo === 'string' && valorCampo.trim()) return `${primeiroCampo}: ${valorCampo}`;
            } catch (_) {
                return errorText;
            }
            return statusText;
        }

        function mensagemErroAmigavel(err, fallback = 'Não foi possível concluir a ação.') {
            const msg = (err && err.message) ? String(err.message) : String(err || '');
            if (!msg) return fallback;
            if (msg.includes('cliente_cpf_cnpj')) return 'CPF/CNPJ já cadastrado para outro cliente. Verifique o documento informado.';
            if (msg.toLowerCase().includes('ordem_servico')) return 'O.S inválida. Use 8 dígitos ou X-12DÍGITOS.';
            return msg;
        }

        async function apiFetch(endpoint, options = {}) {
            const token = localStorage.getItem('accessToken');
            const headers = {
                'Content-Type': 'application/json',
                ...(token ? { 'Authorization': `Bearer ${token}` } : {})
            };
            const config = { ...options, headers };
            
            try {
                const response = await fetch(endpoint, config);
                if (response.status === 401) { logout(); return null; }
                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(extrairMensagemErroApi(errorText, response.statusText));
                }
                if (response.status === 204) return null;
                return await response.json();
            } catch (e) { throw e; }
        }

        function aplicarMascaraOs(valor) {
            let v = String(valor || '').replace(/[^\d-]/g, '');
            const semHifen = v.replace(/-/g, '');
            if (v.includes('-')) {
                const partes = v.split('-');
                const primeiro = (partes[0] || '').replace(/\D/g, '').slice(0, 1);
                const resto = (partes.slice(1).join('') || '').replace(/\D/g, '').slice(0, 12);
                return primeiro + (primeiro ? '-' : '') + resto;
            }
            if (semHifen.length <= 8) return semHifen;
            const primeiro = semHifen.slice(0, 1);
            const resto = semHifen.slice(1, 13);
            return primeiro + '-' + resto;
        }

        /** Carrega o banner "Próximo TT da vez" (primeiro da fila do Controle de TTs) para destacar na auditoria. */
        let proximoTTMatriculaAtual = null;

        async function carregarProximoTTBanner() {
            const banner = document.getElementById('proximo-tt-banner');
            const matEl = document.getElementById('proximo-tt-matricula');
            const diasEl = document.getElementById('proximo-tt-dias');
            if (!banner || !matEl || !diasEl) return;
            try {
                const data = await apiFetch(`${API_AUX}/controle-tts/proximo/`);
                if (data && data.proximo) {
                    proximoTTMatriculaAtual = data.proximo.matricula_vendedor || null;
                    matEl.textContent = proximoTTMatriculaAtual || '—';
                    const dias = data.proximo.dias_sem_vender;
                    if (dias !== null && dias !== undefined) {
                        diasEl.textContent = '(' + dias + ' dias sem vender)';
                    } else {
                        diasEl.textContent = '(sem venda válida registrada)';
                    }
                    banner.style.display = 'flex';
                } else {
                    proximoTTMatriculaAtual = null;
                    banner.style.display = 'none';
                }
            } catch (_) {
                proximoTTMatriculaAtual = null;
                banner.style.display = 'none';
            }
        }

        /** Marca o resultado do uso do "próximo TT" (deu certo = venda registrada, não deu certo = não foi possível) e atualiza o banner para o próximo. */
        async function marcarProximoTTResultado(tipo) {
            if (!proximoTTMatriculaAtual) return;
            const hoje = new Date();
            const dataStr = hoje.getFullYear() + '-' + String(hoje.getMonth() + 1).padStart(2, '0') + '-' + String(hoje.getDate()).padStart(2, '0');
            const body = { matricula_vendedor: proximoTTMatriculaAtual, data: dataStr, tipo: tipo };
            try {
                await apiFetch(`${API_AUX}/controle-tts/tratado/`, { method: 'POST', body: JSON.stringify(body) });
                await carregarProximoTTBanner();
            } catch (e) {
                alert('Erro ao marcar: ' + (e.message || 'tente novamente.'));
            }
        }

        if (typeof window.jQuery === 'undefined') {
            alert('Falha ao carregar dependência da tela de Auditoria (jQuery). Recarregue a página.');
        } else $(document).ready(function() {
            if (!localStorage.getItem('accessToken')) { window.location.href = '/'; return; }
            carregarProximoTTBanner();
            ['#agenda-os', '#repro-os'].forEach(function(sel) {
                $(sel).on('input blur', function() {
                    this.value = aplicarMascaraOs(this.value);
                });
            });
            $('#btn-proximo-tt-deu-certo').on('click', function() { marcarProximoTTResultado('tratado'); });
            $('#btn-proximo-tt-nao-deu').on('click', function() { marcarProximoTTResultado('nao_vendas'); });
            $(document).on('input', '.uppercase-input', function() { this.value = this.value.toUpperCase(); });
            $(document).on('input', '.lowercase-input', function() { this.value = this.value.toLowerCase(); });
            
            $('#repro-status').change(function() {
                const text = $(this).find('option:selected').text().toUpperCase();
                if(text.includes('AGUARDANDO PAGAMENTO')) $('#div-campos-aguardando-pagamento').slideDown();
                else { $('#div-campos-aguardando-pagamento').slideUp(); $('#repro-os').val(''); }
            });

            // Monitoramento do campo de CPF do Representante
            $('#audit-cpf-rep').on('input', function() {
                const val = $(this).val().replace(/\D/g, '');
                clearTimeout(debounceRepTimer);
                if(val.length >= 11) {
                    debounceRepTimer = setTimeout(() => buscarRepresentante(val), 600);
                }
            });

            $('#audit-cep').on('blur', function() {
                const cep = $(this).val().replace(/\D/g, '');
                if (cep.length !== 8) return;
                $('#audit-logradouro').val('Carregando...');
                // ViaCEP permite CORS: chamada direta no navegador (não depende da rede do servidor)
                fetch(`https://viacep.com.br/ws/${cep}/json/`)
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (data.erro) {
                            alert("CEP não encontrado.");
                            $('#audit-logradouro').val('');
                            return;
                        }
                        $('#audit-logradouro').val((data.logradouro || '').toUpperCase());
                        $('#audit-bairro').val((data.bairro || '').toUpperCase());
                        $('#audit-cidade').val((data.localidade || '').toUpperCase());
                        $('#audit-uf').val((data.uf || '').toUpperCase());
                        $('#audit-numero').focus();
                    })
                    .catch(function() {
                        alert("Erro ao buscar CEP. Verifique sua conexão ou tente novamente.");
                        $('#audit-logradouro').val('');
                    });
            });

            $('#filtro-pesquisa').on('keypress', function(e) { if (e.which === 13) aplicarFiltrosAuditoria(); });
            $(document).on('change', 'input[name="aba-data-auditoria"]', function() { carregarVendasPendentes(); });
            $('#filtro-status-tratamento').on('change', function() { carregarVendasPendentes(); });
            $(document).on('change', 'input[name="aba-principal"]', function() {
                const aba = document.querySelector('input[name="aba-principal"]:checked');
                const valor = aba ? aba.value : 'lista';
                const listVisible = (valor === 'lista');
                $('#painel-lista').toggle(listVisible);
                $('#painel-lista-tabela').toggle(listVisible);
                $('#painel-resumo').toggle(!listVisible);
                $('#btn-atualizar-lista').toggle(listVisible);
                if (valor === 'resumo') carregarResumoAuditoria();
            });
            carregarAuxiliares().then(() => {
                carregarVendasPendentes();
            });
        });

        // =========================================================================
        // FUNÇÕES AUXILIARES DE LÓGICA
        // =========================================================================
        function atualizarSaudacao() {
            const hora = new Date().getHours();
            let saudacao = "Bom dia";
            if (hora >= 12 && hora < 18) saudacao = "Boa tarde";
            else if (hora >= 18) saudacao = "Boa noite";
            $('#script-saudacao').text(saudacao);
        }

        function copiarCampo(id, apenasNumeros = false) {
            let valor = document.getElementById(id).value;
            if(!valor) return;
            if (apenasNumeros) valor = valor.replace(/\D/g, "");
            navigator.clipboard.writeText(valor).then(() => {
                const icon = document.getElementById('btn-icon-' + id);
                if(icon) {
                    const originalClass = icon.className;
                    icon.className = "bi bi-check-lg text-success";
                    setTimeout(() => { icon.className = originalClass; }, 2000);
                }
            });
        }

        function proximaAba(tabId) {
            const triggerEl = document.getElementById(tabId);
            bootstrap.Tab.getOrCreateInstance(triggerEl).show();
        }

        function mascaraCPF(i) {
            let v = i.value;
            if(v.length > 14) { 
                v = v.replace(/\D/g, "").replace(/^(\d{2})(\d)/, "$1.$2").replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3").replace(/\.(\d{3})(\d)/, ".$1/$2").replace(/(\d{4})(\d)/, "$1-$2");
            } else { 
                v = v.replace(/\D/g, "").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
            }
            i.value = v;
        }

        function mascaraTelefone(i) {
            let v = i.value.replace(/\D/g, "").replace(/^(\d{2})(\d)/g, "($1) $2").replace(/(\d)(\d{4})$/, "$1-$2");
            i.value = v;
        }

        function mascaraCEP(i) {
            let v = i.value.replace(/\D/g, "").replace(/^(\d{5})(\d)/, "$1-$2");
            i.value = v;
        }

        function aplicarMascarasManuais() {
            const els = ['audit-cliente-cpf', 'audit-tel1', 'audit-tel2', 'audit-cep', 'audit-cpf-rep'];
            els.forEach(id => {
                const el = document.getElementById(id);
                if(el && el.value) {
                    if(id.includes('cpf')) mascaraCPF(el);
                    else if(id.includes('tel')) mascaraTelefone(el);
                    else if(id.includes('cep')) mascaraCEP(el);
                }
            });
        }

        // =========================================================================
        // CARREGAMENTO DE DADOS (COM API FETCH + PAGINAÇÃO)
        // =========================================================================
        async function carregarAuxiliares() {
            try {
                // MUDANÇA: Usando apiFetch e page_size=1000
                const [statusRes, planosRes, pagRes] = await Promise.all([
                    apiFetch(`${API_AUX}/status/?tipo=Tratamento&page_size=1000`),
                    apiFetch(`${API_AUX}/planos/?page_size=1000`),
                    apiFetch(`${API_AUX}/formas-pagamento/?page_size=1000`)
                ]);
                
                // Normalização: Array direto ou objeto paginado
                globalStatusOptions = Array.isArray(statusRes) ? statusRes : (statusRes.results || []);
                planosOptions = Array.isArray(planosRes) ? planosRes : (planosRes.results || []);
                formasPagamentoOptions = Array.isArray(pagRes) ? pagRes : (pagRes.results || []);
                
                const selPlano = $('#audit-plano');
                const selPag = $('#audit-pagamento');
                selPlano.empty().append('<option value="">Selecione...</option>');
                selPag.empty().append('<option value="">Selecione...</option>');
                
                planosOptions.forEach(p => selPlano.append(`<option value="${p.id}">${p.nome}</option>`));
                formasPagamentoOptions.forEach(f => selPag.append(`<option value="${f.id}">${f.nome}</option>`));
                // Status tratamento da auditoria é preenchido pela lista (apenas statuses que existem na lista)
            } catch(e) {
                console.error("Erro auxiliares", e);
            }
        }

        function aplicarFiltrosAuditoria() {
            carregarVendasPendentes();
        }

        function carregarResumoAuditoria() {
            $('#loadingOverlay').show();
            apiFetch(API_BASE + '/resumo_auditoria/')
                .then(function(data) {
                    if (!data) return;
                    $('#resumo-mes-ano').text(data.periodo && data.periodo.mes_ano ? data.periodo.mes_ano : '—');
                    $('#resumo-total-vendas').text(data.total_vendas_mes != null ? data.total_vendas_mes : '—');
                    $('#resumo-total-envios').text(data.total_envios_resumo != null ? data.total_envios_resumo : '—');
                    $('#resumo-total-confirmacoes').text(data.total_confirmacoes != null ? data.total_confirmacoes : '—');
                    renderResumoTabela('resumo-lista-vendas', data.lista_vendas || [], true);
                    renderResumoTabela('resumo-lista-envios', data.lista_envios_resumo || [], false);
                    renderResumoConfirmacoes('resumo-lista-confirmacoes', data.lista_confirmacoes || []);
                    renderResumoPorBo('resumo-lista-por-bo', data.lista_por_bo || []);
                })
                .catch(function(e) { console.error(e); alert('Erro ao carregar resumo.'); })
                .finally(function() { $('#loadingOverlay').hide(); });
        }

        function formatarDataResumo(d) {
            if (!d) return '—';
            try { return new Date(d).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }); } catch(e) { return d; }
        }

        function renderResumoTabela(tbodyId, lista, comStatus) {
            var tbody = document.getElementById(tbodyId);
            if (!tbody) return;
            tbody.innerHTML = '';
            var colCount = comStatus ? 8 : 7;
            if (!lista || lista.length === 0) {
                tbody.innerHTML = '<tr><td colspan="' + colCount + '" class="text-center text-muted py-3">Nenhum registro.</td></tr>';
                return;
            }
            lista.forEach(function(v) {
                var nome = v.cliente_nome_razao_social || 'N/A';
                var cpf = v.cliente_cpf_cnpj || '—';
                var vendedor = v.vendedor_nome || '—';
                var produto = v.plano_nome || '—';
                var dataStr = formatarDataResumo(v.data_criacao);
                var statusNome = v.status_tratamento_nome || '—';
                var acao = '<button class="btn btn-sm btn-auditar" onclick="retomarAuditoria(' + v.id + ')"><i class="bi bi-headset"></i> Auditar</button>';
                var row = '<tr><td class="fw-bold text-primary">#' + v.id + '</td><td>' + dataStr + '</td><td>' + nome + '</td><td class="small">' + cpf + '</td><td>' + vendedor + '</td><td>' + produto + '</td>';
                if (comStatus) row += '<td><span class="badge bg-secondary">' + statusNome + '</span></td>';
                row += '<td class="text-end">' + acao + '</td></tr>';
                tbody.insertAdjacentHTML('beforeend', row);
            });
        }

        function renderResumoConfirmacoes(tbodyId, lista) {
            var tbody = document.getElementById(tbodyId);
            if (!tbody) return;
            tbody.innerHTML = '';
            if (!lista || lista.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted py-3">Nenhuma confirmação no mês.</td></tr>';
                return;
            }
            lista.forEach(function(v) {
                var nome = v.cliente_nome_razao_social || 'N/A';
                var cpf = v.cliente_cpf_cnpj || '—';
                var vendedor = v.vendedor_nome || '—';
                var produto = v.plano_nome || '—';
                var dataConf = formatarDataResumo(v.data_confirmacao_auditoria);
                var acao = '<button class="btn btn-sm btn-auditar" onclick="retomarAuditoria(' + v.id + ')"><i class="bi bi-headset"></i> Auditar</button>';
                var row = '<tr><td class="fw-bold text-primary">#' + v.id + '</td><td>' + dataConf + '</td><td>' + nome + '</td><td class="small">' + cpf + '</td><td>' + vendedor + '</td><td>' + produto + '</td><td class="text-end">' + acao + '</td></tr>';
                tbody.insertAdjacentHTML('beforeend', row);
            });
        }

        function renderResumoPorBo(tbodyId, lista) {
            var tbody = document.getElementById(tbodyId);
            if (!tbody) return;
            tbody.innerHTML = '';
            if (!lista || lista.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-3">Nenhum BO com atividade no mês.</td></tr>';
                return;
            }
            lista.forEach(function(row) {
                var tr = '<tr><td class="fw-bold">' + (row.username || '—') + '</td><td class="text-center">' + (row.tratou != null ? row.tratou : 0) + '</td><td class="text-center text-primary">' + (row.enviou != null ? row.enviou : 0) + '</td><td class="text-center text-success">' + (row.confirmaram != null ? row.confirmaram : 0) + '</td></tr>';
                tbody.insertAdjacentHTML('beforeend', tr);
            });
        }

        function getParamsDataAuditoria() {
            const aba = document.querySelector('input[name="aba-data-auditoria"]:checked');
            const valor = aba ? aba.value : 'todos';
            if (valor === 'todos') return {};
            const hoje = new Date();
            hoje.setHours(0, 0, 0, 0);
            let dataInicio = '', dataFim = '';
            if (valor === 'hoje') {
                dataFim = dataInicio = hoje.toISOString().slice(0, 10);
            } else if (valor === 'ontem') {
                const ontem = new Date(hoje);
                ontem.setDate(ontem.getDate() - 1);
                dataFim = dataInicio = ontem.toISOString().slice(0, 10);
            } else if (valor === '7dias') {
                const sete = new Date(hoje);
                sete.setDate(sete.getDate() - 6);
                dataInicio = sete.toISOString().slice(0, 10);
                dataFim = hoje.toISOString().slice(0, 10);
            }
            const params = {};
            if (dataInicio) params.data_inicio = dataInicio;
            if (dataFim) params.data_fim = dataFim;
            return params;
        }

        function atualizarTextoPlano() {
            const planoId = $('#audit-plano').val(); const pagId = $('#audit-pagamento').val();
            const plano = planosOptions.find(p => p.id == planoId); 
            const pag = formasPagamentoOptions.find(f => f.id == pagId);
            
            let valorFinal = 0;
            if (plano) {
                valorFinal = parseFloat(plano.valor);
                if (pag && (pag.nome.toUpperCase().includes('CRÉDITO') || pag.nome.toUpperCase().includes('CREDITO'))) {
                    valorFinal -= 10;
                }
                $('#txt-plano-nome').text(plano.nome.toUpperCase());
                $('#txt-plano-valor').text('R$ ' + valorFinal.toFixed(2).replace('.', ','));
            } else {
                $('#txt-plano-nome').text('...');
                $('#txt-plano-valor').text('R$ ...');
            }
            
            if (pag) { 
                $('#txt-pagamento-nome').text(pag.nome.toUpperCase()); 
                atualizarScriptPagamento(pag.nome.toUpperCase());
            } else { 
                $('#txt-pagamento-nome').text('...');
                $('#script-pagamento-cartao, #script-pagamento-dacc, #script-pagamento-boleto').hide();
            }
        }

        function atualizarScriptPagamento(nomePagamento) {
            $('#script-pagamento-cartao, #script-pagamento-dacc, #script-pagamento-boleto').hide();
            if (nomePagamento.includes('CRÉDITO') || nomePagamento.includes('CREDITO')) $('#script-pagamento-cartao').show();
            else if (nomePagamento.includes('DÉBITO') || nomePagamento.includes('DEBITO') || nomePagamento.includes('DACC')) $('#script-pagamento-dacc').show();
            else if (nomePagamento.includes('BOLETO')) $('#script-pagamento-boleto').show();
        }

        // =========================================================================
        // LISTAGEM DE VENDAS (COM API FETCH E LOOKUP)
        // =========================================================================
        function carregarVendasPendentes() {
            $('#loadingOverlay').show();
            const params = new URLSearchParams();
            params.set('page_size', '200');
            const statusId = $('#filtro-status-tratamento').val();
            if (statusId) params.set('status_tratamento_id', statusId);
            const pesquisa = ($('#filtro-pesquisa').val() || '').trim();
            if (pesquisa) params.set('search', pesquisa);
            const dataParams = getParamsDataAuditoria();
            if (dataParams.data_inicio) params.set('data_inicio', dataParams.data_inicio);
            if (dataParams.data_fim) params.set('data_fim', dataParams.data_fim);
            const query = params.toString();
            apiFetch(`${API_BASE}/pendentes_auditoria/?${query}`)
            .then(data => {
                const tbody = $('#listaVendasBody'); tbody.empty();
                // Normalização (resposta pode ser paginada ou lista direta)
                const lista = Array.isArray(data) ? data : (data.results || []);
                const currentStatusVal = $('#filtro-status-tratamento').val();

                // Preencher select de status apenas com os statuses que existem na lista retornada
                const statusMap = new Map();
                (lista || []).forEach(v => {
                    let id = null, nome = '-';
                    if (v.status_tratamento != null && v.status_tratamento !== undefined) {
                        if (typeof v.status_tratamento === 'object') {
                            id = v.status_tratamento.id; nome = v.status_tratamento.nome || nome;
                        } else {
                            id = v.status_tratamento; nome = v.status_tratamento_nome || nome;
                        }
                    } else if (v.status_tratamento_nome) {
                        nome = v.status_tratamento_nome; id = v.status_tratamento;
                    }
                    if (id != null && id !== '' && !statusMap.has(id)) statusMap.set(id, nome || `Status ${id}`);
                });
                const statusList = Array.from(statusMap.entries()).map(([id, nome]) => ({ id, nome })).sort((a, b) => (a.nome || '').localeCompare(b.nome || ''));
                const selStatus = $('#filtro-status-tratamento');
                selStatus.off('change').empty().append('<option value="">Todos</option>');
                statusList.forEach(s => selStatus.append(`<option value="${s.id}">${s.nome}</option>`));
                if (currentStatusVal && statusList.some(s => String(s.id) === String(currentStatusVal))) selStatus.val(currentStatusVal);
                else selStatus.val('');
                selStatus.on('change', function() { carregarVendasPendentes(); });

                if (!lista || lista.length === 0) { tbody.append('<tr><td colspan="9" class="text-center text-muted py-4">Nenhuma venda pendente.</td></tr>'); return; }

                lista.forEach(v => {
                    let nomeCliente = 'N/A'; let cpfCliente = '-';
                    if (v.cliente && typeof v.cliente === 'object') { nomeCliente = v.cliente.nome_razao_social || 'N/A'; cpfCliente = v.cliente.cpf_cnpj || '-'; } 
                    else { nomeCliente = v.cliente_nome_razao_social || 'N/A'; cpfCliente = v.cliente_cpf_cnpj || '-'; }
                    
                    let nomeVendedor = v.vendedor_nome || (v.vendedor ? (v.vendedor.username || v.vendedor) : 'N/A');
                    
                    // LOOKUP PRODUTO
                    let produto = '-';
                    if (v.plano_nome) { produto = v.plano_nome; }
                    else if (v.plano) {
                        if (typeof v.plano === 'object') { produto = v.plano.nome || '-'; }
                        else {
                            const pEncontrado = planosOptions.find(p => String(p.id) === String(v.plano));
                            produto = pEncontrado ? pEncontrado.nome : `(ID: ${v.plano})`;
                        }
                    }

                    // LOOKUP STATUS TRATAMENTO
                    let statusNome = '-';
                    if (v.status_tratamento_nome) { statusNome = v.status_tratamento_nome; }
                    else if (v.status_tratamento) {
                        if (typeof v.status_tratamento === 'object') { statusNome = v.status_tratamento.nome || '-'; }
                        else {
                            const sEncontrado = globalStatusOptions.find(s => String(s.id) === String(v.status_tratamento));
                            statusNome = sEncontrado ? sEncontrado.nome : `(ID: ${v.status_tratamento})`;
                        }
                    }

                    let dataFormatada = v.data_criacao ? new Date(v.data_criacao).toLocaleString('pt-BR', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '-';
                    
                    let infoEdicao = '-';
                    if (v.nome_editor) {
                        let dataEdicao = v.data_ultima_alteracao ? new Date(v.data_ultima_alteracao).toLocaleString('pt-BR', {day: '2-digit', month: '2-digit', hour: '2-digit', minute:'2-digit'}) : '';
                        infoEdicao = `<div><strong class="text-dark small">${v.nome_editor}</strong></div><div class="edit-info">${dataEdicao}</div>`;
                    }

                    let token = localStorage.getItem('accessToken');
                    let myId = token ? parseInt(jwt_decode(token).user_id) : null;
                    const nomeAuditor = v.auditor_atual_nome || (v.auditor_atual ? `ID: ${v.auditor_atual}` : '-');
                    
                    let auditorInfo = '-'; let btnHtml = ''; let classeLinha = '';
                    
                    if (v.auditor_atual && v.auditor_atual !== myId) {
                        classeLinha = 'locked-row';
                        auditorInfo = `<div class="d-flex align-items-center gap-2"><span class="auditor-badge text-truncate" style="max-width: 100px;" title="${nomeAuditor}"><i class="bi bi-lock-fill"></i> ${nomeAuditor}</span><button class="btn btn-sm btn-outline-danger border-0" onclick="forcarLiberacao(${v.id})" title="Desbloquear"><i class="bi bi-unlock"></i></button></div>`;
                        btnHtml = `<span class="badge bg-secondary">Em uso</span>`;
                    } else if (v.auditor_atual === myId) {
                        auditorInfo = `<span class="auditor-badge bg-success text-white">VOCÊ</span>`;
                        btnHtml = `<button class="btn btn-auditar" onclick="retomarAuditoria(${v.id})"><i class="bi bi-play-circle"></i> Continuar</button>`;
                    } else {
                        btnHtml = `<button class="btn btn-auditar" onclick="tentarAuditoria(${v.id})"><i class="bi bi-headset"></i> Auditar</button>`;
                    }
                    
                    tbody.append(`<tr class="${classeLinha}"><td class="fw-bold text-primary">#${v.id}</td><td>${dataFormatada}</td><td><div class="fw-bold text-dark">${nomeCliente}</div><div class="small text-muted" style="font-size: 0.8rem;">${cpfCliente}</div></td><td>${nomeVendedor}</td><td>${produto}</td><td><span class="badge bg-warning text-dark">${statusNome}</span></td><td>${infoEdicao}</td><td>${auditorInfo}</td><td class="text-end">${btnHtml}</td></tr>`);
                });
            })
            .catch(e => { console.error(e); alert('Erro ao carregar vendas.'); })
            .finally(() => $('#loadingOverlay').hide());
        }

        // =========================================================================
        // FUNÇÕES DE AÇÃO (USANDO API FETCH)
        // =========================================================================
        function tentarAuditoria(id) { if(!confirm(`Iniciar auditoria da Venda #${id}?`)) return; alocarVenda(id); }
        function retomarAuditoria(id) { carregarDadosNoScript(id); }
        
        function alocarVenda(id) { 
            $('#loadingOverlay').show(); 
            apiFetch(`${API_BASE}/${id}/alocar-auditoria/`, { method: 'POST' })
            .then(() => carregarDadosNoScript(id))
            .catch(err => { 
                $('#loadingOverlay').hide(); 
                alert('Erro ao alocar venda (talvez já esteja em uso).'); 
                carregarVendasPendentes(); 
            }); 
        }
        
        function forcarLiberacao(id) { 
            if(!confirm("Forçar desbloqueio?")) return; 
            $('#loadingOverlay').show(); 
            apiFetch(`${API_BASE}/${id}/liberar-auditoria/`, { method: 'POST' })
            .then(() => { alert("Liberada."); carregarVendasPendentes(); })
            .catch(() => { $('#loadingOverlay').hide(); alert("Sem permissão."); }); 
        }

        function carregarDadosNoScript(id) {
            apiFetch(`${API_BASE}/${id}/`).then(res => {
                // Normalização para objeto de venda
                let v = Array.isArray(res) ? (res[0] || {}) : (res.results ? res.results[0] : res);
                vendaEmAuditoria = v;
                $('#loadingOverlay').hide(); $('#auditoria_id_venda').val(v.id); $('#script-id-venda').text(v.id); $('#script-vendedor-nome').text(v.vendedor_nome || 'N/A');
                try { $('#script-user-logado').text(jwt_decode(localStorage.getItem('accessToken')).username || 'Consultor'); } catch(e) {}
                const nomeCli = (v.cliente && v.cliente.nome_razao_social) ? v.cliente.nome_razao_social : (v.cliente_nome_razao_social || '');
                const cpfCli = (v.cliente && v.cliente.cpf_cnpj) ? v.cliente.cpf_cnpj : (v.cliente_cpf_cnpj || '');
                const emailCli = (v.cliente && v.cliente.email) ? v.cliente.email : (v.cliente_email || '');
                $('#audit-cliente-nome').val(nomeCli); $('#audit-cliente-cpf').val(cpfCli); $('#audit-email').val(emailCli);
                $('#audit-nome-mae').val(v.nome_mae || ''); $('#audit-data-nasc').val(v.data_nascimento || '');
                $('#audit-tel1').val(v.telefone1 || ''); $('#audit-tel2').val(v.telefone2 || '');
                $('#audit-cep').val(v.cep || ''); $('#audit-logradouro').val(v.logradouro || ''); $('#audit-numero').val(v.numero_residencia || '');
                $('#audit-complemento').val(v.complemento || ''); $('#audit-bairro').val(v.bairro || ''); $('#audit-cidade').val(v.cidade || '');
                $('#audit-uf').val(v.estado || ''); $('#audit-ref').val(v.ponto_referencia || '');
                if(v.plano) $('#audit-plano').val(v.plano.id || v.plano); if(v.forma_pagamento) $('#audit-pagamento').val(v.forma_pagamento.id || v.forma_pagamento);
                $('#audit-data-agendamento').val(v.data_agendamento || ''); $('#audit-turno-agendamento').val(v.periodo_agendamento || ''); $('#script-obs-venda').val(v.observacoes || '');
                
                // Exibir informação de telefone fixo
                const temFixo = v.tem_fixo === true || v.tem_fixo === 'true' || v.tem_fixo === 1;
                const fixoDisplay = $('#audit-tem-fixo-display');
                if (temFixo) {
                    fixoDisplay.html('<span style="font-size: 0.8rem; font-weight: 600; color: #198754;">Sim</span>');
                } else {
                    fixoDisplay.html('<span style="font-size: 0.8rem; font-weight: 600; color: #6c757d;">Não</span>');
                }
                
                $('#repro-data').val(v.data_abertura ? v.data_abertura.split('T')[0] : '');

                // Carrega campos do Representante e exibe se for CNPJ
                $('#audit-cpf-rep').val(v.cpf_representante_legal || '');
                $('#audit-nome-rep').val(v.nome_representante_legal || '');
                
                const cpfLimpo = cpfCli.replace(/\D/g, '');
                if (cpfLimpo.length > 11 || v.cpf_representante_legal) {
                    $('#div-representante').show();
                } else {
                    $('#div-representante').hide();
                }

                calcularIdadeAuto(); atualizarTextoPlano(); aplicarMascarasManuais(); 
                atualizarSaudacao();
                $('.form-check-input').prop('checked', false);
                $('.nav-link').removeClass('active'); $('.tab-pane').removeClass('show active');
                $('#pills-identidade-tab').addClass('active'); $('#pills-identidade').addClass('show active');
                modalAuditoria.show();

                // Alerta quando venda foi gerada com O.S. automática (vendedor já abriu o pedido)
                const geradaOsAuto = v.gerada_os_automatica === true || v.gerada_os_automatica === 'true';
                const alertaOsAuto = document.getElementById('alerta-gerada-os-automatica');
                if (alertaOsAuto) {
                    if (geradaOsAuto) {
                        alertaOsAuto.style.display = 'block';
                        alertaOsAuto.innerHTML = '<i class="bi bi-info-circle-fill me-2"></i><strong>Vendedor já abriu o pedido.</strong> Realizar apenas auditoria e registrar a venda.';
                    } else {
                        alertaOsAuto.style.display = 'none';
                    }
                }

                // Título: protocolo confirmação cliente (auditoria)
                const protocoloBadge = document.getElementById('script-protocolo-badge');
                if (protocoloBadge) {
                    if (v.protocolo_confirmacao_auditoria) {
                        protocoloBadge.style.display = 'inline';
                        protocoloBadge.textContent = '— [PROTOCOLO GERADO COM A CONFIRMAÇÃO DO CLIENTE]';
                    } else {
                        protocoloBadge.style.display = 'none';
                    }
                }

                // Aba 6. Retorno Auditoria
                const statusEl = document.getElementById('audit-retorno-status');
                const protocoloBox = document.getElementById('audit-retorno-protocolo-box');
                const protocoloEl = document.getElementById('audit-retorno-protocolo');
                const dataBox = document.getElementById('audit-retorno-data-box');
                const dataEl = document.getElementById('audit-retorno-data');
                const btnNaoConfirmado = document.getElementById('btn-audit-marcar-nao-confirmado');
                if (v.cliente_confirmou_auditoria === true) {
                    statusEl.textContent = 'Sim'; statusEl.className = 'badge bg-success';
                    if (v.protocolo_confirmacao_auditoria) {
                        protocoloBox.style.display = 'block'; protocoloEl.textContent = v.protocolo_confirmacao_auditoria;
                    } else { protocoloBox.style.display = 'none'; }
                    if (v.data_confirmacao_auditoria) {
                        dataBox.style.display = 'block';
                        try {
                            const d = new Date(v.data_confirmacao_auditoria);
                            dataEl.textContent = d.toLocaleString('pt-BR');
                        } catch (e) { dataEl.textContent = v.data_confirmacao_auditoria; }
                    } else { dataBox.style.display = 'none'; }
                    btnNaoConfirmado.style.display = 'none';
                } else if (v.cliente_confirmou_auditoria === false) {
                    statusEl.textContent = 'Não'; statusEl.className = 'badge bg-danger';
                    protocoloBox.style.display = 'none'; dataBox.style.display = 'none';
                    btnNaoConfirmado.style.display = 'none';
                } else {
                    statusEl.textContent = 'Aguardando'; statusEl.className = 'badge bg-secondary';
                    protocoloBox.style.display = 'none'; dataBox.style.display = 'none';
                    btnNaoConfirmado.style.display = 'inline-block';
                }
            }).catch(e => { console.error(e); $('#loadingOverlay').hide(); alert('Erro ao abrir venda.'); });
        }

        async function buscarRepresentante(cpf) {
            const inputNome = $('#audit-nome-rep');
            inputNome.val("BUSCANDO...");
            inputNome.prop('readonly', true).css('background-color', '#e9ecef');

            try {
                const data = await apiFetch(`${API_AUX}/clientes/?search=${cpf}`);
                let encontrado = false;

                if(data && data.length > 0) {
                    const rep = data.find(cli => cli.cpf_cnpj.replace(/\D/g, '') === cpf.replace(/\D/g, ''));
                    if (rep) {
                        inputNome.val(rep.nome_razao_social);
                        inputNome.prop('readonly', true).css('background-color', '#e9ecef');
                        encontrado = true;
                    }
                }

                if (!encontrado) {
                    inputNome.val("");
                    inputNome.prop('readonly', false).css('background-color', '#ffffff');
                    inputNome.focus();
                }
            } catch(e) {
                console.error("Erro rep:", e);
                inputNome.val("");
                inputNome.prop('readonly', false).css('background-color', '#ffffff');
            }
        }

        function calcularIdadeAuto() {
            const dn = $('#audit-data-nasc').val(); if(!dn) { $('#audit-idade-calc').val(''); return; }
            const nasc = new Date(dn); const hoje = new Date(); let idade = hoje.getFullYear() - nasc.getFullYear();
            if (hoje.getMonth() < nasc.getMonth() || (hoje.getMonth() === nasc.getMonth() && hoje.getDate() < nasc.getDate())) idade--;
            $('#audit-idade-calc').val(idade + ' anos');
        }

        function coletarDadosAuditoria() {
            return {
                cliente_nome: $('#audit-cliente-nome').val(), cliente_cpf: $('#audit-cliente-cpf').val(), cliente_email: $('#audit-email').val(),
                nome_mae: $('#audit-nome-mae').val(), data_nascimento: $('#audit-data-nasc').val(), telefone1: $('#audit-tel1').val(), telefone2: $('#audit-tel2').val(),
                cep: $('#audit-cep').val(), logradouro: $('#audit-logradouro').val(), numero: $('#audit-numero').val(), complemento: $('#audit-complemento').val(),
                bairro: $('#audit-bairro').val(), cidade: $('#audit-cidade').val(), estado: $('#audit-uf').val(), referencia: $('#audit-ref').val(),
                plano: $('#audit-plano').val(), forma_pagamento: $('#audit-pagamento').val(), data_agendamento: $('#audit-data-agendamento').val(), periodo_agendamento: $('#audit-turno-agendamento').val(),
                observacoes: $('#script-obs-venda').val(),
                cpf_representante_legal: $('#audit-cpf-rep').val(),
                nome_representante_legal: $('#audit-nome-rep').val()
            };
        }

        async function salvarRascunhoAuditoria(dadosAdicionais = {}) {
            const d = coletarDadosAuditoria();
            const rascunho = {
                cliente_email: d.cliente_email || null,
                cliente_nome_razao_social: d.cliente_nome || null,
                cliente_cpf_cnpj: d.cliente_cpf || null,
                observacoes: d.observacoes || null,
                nome_mae: d.nome_mae || null,
                data_nascimento: d.data_nascimento || null,
                telefone1: d.telefone1 || null,
                telefone2: d.telefone2 || null,
                cep: d.cep || null,
                logradouro: d.logradouro || null,
                numero_residencia: d.numero || null,
                complemento: d.complemento || null,
                bairro: d.bairro || null,
                cidade: d.cidade || null,
                estado: d.estado || null,
                ponto_referencia: d.referencia || null,
                plano: d.plano || null,
                forma_pagamento: d.forma_pagamento || null,
                data_agendamento: d.data_agendamento || null,
                periodo_agendamento: d.periodo_agendamento || null,
                cpf_representante_legal: d.cpf_representante_legal || null,
                nome_representante_legal: d.nome_representante_legal || null,
                ...dadosAdicionais
            };
            Object.keys(rascunho).forEach(key => { if (rascunho[key] === "") rascunho[key] = null; });
            
            try {
                await apiFetch(`${API_BASE}/${vendaEmAuditoria.id}/`, { method: 'PATCH', body: JSON.stringify(rascunho) });
            } catch (e) {
                console.error("Erro ao salvar rascunho:", e);
            }
        }
        
        function validarAuditoriaCompleta() {
            const cep = $('#audit-cep').val();
            const logradouro = $('#audit-logradouro').val();
            const numero = $('#audit-numero').val();
            const plano = $('#audit-plano').val();
            const pagamento = $('#audit-pagamento').val();

            if (!cep || !logradouro || !numero || !plano || !pagamento) {
                alert("Atenção: É obrigatório preencher Endereço (Aba 3) e Oferta/Pagamento (Aba 4) antes de prosseguir.");
                if (!cep || !logradouro || !numero) proximaAba('pills-endereco-tab'); else proximaAba('pills-oferta-tab');
                return false;
            }
            return true;
        }

        function getCpfOuVendaIdParaBiometria() {
            if (vendaEmAuditoria && vendaEmAuditoria.id) return { venda_id: vendaEmAuditoria.id };
            const cpfRep = $('#audit-cpf-rep').val();
            const cpfCli = $('#audit-cliente-cpf').val();
            const cpf = ($('#div-representante').is(':visible') && cpfRep) ? cpfRep : cpfCli;
            const cpfLimpo = (cpf || '').replace(/\D/g, '');
            if (cpfLimpo.length !== 11) return null;
            return { cpf: cpfLimpo };
        }

        async function checarBiometriaBrPronto() {
            const payload = getCpfOuVendaIdParaBiometria();
            if (!payload) { alert('Preencha o CPF do titular (ou do representante legal) na aba Identidade, ou abra uma venda para usar o CPF da venda.'); return; }
            $('#biometria-status-msg').text('Consultando Br Pronto...').removeClass('text-success text-danger').addClass('text-muted');
            $('#btn-checar-biometria').prop('disabled', true);
            try {
                const res = await apiFetch(`${API_AUX}/consultar-biometria-brpronto/`, { method: 'POST', body: JSON.stringify(payload) });
                if (!res.ok) {
                    $('#biometria-status-msg').text(res.error || 'Erro na consulta').removeClass('text-success text-muted').addClass('text-danger');
                    return;
                }
                if (res.aprovada) {
                    $('#check-biometria').prop('checked', true);
                    $('#biometria-status-msg').text('Biometria APROVADA' + (res.data_mais_recente_apta ? ' em ' + res.data_mais_recente_apta : '')).removeClass('text-danger text-muted').addClass('text-success');
                } else {
                    $('#biometria-status-msg').text('Nenhuma biometria com "Doc. Apto para Venda" encontrada para este CPF.').removeClass('text-success text-muted').addClass('text-danger');
                }
            } catch (e) {
                const msg = (e && e.message) ? e.message : String(e);
                $('#biometria-status-msg').text(msg.indexOf('{') >= 0 ? (JSON.parse(msg).error || msg) : msg).removeClass('text-success text-muted').addClass('text-danger');
            } finally {
                $('#btn-checar-biometria').prop('disabled', false);
            }
        }

        async function listarBiometriaBrPronto() {
            const payload = getCpfOuVendaIdParaBiometria();
            if (!payload) { alert('Preencha o CPF do titular (ou do representante legal) na aba Identidade, ou abra uma venda para usar o CPF da venda.'); return; }
            $('#btn-listar-biometria').prop('disabled', true);
            try {
                const res = await apiFetch(`${API_AUX}/consultar-biometria-brpronto/`, { method: 'POST', body: JSON.stringify(payload) });
                const tbody = $('#tbody-biometria-lista');
                const vazia = $('#biometria-lista-vazia');
                tbody.empty();
                if (!res.ok) {
                    vazia.show().text(res.error || 'Erro na consulta');
                    bootstrap.Modal.getOrCreateInstance(document.getElementById('modal-biometria-lista')).show();
                    return;
                }
                const registros = res.registros || [];
                if (registros.length === 0) {
                    vazia.show().text('Nenhum registro encontrado para este CPF.');
                } else {
                    vazia.hide();
                    registros.forEach(function(r) {
                        const tr = $('<tr></tr>');
                        tr.append($('<td></td>').text(r.protocolo || ''));
                        tr.append($('<td></td>').text(r.cpf_cnpj || ''));
                        tr.append($('<td></td>').text(r.n_linha || ''));
                        tr.append($('<td></td>').text(r.data_envio || ''));
                        tr.append($('<td></td>').text(r.data_conferencia || ''));
                        tr.append($('<td></td>').text(r.regional || ''));
                        tr.append($('<td></td>').text(r.cod_pdv || ''));
                        tr.append($('<td></td>').text(r.login || ''));
                        tr.append($('<td></td>').text(r.tipo_servico || ''));
                        tr.append($('<td></td>').text(r.nome_fantasia || ''));
                        const resultado = (r.resultado_analise || '').trim();
                        const tdResultado = $('<td></td>').text(resultado);
                        if (resultado.indexOf('Doc. Apto para Venda') >= 0) tdResultado.addClass('text-success fw-bold');
                        tr.append(tdResultado);
                        tbody.append(tr);
                    });
                }
                bootstrap.Modal.getOrCreateInstance(document.getElementById('modal-biometria-lista')).show();
            } catch (e) {
                const msg = (e && e.message) ? e.message : String(e);
                alert(msg.indexOf('{') >= 0 ? (JSON.parse(msg).error || msg) : msg);
            } finally {
                $('#btn-listar-biometria').prop('disabled', false);
            }
        }

        function validarChecklist() {
            if(!$('#check-biometria').is(':checked')) { alert('Erro: Confirme a Biometria!'); proximaAba('pills-identidade-tab'); return false; }
            if(!$('#check-fibra').is(':checked')) { alert('Erro: Questione sobre Fibra existente!'); proximaAba('pills-endereco-tab'); return false; }
            if(!$('#check-viabilidade').is(':checked')) { alert('Erro: Valide a Viabilidade!'); proximaAba('pills-endereco-tab'); return false; }
            if(!$('#check-maioridade').is(':checked')) { alert('Erro: Confirme que o cliente foi avisado sobre o responsável +18!'); proximaAba('pills-finalizacao-tab'); return false; }
            return true;
        }

        async function enviarResumoPlanoCliente() {
            if (!vendaEmAuditoria || !vendaEmAuditoria.id) { alert('Nenhuma venda em auditoria.'); return; }
            const tel1 = $('#audit-tel1').val();
            if (!tel1 || !String(tel1).replace(/\D/g, '').length) {
                alert('Cadastro sem Celular 1. Preencha o telefone na aba Contato antes de enviar o resumo.');
                return;
            }
            const cep = $('#audit-cep').val();
            const logradouro = $('#audit-logradouro').val();
            const numero = $('#audit-numero').val();
            const plano = $('#audit-plano').val();
            const pagamento = $('#audit-pagamento').val();
            if (!cep || !String(cep).replace(/\D/g, '').length) {
                alert('Preencha o CEP (aba Endereço) antes de enviar o resumo.');
                return;
            }
            if (!logradouro || !String(logradouro).trim()) {
                alert('Preencha o Logradouro (aba Endereço) antes de enviar o resumo.');
                return;
            }
            if (!numero || !String(numero).trim()) {
                alert('Preencha o Número (aba Endereço) antes de enviar o resumo.');
                return;
            }
            if (!plano) {
                alert('Selecione o Plano (aba Oferta & Pagamento) antes de enviar o resumo.');
                return;
            }
            if (!pagamento) {
                alert('Selecione a Forma de Pagamento (aba Oferta & Pagamento) antes de enviar o resumo.');
                return;
            }
            if (!confirm('Enviar resumo do plano ao Cliente (' + tel1 + ')?')) return;
            $('#loadingOverlay').show();
            try {
                // Salva rascunho da auditoria antes de enviar o resumo
                const d = coletarDadosAuditoria();
                const rascunho = {
                    cliente_email: d.cliente_email || null,
                    cliente_nome_razao_social: d.cliente_nome || null,
                    cliente_cpf_cnpj: d.cliente_cpf || null,
                    observacoes: d.observacoes || null,
                    nome_mae: d.nome_mae || null,
                    data_nascimento: d.data_nascimento || null,
                    telefone1: d.telefone1 || null,
                    telefone2: d.telefone2 || null,
                    cep: d.cep || null,
                    logradouro: d.logradouro || null,
                    numero_residencia: d.numero || null,
                    complemento: d.complemento || null,
                    bairro: d.bairro || null,
                    cidade: d.cidade || null,
                    estado: d.estado || null,
                    ponto_referencia: d.referencia || null,
                    plano: d.plano || null,
                    forma_pagamento: d.forma_pagamento || null,
                    data_agendamento: d.data_agendamento || null,
                    periodo_agendamento: d.periodo_agendamento || null,
                    cpf_representante_legal: d.cpf_representante_legal || null,
                    nome_representante_legal: d.nome_representante_legal || null
                };
                Object.keys(rascunho).forEach(key => { if (rascunho[key] === "") rascunho[key] = null; });

                await apiFetch(`${API_BASE}/${vendaEmAuditoria.id}/`, { method: 'PATCH', body: JSON.stringify(rascunho) });

                const res = await apiFetch(`${API_BASE}/${vendaEmAuditoria.id}/enviar-resumo-plano-whatsapp/`, { method: 'POST' });
                alert(res.detail || 'Resumo enviado!');
            } catch (e) {
                const msg = (e && e.message) ? e.message : (typeof e === 'string' ? e : 'Erro ao enviar.');
                try {
                    const parsed = JSON.parse(msg);
                    alert(parsed.detail || msg);
                } catch (_) { alert(msg); }
            } finally {
                $('#loadingOverlay').hide();
            }
        }

        async function atualizarStatusConfirmacaoCliente() {
            if (!vendaEmAuditoria || !vendaEmAuditoria.id) return;
            try {
                const v = await apiFetch(`${API_BASE}/${vendaEmAuditoria.id}/`);
                vendaEmAuditoria = v;
                const statusEl = document.getElementById('audit-retorno-status');
                const protocoloBox = document.getElementById('audit-retorno-protocolo-box');
                const protocoloEl = document.getElementById('audit-retorno-protocolo');
                const dataBox = document.getElementById('audit-retorno-data-box');
                const dataEl = document.getElementById('audit-retorno-data');
                const btnNaoConfirmado = document.getElementById('btn-audit-marcar-nao-confirmado');
                const protocoloBadge = document.getElementById('script-protocolo-badge');
                if (v.cliente_confirmou_auditoria === true) {
                    statusEl.textContent = 'Sim'; statusEl.className = 'badge bg-success';
                    if (v.protocolo_confirmacao_auditoria) {
                        protocoloBox.style.display = 'block'; protocoloEl.textContent = v.protocolo_confirmacao_auditoria;
                    } else { protocoloBox.style.display = 'none'; }
                    if (v.data_confirmacao_auditoria) {
                        dataBox.style.display = 'block';
                        try {
                            const d = new Date(v.data_confirmacao_auditoria);
                            dataEl.textContent = d.toLocaleString('pt-BR');
                        } catch (e) { dataEl.textContent = v.data_confirmacao_auditoria; }
                    } else { dataBox.style.display = 'none'; }
                    btnNaoConfirmado.style.display = 'none';
                    if (protocoloBadge) { protocoloBadge.style.display = 'inline'; protocoloBadge.textContent = '— [PROTOCOLO GERADO COM A CONFIRMAÇÃO DO CLIENTE]'; }
                } else if (v.cliente_confirmou_auditoria === false) {
                    statusEl.textContent = 'Não'; statusEl.className = 'badge bg-danger';
                    protocoloBox.style.display = 'none'; dataBox.style.display = 'none';
                    btnNaoConfirmado.style.display = 'none';
                    if (protocoloBadge) protocoloBadge.style.display = 'none';
                } else {
                    statusEl.textContent = 'Aguardando'; statusEl.className = 'badge bg-secondary';
                    protocoloBox.style.display = 'none'; dataBox.style.display = 'none';
                    btnNaoConfirmado.style.display = 'inline-block';
                    if (protocoloBadge) protocoloBadge.style.display = 'none';
                }
            } catch (e) {
                alert('Erro ao atualizar: ' + (e.message || e));
            }
        }

        async function marcarClienteNaoConfirmado() {
            if (!vendaEmAuditoria || !vendaEmAuditoria.id) return;
            if (!confirm('Marcar que o cliente não confirmou o resumo?')) return;
            $('#loadingOverlay').show();
            try {
                await apiFetch(`${API_BASE}/${vendaEmAuditoria.id}/`, {
                    method: 'PATCH',
                    body: JSON.stringify({ cliente_confirmou_auditoria: false })
                });
                vendaEmAuditoria.cliente_confirmou_auditoria = false;
                document.getElementById('audit-retorno-status').textContent = 'Não';
                document.getElementById('audit-retorno-status').className = 'badge bg-danger';
                document.getElementById('audit-retorno-protocolo-box').style.display = 'none';
                document.getElementById('audit-retorno-data-box').style.display = 'none';
                document.getElementById('btn-audit-marcar-nao-confirmado').style.display = 'none';
                alert('Registrado: cliente não confirmou.');
            } catch (e) {
                alert('Erro ao salvar: ' + (e.message || e));
            } finally {
                $('#loadingOverlay').hide();
            }
        }

        async function finalizarComoAuditada() { 
            if(!validarAuditoriaCompleta()) return;
            if(!validarChecklist()) return;
            if(!confirm("Aprovar venda como AUDITADA?")) return; 
            $('#loadingOverlay').show();
            await salvarRascunhoAuditoria();
            enviarFinalizacao('AUDITADA', $('#script-obs-venda').val(), coletarDadosAuditoria()); 
        }

        function prepararAgendamento() {
            if(!validarAuditoriaCompleta()) return;
            if(!validarChecklist()) return;
            const d = coletarDadosAuditoria();
            modalAuditoria.hide(); 
            $('#agenda-os').val(vendaEmAuditoria.ordem_servico || '');
            $('#agenda-obs').val($('#script-obs-venda').val());
            if(d.data_agendamento) $('#agenda-data-final').val(d.data_agendamento); 
            if(d.periodo_agendamento) $('#agenda-turno-final').val(d.periodo_agendamento);
            modalAgendamento.show();
        }

        async function abrirModalReprovacao() {
            const sel = $('#repro-status');
            sel.empty().append('<option value="">Carregando...</option>');
            try {
                const r = await apiFetch(`${API_AUX}/status/?tipo=Tratamento&page_size=1000`);
                globalStatusOptions = Array.isArray(r) ? r : (r?.results || []);
            } catch(e) { globalStatusOptions = []; }
            sel.empty().append('<option value="">Selecione...</option>');
            if (globalStatusOptions.length > 0) { globalStatusOptions.filter(s => {
                const nome = s.nome.toUpperCase();
                return !(nome === 'AUDITADA' || nome === 'APROVADA' || nome === 'CADASTRADA' || nome.startsWith('APROVADA E '));
            }).forEach(s => sel.append(`<option value="${s.id}">${s.nome}</option>`)); }
            $('#div-campos-aguardando-pagamento').hide(); $('#repro-os').val(''); $('#repro-data').val($('#audit-data-agendamento').val()); $('#repro-turno').val($('#audit-turno-agendamento').val()); $('#repro-obs').val($('#script-obs-venda').val());
            modalReprovacao.show();
        }

        async function confirmarReprovacao() {
            const stId = $('#repro-status').val(); const obs = $('#repro-obs').val(); const stText = $('#repro-status option:selected').text().toUpperCase();
            if(!stId || !obs) { alert('Selecione status e motivo.'); return; }
            $('#loadingOverlay').show();
            if (stText.includes('AGUARDANDO PAGAMENTO')) {
                const os = ($('#repro-os').val() || '').trim(), dt = $('#repro-data').val(), tr = $('#repro-turno').val();
                if (!os || !dt || !tr) { alert('O.S, Data e Turno obrigatórios.'); $('#loadingOverlay').hide(); return; }
                if (!validarFormatoOs(os, 'AGUARDANDO PAGAMENTO')) { $('#loadingOverlay').hide(); return; }
                await salvarRascunhoAuditoria({ ordem_servico: os, data_agendamento: dt, periodo_agendamento: tr });
                const d = coletarDadosAuditoria(); d.data_agendamento = dt; d.periodo_agendamento = tr;
                enviarFinalizacao(stId, obs, d, true);
            } else {
                await salvarRascunhoAuditoria();
                enviarFinalizacao(stId, obs, coletarDadosAuditoria(), true);
            }
        }

        async function salvarAgendamentoFinal() {
            const os = ($('#agenda-os').val() || '').trim(), dt = $('#agenda-data-final').val(), tr = $('#agenda-turno-final').val();
            const obs = $('#agenda-obs').val();
            if(!os || !dt || !tr) { alert('Preencha tudo.'); return; }
            if(!validarFormatoOs(os, 'CADASTRADA')) return;
            $('#loadingOverlay').show();
            try {
                const res = await apiFetch(`${API_AUX}/status/?tipo=Esteira`);
                const lista = Array.isArray(res) ? res : (res.results || []);
                const st = lista.find(s => s.nome.toUpperCase() === 'AGENDADO'); 
                if(!st) throw new Error("Status AGENDADO sumiu.");
                
                // Salva rascunho com todos os dados antes de finalizar
                await salvarRascunhoAuditoria({ ordem_servico: os, data_agendamento: dt, periodo_agendamento: tr, status_esteira: st.id });
                
                const d = coletarDadosAuditoria(); 
                d.data_agendamento = dt; 
                d.periodo_agendamento = tr;
                d.observacoes = obs;
                enviarFinalizacao('CADASTRADA', obs, d, false, true);
            } catch(e) { 
                alert('Erro: ' + e.message); 
                $('#loadingOverlay').hide(); 
            }
        }

        function enviarFinalizacao(st, obs, dados, fechaRep=false, abreZap=false) {
            return apiFetch(`${API_BASE}/${vendaEmAuditoria.id}/finalizar_auditoria/`, { method: 'POST', body: JSON.stringify({ status: st, observacoes: obs, dados_atualizados: dados }) })
            .then(() => { alert('Salvo!'); if(fechaRep) modalReprovacao.hide(); modalAgendamento.hide(); modalAuditoria.hide(); if(abreZap) gerarAprovacaoMsg(dados); else carregarVendasPendentes(); })
            .catch(e => { console.error(e); alert(mensagemErroAmigavel(e, 'Erro ao finalizar.')); })
            .finally(() => { if(!abreZap) $('#loadingOverlay').hide(); });
        }

        function validarFormatoOs(os, contextoStatus = '') {
            const valor = (os || '').trim();
            const regexOs = /^(\d{8}|\d-\d{12})$/;
            if (!regexOs.test(valor)) {
                const sufixo = contextoStatus ? ` para ${contextoStatus}` : '';
                alert(`O.S inválida${sufixo}. Use 8 dígitos (08907507) ou X-12DÍGITOS (4-212051254235).`);
                return false;
            }
            return true;
        }

        function normalizarTelefone(valor) {
            return (valor || '').replace(/\D/g, '');
        }

        function formatarDataHoraLigacao(valor) {
            if (!valor) return '-';
            const dt = new Date(valor);
            if (Number.isNaN(dt.getTime())) return '-';
            return dt.toLocaleString('pt-BR');
        }

        async function abrirModalLigacoesAuditoria() {
            if (!vendaEmAuditoria || !vendaEmAuditoria.id) {
                alert('Abra uma venda na auditoria antes de iniciar uma ligação.');
                return;
            }
            const telefonePreferencial = $('#audit-tel1').val() || vendaEmAuditoria.telefone1 || vendaEmAuditoria.telefone2 || '';
            $('#ligacao-destino').val(telefonePreferencial);
            $('#ligacao-feedback').removeClass('text-danger text-success').addClass('text-muted').text('Pronto para iniciar ligação.');
            modalLigacoesAuditoria.show();
            await carregarOpcoesLigacaoAuditoria();
            carregarLigacoesAuditoria();
        }

        async function carregarOpcoesLigacaoAuditoria() {
            try {
                const r = await apiFetch(`${API_AUX}/auditoria/ligacoes/opcoes/`);
                auditoriaVoiceConfig = r || auditoriaVoiceConfig;
                const rowRamal = document.getElementById('row-ligacao-ramal');
                const rowOrigem = document.getElementById('row-ligacao-origem');
                if (r.voice_provider === 'sonax') {
                    rowRamal.style.display = '';
                    rowOrigem.style.display = 'none';
                    const sel = $('#ligacao-ramal');
                    sel.empty();
                    const ramais = Array.isArray(r.sonax_ramais) ? r.sonax_ramais : [];
                    ramais.forEach((x) => sel.append(new Option(`Ramal ${x}`, String(x))));
                    if (!ramais.length) sel.append(new Option('Configure SONAX_RAMAIS', ''));
                } else {
                    rowRamal.style.display = 'none';
                    rowOrigem.style.display = '';
                }
            } catch (e) {
                console.warn('auditoria opcoes ligacao', e);
            }
        }

        async function iniciarLigacaoGravada() {
            if (!vendaEmAuditoria || !vendaEmAuditoria.id) {
                alert('Nenhuma venda carregada na auditoria.');
                return;
            }

            const destino = normalizarTelefone($('#ligacao-destino').val());
            const origem = normalizarTelefone($('#ligacao-origem').val());
            if (!destino) {
                alert('Informe o telefone de destino.');
                return;
            }

            const payload = {
                destination_number: destino,
                consentimento_declarado: true,
                consentimento_observacao: 'Cliente informado pelo auditor no início da chamada.'
            };
            if (auditoriaVoiceConfig.voice_provider === 'sonax') {
                const ramal = $('#ligacao-ramal').val();
                if (!ramal) {
                    alert('Selecione o ramal SIP.');
                    return;
                }
                payload.sip_extension = ramal;
            } else if (origem) {
                payload.source_number = origem;
            }

            $('#ligacao-feedback').removeClass('text-danger text-success').addClass('text-muted').text('Iniciando ligação...');
            try {
                const resp = await apiFetch(`${API_AUX}/auditoria/ligacoes/${vendaEmAuditoria.id}/iniciar/`, {
                    method: 'POST',
                    body: JSON.stringify(payload)
                });
                $('#ligacao-feedback')
                    .removeClass('text-danger text-muted')
                    .addClass('text-success')
                    .text(`Ligação iniciada. ID: ${resp.ligacao_id || '-'} | Provedor: ${resp.provider_call_id || '-'}`);
                carregarLigacoesAuditoria();
            } catch (e) {
                let msg = (e && e.message) ? e.message : 'Erro ao iniciar ligação.';
                try {
                    const parsed = JSON.parse(msg);
                    msg = parsed.detail || msg;
                } catch (_) {}
                $('#ligacao-feedback').removeClass('text-success text-muted').addClass('text-danger').text(msg);
            }
        }

        async function carregarLigacoesAuditoria() {
            if (!vendaEmAuditoria || !vendaEmAuditoria.id) return;
            const tbody = $('#tbody-ligacoes-auditoria');
            tbody.html('<tr><td colspan="7" class="text-center text-muted">Carregando...</td></tr>');
            try {
                const resp = await apiFetch(`${API_AUX}/auditoria/ligacoes/${vendaEmAuditoria.id}/`);
                const rows = Array.isArray(resp) ? resp : (resp.results || []);
                if (!rows.length) {
                    tbody.html('<tr><td colspan="7" class="text-center text-muted">Nenhuma ligação registrada para esta venda.</td></tr>');
                    return;
                }
                tbody.empty();
                rows.forEach(r => {
                    const gravacao = r.link_gravacao_onedrive || r.link_gravacao_provedor;
                    const botaoOuvir = gravacao
                        ? `<a href="${gravacao}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-primary"><i class="bi bi-play-fill"></i> Ouvir</a>`
                        : '<span class="text-muted small">Processando...</span>';
                    tbody.append(`
                        <tr>
                            <td>#${r.id || '-'}</td>
                            <td><span class="badge bg-secondary">${r.status || '-'}</span></td>
                            <td>${r.numero_origem || '-'}</td>
                            <td>${r.numero_destino || '-'}</td>
                            <td>${(r.duracao_segundos || 0)}s</td>
                            <td>${botaoOuvir}</td>
                            <td>${formatarDataHoraLigacao(r.criado_em)}</td>
                        </tr>
                    `);
                });
            } catch (e) {
                tbody.html('<tr><td colspan="7" class="text-center text-danger">Erro ao carregar ligações.</td></tr>');
            }
        }

        async function fecharScriptSemSalvar() { 
            if(confirm("Deseja sair? O que você preencheu será salvo como rascunho.")) {
                $('#loadingOverlay').show();
                const d = coletarDadosAuditoria();
                const rascunho = {
                    cliente_email: d.cliente_email || null,
                    cliente_nome_razao_social: d.cliente_nome || null,
                    cliente_cpf_cnpj: d.cliente_cpf || null,
                    observacoes: d.observacoes || null,
                    nome_mae: d.nome_mae || null,
                    data_nascimento: d.data_nascimento || null,
                    telefone1: d.telefone1 || null,
                    telefone2: d.telefone2 || null,
                    cep: d.cep || null,
                    logradouro: d.logradouro || null,
                    numero_residencia: d.numero || null,
                    complemento: d.complemento || null,
                    bairro: d.bairro || null,
                    cidade: d.cidade || null,
                    estado: d.estado || null,
                    ponto_referencia: d.referencia || null,
                    plano: d.plano || null,
                    forma_pagamento: d.forma_pagamento || null,
                    data_agendamento: d.data_agendamento || null,
                    periodo_agendamento: d.periodo_agendamento || null,
                    cpf_representante_legal: d.cpf_representante_legal || null,
                    nome_representante_legal: d.nome_representante_legal || null
                };
                Object.keys(rascunho).forEach(key => { if (rascunho[key] === "") rascunho[key] = null; });

                try {
                    await apiFetch(`${API_BASE}/${vendaEmAuditoria.id}/`, { method: 'PATCH', body: JSON.stringify(rascunho) });
                    await apiFetch(`${API_BASE}/${vendaEmAuditoria.id}/liberar-auditoria/`, { method: 'POST' });
                    modalAuditoria.hide(); 
                    carregarVendasPendentes();
                } catch (e) {
                    console.error("Erro ao salvar rascunho:", e);
                    apiFetch(`${API_BASE}/${vendaEmAuditoria.id}/liberar-auditoria/`, { method: 'POST' }).finally(() => {
                        modalAuditoria.hide(); 
                        carregarVendasPendentes();
                    });
                } finally {
                    $('#loadingOverlay').hide();
                }
            } 
        }
        
        function cancelarAgendamento() { modalAgendamento.hide(); modalAuditoria.show(); }
        
        function gerarAprovacaoMsg(d) {
            $('#loadingOverlay').hide();
            const planoTexto = $('#audit-plano option:selected').text();
            const dataAgendamento = d.data_agendamento ? d.data_agendamento.split('-').reverse().join('/') : '';
            
            let txt = `APROVADO!✅✅\n`;
            txt += `PLANO ADQUIRIDO: ${planoTexto}\n`;
            txt += `NOME DO CLIENTE: ${d.cliente_nome}\n`;
            txt += `CPF/CNPJ: ${d.cliente_cpf}\n`;
            if($('#agenda-os').val()) txt += `OS: ${$('#agenda-os').val()}\n`;
            const formaPagtoTexto = $('#audit-pagamento option:selected').text().toUpperCase();
            const isDacc = formaPagtoTexto.includes('DÉBITO') || formaPagtoTexto.includes('DEBITO') || formaPagtoTexto.includes('DACC') ? 'SIM' : 'NÃO';
            txt += `DACC: ${isDacc}\n`;
            if(dataAgendamento) {
                let turnoFmt = d.periodo_agendamento;
                if(turnoFmt === 'MANHA') turnoFmt = 'na parte da manhã';
                else if(turnoFmt === 'TARDE') turnoFmt = 'na parte da tarde';
                txt += `AGENDAMENTO: Agendamento confirmado para o dia ${dataAgendamento} ${turnoFmt}\n`;
            }
            txt += `VENDEDOR: ${$('#script-vendedor-nome').text()}\n`;
            txt += `⚠FATURA, SEGUNDA VIA OU DÚVIDAS\n`;
            txt += `https://www.niointernet.com.br/\n`;
            txt += `\nLembrete importante: Peça seu cliente para salvar o telefone 21 4040-1810 na sua agenda, isso evita pendências indevidas.\n`;
            txt += `Para que sua instalação seja concluída favor salvar esse contato, Técnico Nio 21 4040-1810, para receber informações da Visita.`;

            $('#aprovacao-mensagem').val(txt); 
            modalAprovacao.show();
            document.getElementById('modal-aprovacao').addEventListener('hidden.bs.modal', () => carregarVendasPendentes(), {once:true});
        }

        function copiarMensagem() { const t = document.getElementById("aprovacao-mensagem"); t.select(); navigator.clipboard.writeText(t.value).then(() => alert("Copiado!")); }
        function logout() { localStorage.removeItem('accessToken'); window.location.href = '/'; }
    function copiarEnderecoCompleto() {
        function toTitleCase(str) {
            return str.toLowerCase().replace(/\b\w+/g, function(txt){
                return txt.charAt(0).toUpperCase() + txt.substr(1);
            });
        }
        var cep = document.getElementById('audit-cep').value;
        var logradouro = toTitleCase(document.getElementById('audit-logradouro').value);
        var numero = document.getElementById('audit-numero').value;
        var complemento = toTitleCase(document.getElementById('audit-complemento').value);
        var bairro = toTitleCase(document.getElementById('audit-bairro').value);
        var cidade = toTitleCase(document.getElementById('audit-cidade').value);
        var uf = document.getElementById('audit-uf').value.toUpperCase();
        var ref = toTitleCase(document.getElementById('audit-ref').value);
        var enderecoCompleto = `${logradouro}, ${numero}`;
        if (complemento) enderecoCompleto += `, ${complemento}`;
        enderecoCompleto += `, ${bairro}, ${cidade} - ${uf}, ${cep}`;
        if (ref) enderecoCompleto += `, ${ref}`;
        navigator.clipboard.writeText(enderecoCompleto);
    }