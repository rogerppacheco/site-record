// static/js/auth.js - VERSÃO FINAL UNIFICADA

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
    const areaInternaButton = document.querySelector('a.nav-button[href="/area-interna/"]');
    const loginForm = document.getElementById('loginForm');
    const cancelarLogin = document.getElementById('cancelarLogin');

    // **Esta lógica SÓ será executada se o modal de login existir na página (ou seja, na index.html)**
    if (loginModal && areaInternaButton && loginForm && cancelarLogin) {
        
        // Adiciona evento ao botão "Área Interna" para abrir o modal
        areaInternaButton.addEventListener('click', function(event) {
            event.preventDefault(); // Impede a navegação direta
            const token = localStorage.getItem('accessToken');
            if (token) {
                // Se já tiver token, vai direto para a área interna
                window.location.href = '/area-interna/';
            } else {
                // Se não, abre o modal de login
                loginModal.classList.add('active');
            }
        });

        // Adiciona evento ao botão "Cancelar" para fechar o modal
        cancelarLogin.addEventListener('click', function() {
            loginModal.classList.remove('active');
        });

        // Adiciona evento de submit ao formulário de login
        loginForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            await login(username, password); // Chama a sua função de login global
        });
    }

    // **Esta lógica de logout será executada em TODAS as páginas**
    const logoutButton = document.querySelector('.logout-button');
    if (logoutButton) {
        logoutButton.addEventListener('click', function(event) {
            event.preventDefault();
            logout(); // Chama a sua função de logout global
        });
    }
});


/**
 * Função para realizar o login do usuário. (SEU CÓDIGO ORIGINAL MANTIDO)
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
            alert('Falha na autenticação: ' + (errorData.detail || 'Usuário ou senha inválidos.'));
            throw new Error('Falha na autenticação');
        }

        const data = await response.json();
        if (data.token) {
            localStorage.setItem('accessToken', data.token);
            const decodedToken = jwt_decode(data.token);
            if (decodedToken && decodedToken.perfil) {
                localStorage.setItem('userProfile', decodedToken.perfil);
            }
            window.location.href = '/area-interna/';
            return true;
        } else {
            alert('Ocorreu um erro inesperado durante o login. Tente novamente.');
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
    localStorage.removeItem('userProfile');
    clearTimeout(inactivityTimer); // Para o timer de inatividade
    window.location.href = '/';
}

/**
 * Verifica se o usuário está autenticado.
 */
function verificarAutenticacao() {
    const token = localStorage.getItem('accessToken');
    if (!token) {
        alert('Você precisa estar logado para acessar esta página.');
        window.location.href = '/';
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
    },
    postMultipart: async function(url, formData) {
        const token = localStorage.getItem('accessToken');
        const headers = { 'Authorization': `Bearer ${token}` };
        const response = await fetch(`${API_URL}${url}`, {
            method: 'POST',
            headers: headers,
            body: formData,
            credentials: 'include'
        });
        if (!response.ok) {
            let errorDetails = response.statusText;
            try {
                const errorData = await response.json();
                errorDetails = errorData.error || JSON.stringify(errorData);
            } catch (e) {}
            throw new Error(`HTTP error! status: ${response.status} - ${errorDetails}`);
        }
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    }
};