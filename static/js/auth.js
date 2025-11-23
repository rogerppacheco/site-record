// static/js/auth.js - VERSÃO FINAL CORRIGIDA

// URL base da API. Uma string vazia funciona para a mesma origem.
const API_URL = '';

// --- INÍCIO DA LÓGICA DE LOGOUT POR INATIVIDADE ---

let inactivityTimer;

function logoutOnInactivity() {
    alert('Sua sessão expirou por inatividade. Por favor, faça o login novamente.');
    logout(); // Chama a função de logout global
}

function resetInactivityTimer() {
    clearTimeout(inactivityTimer);
    // Define o tempo de inatividade para 15 minutos
    inactivityTimer = setTimeout(logoutOnInactivity, 15 * 60 * 1000);
}

// Verifica se o usuário está logado para iniciar o timer
if (localStorage.getItem('accessToken')) {
    // Adiciona "escutadores" de eventos para detectar atividade do usuário
    document.addEventListener('load', resetInactivityTimer, true);
    document.addEventListener('mousemove', resetInactivityTimer, true);
    document.addEventListener('mousedown', resetInactivityTimer, true);
    document.addEventListener('keypress', resetInactivityTimer, true);
    document.addEventListener('touchmove', resetInactivityTimer, true);
    document.addEventListener('scroll', resetInactivityTimer, true);
    // Inicia o timer pela primeira vez
    resetInactivityTimer();
}

// --- FIM DA LÓGICA DE LOGOUT POR INATIVIDADE ---


// --- LÓGICA DE INTERAÇÃO COM A PÁGINA (MODAL, LOGIN, LOGOUT) ---

document.addEventListener('DOMContentLoaded', function() {
    
    // Tenta encontrar os elementos do modal na página
    const loginModal = document.getElementById('loginModalOverlay');
    const areaInternaButton = document.querySelector('a.nav-button[href="/area-interna/"]'); // Seletor específico se existir href
    const btnOpenLogin = document.getElementById('btnOpenLogin'); // Seletor pelo ID (mais seguro)
    const loginForm = document.getElementById('loginForm');
    const cancelarLogin = document.getElementById('btnCancelLogin'); // ID corrigido conforme seu HTML

    // **Esta lógica SÓ será executada se o modal de login existir na página**
    if (loginModal && loginForm) {
        
        // Função para abrir o modal
        const openModal = function(event) {
            event.preventDefault();
            const token = localStorage.getItem('accessToken');
            if (token) {
                window.location.href = '/area-interna/';
            } else {
                loginModal.style.display = 'flex'; // Usa style.display para forçar a visibilidade
                const userInput = document.getElementById('username');
                if(userInput) userInput.focus();
            }
        };

        // Adiciona evento aos botões de abrir login
        if (areaInternaButton) areaInternaButton.addEventListener('click', openModal);
        if (btnOpenLogin) btnOpenLogin.addEventListener('click', openModal);

        // Botão Cancelar
        if (cancelarLogin) {
            cancelarLogin.addEventListener('click', function() {
                loginModal.style.display = 'none';
            });
        }

        // Fechar clicando fora
        loginModal.addEventListener('click', function(e) {
            if(e.target === loginModal) loginModal.style.display = 'none';
        });

        // Submit do Formulário
        loginForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const submitBtn = loginForm.querySelector('button[type="submit"]');
            const originalText = submitBtn ? submitBtn.innerText : 'Entrar';
            
            if(submitBtn) {
                submitBtn.innerText = 'Entrando...';
                submitBtn.disabled = true;
            }

            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            await login(username, password); 
            
            if(submitBtn) {
                submitBtn.innerText = originalText;
                submitBtn.disabled = false;
            }
        });
    }

    // **Esta lógica de logout será executada em TODAS as páginas**
    const logoutButtons = document.querySelectorAll('.logout-button');
    logoutButtons.forEach(btn => {
        btn.addEventListener('click', function(event) {
            event.preventDefault();
            logout(); 
        });
    });
});


/**
 * Função para realizar o login do usuário.
 */
async function login(username, password) {
    try {
        const response = await fetch(`${API_URL}/api/auth/login/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
            credentials: 'include'
        });

        if (!response.ok) {
            const errorData = await response.json();
            const errorMsg = document.getElementById('error-message');
            if(errorMsg) {
                errorMsg.innerText = 'Falha: ' + (errorData.detail || 'Usuário ou senha incorretos');
                errorMsg.style.display = 'block';
            } else {
                alert('Falha na autenticação: ' + (errorData.detail || 'Usuário ou senha inválidos.'));
            }
            throw new Error('Falha na autenticação');
        }

        const data = await response.json();
        
        // === CORREÇÃO CRÍTICA AQUI ===
        // O Django retorna 'access', mas seu código antigo buscava 'token'
        const accessToken = data.access || data.token; 
        
        if (accessToken) {
            localStorage.setItem('accessToken', accessToken);
            if(data.refresh) localStorage.setItem('refreshToken', data.refresh);

            const decodedToken = jwt_decode(accessToken);
            if (decodedToken && decodedToken.perfil) {
                localStorage.setItem('userProfile', decodedToken.perfil);
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

/**
 * Função para fazer logout do usuário.
 */
function logout() {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken'); // Limpa o refresh token também
    localStorage.removeItem('userProfile');
    clearTimeout(inactivityTimer); 
    window.location.href = '/';
}

/**
 * Verifica se o usuário está autenticado.
 */
function verificarAutenticacao() {
    const token = localStorage.getItem('accessToken');
    if (!token) {
        // Se estiver na home, não faz nada, senão redireciona
        if (window.location.pathname !== '/') {
            alert('Você precisa estar logado para acessar esta página.');
            window.location.href = '/';
        }
    }
}

/**
 * Decodifica um token JWT.
 */
function jwt_decode(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(atob(base64).split('').map(function(c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join(''));
        return JSON.parse(jsonPayload);
    } catch (e) {
        console.error("Erro ao decodificar token:", e);
        return null;
    }
}

/**
 * Objeto para centralizar as chamadas à API.
 */
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
        const response = await fetch(`${API_URL}${url}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data),
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    },
    // ... (outros métodos mantidos iguais)
    patch: async function(url, data) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'PATCH',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data),
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    },
    delete: async function(url) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        return { data: null };
    }
};