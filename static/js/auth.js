// static/js/auth.js - VERSÃO BLINDADA (CORREÇÃO DO REFRESH)

const API_URL = '';

// --- HELPER CSRF ---
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// --- LOGOUT POR INATIVIDADE ---
let inactivityTimer;

function logoutOnInactivity() {
    // Só faz logout se não estiver no meio da troca de senha
    if(localStorage.getItem('trocaPendente') !== 'true') {
        alert('Sua sessão expirou por inatividade.');
        logout(); 
    }
}

function resetInactivityTimer() {
    clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(logoutOnInactivity, 15 * 60 * 1000);
}

if (localStorage.getItem('accessToken')) {
    const events = ['load', 'mousemove', 'mousedown', 'keypress', 'touchmove', 'scroll'];
    events.forEach(event => document.addEventListener(event, resetInactivityTimer, true));
    resetInactivityTimer();
}

// --- CLIENTE API ---
const apiClient = {
    get: async function(url) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'GET',
            headers: { 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    },
    post: async function(url, data) {
        const token = localStorage.getItem('accessToken');
        const csrftoken = getCookie('csrftoken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            mode: 'same-origin',
            body: JSON.stringify(data),
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    }
};

// --- FUNÇÃO PARA FORÇAR O MODAL DE TROCA ---
function forcarModalTrocaSenha() {
    const modal = document.getElementById('modalTrocaSenha');
    const loginOverlay = document.getElementById('loginModalOverlay');
    
    if(loginOverlay) loginOverlay.style.display = 'none'; // Garante que o login fecha
    
    if (modal) {
        modal.style.display = 'flex';
        // Limpa campos para evitar cache visual
        const s1 = document.getElementById('novaSenhaInput');
        const s2 = document.getElementById('confirmaSenhaInput');
        if(s1) s1.value = '';
        if(s2) s2.value = '';
    } else {
        console.error("Modal de troca não encontrado. Bloqueando acesso.");
        alert("Troca de senha obrigatória. Contate o suporte se a janela não abrir.");
    }
}

document.addEventListener('DOMContentLoaded', function() {
    
    // --- VERIFICAÇÃO DE SEGURANÇA AO CARREGAR A PÁGINA ---
    // Se o usuário deu F5 mas tem a trava 'trocaPendente', abrimos o modal na cara dele.
    if (localStorage.getItem('accessToken') && localStorage.getItem('trocaPendente') === 'true') {
        forcarModalTrocaSenha();
    }

    // --- ELEMENTOS DO DOM ---
    const loginModal = document.getElementById('loginModalOverlay');
    const areaInternaButton = document.querySelector('a.nav-button[href="/area-interna/"]');
    const btnOpenLogin = document.getElementById('btnOpenLogin');
    const loginForm = document.getElementById('loginForm');
    const cancelarLogin = document.getElementById('btnCancelLogin');

    // --- 1. CONFIGURAÇÃO MODAL ESQUECI A SENHA ---
    const linkEsqueci = document.getElementById('linkEsqueciSenha');
    if(linkEsqueci) {
        linkEsqueci.addEventListener('click', function(e) {
            e.preventDefault();
            if(loginModal) loginModal.style.display = 'none';
            const modalEsqueci = document.getElementById('modalEsqueciSenha');
            if(modalEsqueci) modalEsqueci.style.display = 'flex';
        });
    }

    const formEsqueci = document.getElementById('formEsqueciSenha');
    if(formEsqueci) {
        formEsqueci.addEventListener('submit', async function(e) {
            e.preventDefault();
            const btn = formEsqueci.querySelector('button[type="submit"]');
            const originalText = btn.innerText;
            btn.innerText = 'Enviando...'; btn.disabled = true;

            const cpf = document.getElementById('esqueciCpf').value;
            const zap = document.getElementById('esqueciZap').value;
            const csrftoken = getCookie('csrftoken');

            try {
                const resp = await fetch(`${API_URL}/api/usuarios/esqueci-senha/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
                    mode: 'same-origin',
                    body: JSON.stringify({ cpf: cpf, whatsapp: zap })
                });
                
                const data = await resp.json();
                if(resp.ok) {
                    alert('Sucesso! ' + data.detail);
                    document.getElementById('modalEsqueciSenha').style.display = 'none';
                    if(loginModal) loginModal.style.display = 'flex';
                } else {
                    alert('Erro: ' + (data.detail || 'Falha ao recuperar senha.'));
                }
            } catch (err) {
                alert('Erro de conexão ou servidor.');
            } finally {
                btn.innerText = originalText; btn.disabled = false;
            }
        });
    }

    // --- 2. CONFIGURAÇÃO MODAL TROCA DE SENHA ---
    const formTroca = document.getElementById('formTrocaSenha');
    if(formTroca) {
        formTroca.addEventListener('submit', async function(e) {
            e.preventDefault();
            const nova = document.getElementById('novaSenhaInput').value;
            const conf = document.getElementById('confirmaSenhaInput').value;

            if(nova !== conf) {
                alert('As senhas não conferem!'); return;
            }

            try {
                await apiClient.post('/api/usuarios/definir-senha/', {
                    nova_senha: nova,
                    confirmacao_senha: conf
                });
                
                // SUCESSO! Remove a trava de segurança
                localStorage.removeItem('trocaPendente'); 
                
                alert('Senha alterada com sucesso!');
                document.getElementById('modalTrocaSenha').style.display = 'none';
                window.location.href = '/area-interna/';
            } catch (err) {
                alert('Erro ao salvar senha: ' + err.message);
            }
        });
    }

    // --- 3. LÓGICA DO LOGIN E BOTÕES ---
    if (loginModal && loginForm) {
        
        const openModal = function(event) {
            event.preventDefault();
            
            // SEGURANÇA: Verifica se tem troca pendente ANTES de deixar entrar
            if (localStorage.getItem('accessToken')) {
                if (localStorage.getItem('trocaPendente') === 'true') {
                    forcarModalTrocaSenha();
                    return; // PARA TUDO AQUI
                }
                window.location.href = '/area-interna/';
            } else {
                loginModal.style.display = 'flex';
                const userInput = document.getElementById('username');
                if(userInput) userInput.focus();
            }
        };

        if (areaInternaButton) areaInternaButton.addEventListener('click', openModal);
        if (btnOpenLogin) btnOpenLogin.addEventListener('click', openModal);

        if (cancelarLogin) {
            cancelarLogin.addEventListener('click', function() {
                loginModal.style.display = 'none';
            });
        }

        loginModal.addEventListener('click', function(e) {
            if(e.target === loginModal) loginModal.style.display = 'none';
        });

        loginForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const submitBtn = loginForm.querySelector('button[type="submit"]');
            const originalText = submitBtn ? submitBtn.innerText : 'Entrar';
            
            if(submitBtn) { submitBtn.innerText = 'Entrando...'; submitBtn.disabled = true; }

            const u = document.getElementById('username').value;
            const p = document.getElementById('password').value;
            
            await login(u, p); 
            
            if(submitBtn) { submitBtn.innerText = originalText; submitBtn.disabled = false; }
        });
    }

    const logoutButtons = document.querySelectorAll('.logout-button');
    logoutButtons.forEach(btn => {
        btn.addEventListener('click', function(event) {
            event.preventDefault();
            logout(); 
        });
    });
});

async function login(username, password) {
    const csrftoken = getCookie('csrftoken'); 
    try {
        const response = await fetch(`${API_URL}/api/auth/login/`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken 
            },
            mode: 'same-origin',
            body: JSON.stringify({ username, password }),
            credentials: 'include'
        });

        if (!response.ok) {
            const errorData = await response.json();
            alert('Falha na autenticação: ' + (errorData.detail || 'Usuário ou senha inválidos.'));
            throw new Error('Falha na autenticação');
        }

        const data = await response.json();
        const accessToken = data.access || data.token; 
        
        if (accessToken) {
            localStorage.setItem('accessToken', accessToken);
            if(data.refresh) localStorage.setItem('refreshToken', data.refresh);

            const decodedToken = jwt_decode(accessToken);
            if (decodedToken && decodedToken.perfil) {
                localStorage.setItem('userProfile', decodedToken.perfil);
            }
            
            // --- TRAVA DE SEGURANÇA AQUI ---
            if (data.obriga_troca_senha === true) {
                // 1. Ativa a trava no navegador
                localStorage.setItem('trocaPendente', 'true');
                
                // 2. Fecha login, abre troca
                const loginM = document.getElementById('loginModalOverlay');
                if(loginM) loginM.style.display = 'none';
                
                forcarModalTrocaSenha();
                
                return false; // IMPEDE REDIRECIONAMENTO
            } else {
                // Se não precisa trocar, garante que a trava não existe (caso tenha sobrado lixo)
                localStorage.removeItem('trocaPendente');
            }

            window.location.href = '/area-interna/';
            return true;
        } else {
            alert('Erro: O servidor não retornou um token válido.');
            return false;
        }
    } catch (error) {
        console.error('Erro geral durante o login:', error);
        return false;
    }
}

function logout() {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('userProfile');
    localStorage.removeItem('trocaPendente'); // Limpa a trava ao sair
    clearTimeout(inactivityTimer); 
    window.location.href = '/';
}

function jwt_decode(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(atob(base64).split('').map(function(c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join(''));
        return JSON.parse(jsonPayload);
    } catch (e) {
        return null;
    }
}