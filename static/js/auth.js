// Em static/js/auth.js

const API_URL = '';

// --- LÓGICA DE LOGOUT POR INATIVIDADE ---
let inactivityTimer;

function logoutOnInactivity() {
    alert('Sua sessão expirou por inatividade. Por favor, faça o login novamente.');
    logout();
}

function resetInactivityTimer() {
    clearTimeout(inactivityTimer);
    inactivityTimer = setTimeout(logoutOnInactivity, 15 * 60 * 1000);
}

document.addEventListener('load', resetInactivityTimer, true);
document.addEventListener('mousemove', resetInactivityTimer, true);
document.addEventListener('mousedown', resetInactivityTimer, true);
document.addEventListener('keypress', resetInactivityTimer, true);
document.addEventListener('touchmove', resetInactivityTimer, true);
document.addEventListener('scroll', resetInactivityTimer, true);

// --- LÓGICA DE LOGIN E AUTENTICAÇÃO (CORRIGIDA) ---

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

/**
 * Função para realizar o login do usuário. (CORRIGIDA)
 */
async function login(username, password) {
    console.log("Iniciando requisição de login...");
    try {
        const response = await fetch(`${API_URL}/api/auth/login/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken') // Boa prática adicionar CSRF
            },
            body: JSON.stringify({ username, password })
        });

        if (!response.ok) {
            const errorData = await response.json();
            alert('Falha na autenticação: ' + (errorData.detail || 'Usuário ou senha inválidos.'));
            throw new Error('Falha na autenticação');
        }

        const data = await response.json();
        console.log("Dados recebidos do login:", data);

        // <<< CORREÇÃO PRINCIPAL APLICADA AQUI >>>
        // A API retorna 'access_token', não 'token'.
        if (data.access_token && data.refresh_token) {
            localStorage.setItem('accessToken', data.access_token);
            localStorage.setItem('refreshToken', data.refresh_token);
            console.log("Tokens armazenados com sucesso.");

            const decodedToken = jwt_decode(data.access_token);
            if (decodedToken && decodedToken.perfil) {
                localStorage.setItem('userProfile', decodedToken.perfil);
            }

            window.location.href = '/area-interna/';
            return true;
        } else {
            console.error("Resposta de sucesso, mas os tokens esperados ('access_token', 'refresh_token') não foram encontrados.");
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
    localStorage.removeItem('refreshToken');
    localStorage.removeItem('userProfile');
    window.location.href = '/';
}

function verificarAutenticacao() {
    const token = localStorage.getItem('accessToken');
    // Não redireciona se já estiver na página de login
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

/**
 * Cliente de API para realizar requisições autenticadas.
 */
const apiClient = {
    _handleResponse: async function(response) {
        if (!response.ok) {
            let errorDetail = `HTTP error! status: ${response.status}`;
            try {
                const errorData = await response.json();
                errorDetail = errorData.detail || JSON.stringify(errorData);
            } catch (e) {
                errorDetail = response.statusText;
            }
            const error = new Error(errorDetail);
            error.response = response;
            throw error;
        }
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    },

    get: async function(url) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'GET',
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return this._handleResponse(response);
    },

    post: async function(url, data) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify(data)
        });
        return this._handleResponse(response);
    },

    patch: async function(url, data) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'PATCH',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify(data)
        });
        return this._handleResponse(response);
    },

    delete: async function(url) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${token}`,
                'X-CSRFToken': getCookie('csrftoken')
            }
        });
        return this._handleResponse(response);
    },

    postMultipart: async function(url, formData) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: formData
        });
        return this._handleResponse(response);
    }
};