// Em static/js/auth.js

// URL base da API. Uma string vazia funciona para a mesma origem.
const API_URL = '';

// --- INÍCIO DA LÓGICA DE LOGOUT POR INATIVIDADE ---

let inactivityTimer; // Variável para armazenar o temporizador

/**
 * Função chamada quando o tempo de inatividade expira.
 */
function logoutOnInactivity() {
    // Exibe uma mensagem amigável antes de deslogar
    alert('Sua sessão expirou por inatividade. Por favor, faça o login novamente.');
    // Chama a função de logout para limpar a sessão
    logout();
}

/**
 * Reinicia o temporizador de inatividade.
 */
function resetInactivityTimer() {
    // Limpa o temporizador anterior para evitar múltiplos timeouts
    clearTimeout(inactivityTimer);
    // Define um novo temporizador de 15 minutos (15 * 60 * 1000 milissegundos)
    inactivityTimer = setTimeout(logoutOnInactivity, 15 * 60 * 1000);
}

// Adiciona "escutadores" de eventos para detectar atividade do usuário em toda a aplicação.
document.addEventListener('load', resetInactivityTimer, true);
document.addEventListener('mousemove', resetInactivityTimer, true);
document.addEventListener('mousedown', resetInactivityTimer, true); // Captura cliques
document.addEventListener('keypress', resetInactivityTimer, true); // Captura teclas pressionadas
document.addEventListener('touchmove', resetInactivityTimer, true); // Para dispositivos móveis
document.addEventListener('scroll', resetInactivityTimer, true); // Captura o scroll

// --- FIM DA LÓGICA DE LOGOUT POR INATIVIDADE ---


// --- LÓGICA DE LOGIN E AUTENTICAÇÃO ---

document.addEventListener('DOMContentLoaded', function() {
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            await login(username, password);
        });
    }
});

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
        // Corrigido para usar o padrão SimpleJWT (access e refresh)
        if (data.access_token && data.refresh_token) {
            localStorage.setItem('accessToken', data.access_token);
            localStorage.setItem('refreshToken', data.refresh_token);
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

function logout() {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken'); // Limpa também o refresh token
    localStorage.removeItem('userProfile');
    window.location.href = '/';
}

function verificarAutenticacao() {
    const token = localStorage.getItem('accessToken');
    if (!token && window.location.pathname !== '/') {
        alert('Você precisa estar logado para acessar esta página.');
        window.location.href = '/';
    }
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
        console.error("Erro ao decodificar token:", e);
        return null;
    }
}


/**
 * Cliente de API para realizar requisições autenticadas.
 */
const apiClient = {
    _handleResponse: async function(response) {
        if (!response.ok) {
            // Tenta extrair uma mensagem de erro específica do corpo da resposta
            let errorDetail = `HTTP error! status: ${response.status}`;
            try {
                const errorData = await response.json();
                errorDetail = errorData.detail || JSON.stringify(errorData);
            } catch (e) {
                // Se o corpo não for JSON, usa o texto do status
                errorDetail = response.statusText;
            }
            // Cria um objeto de erro que pode ser capturado pelo bloco catch
            const error = new Error(errorDetail);
            error.response = response; // Anexa a resposta completa ao erro
            throw error;
        }
        // Se a resposta for 204 No Content, retorna um objeto com data nula
        if (response.status === 204) {
            return { data: null };
        }
        // Se for sucesso, retorna o JSON
        return { data: await response.json() };
    },

    get: async function(url) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'GET',
            headers: { 'Authorization': `Bearer ${token}` },
            credentials: 'include'
        });
        return this._handleResponse(response);
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
        return this._handleResponse(response);
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
        return this._handleResponse(response);
    },

    // <<< FUNÇÃO DELETE ADICIONADA AQUI >>>
    delete: async function(url) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            credentials: 'include'
        });
        return this._handleResponse(response);
    },

    postMultipart: async function(url, formData) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData,
            credentials: 'include'
        });
        return this._handleResponse(response);
    }
};