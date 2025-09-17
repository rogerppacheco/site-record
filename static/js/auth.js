// Em static/js/auth.js

// URL base da API. Uma string vazia funciona para a mesma origem.
const API_URL = '';

// --- INÍCIO DA LÓGICA DE LOGOUT POR INATIVIDADE ---

// Variável para armazenar nosso temporizador
let inactivityTimer;

// Função que será chamada quando o tempo de inatividade expirar
function logoutOnInactivity() {
    // Exibe uma mensagem amigável antes de deslogar
    alert('Sua sessão expirou por inatividade. Por favor, faça o login novamente.');
    // Chama a sua função de logout original, que já existe neste arquivo
    logout();
}

// Função para reiniciar o temporizador de inatividade
function resetInactivityTimer() {
    // Limpa o temporizador anterior
    clearTimeout(inactivityTimer);
    // Define um novo temporizador. 15 minutos = 15 * 60 * 1000 milissegundos
    inactivityTimer = setTimeout(logoutOnInactivity, 15 * 60 * 1000);
}

// Adiciona "escutadores" de eventos para detectar atividade do usuário
document.addEventListener('load', resetInactivityTimer, true);
document.addEventListener('mousemove', resetInactivityTimer, true);
document.addEventListener('mousedown', resetInactivityTimer, true); // Captura cliques
document.addEventListener('keypress', resetInactivityTimer, true); // Captura teclas pressionadas
document.addEventListener('touchmove', resetInactivityTimer, true); // Para dispositivos móveis
document.addEventListener('scroll', resetInactivityTimer, true); // Captura o scroll

// --- FIM DA LÓGICA DE LOGOUT POR INATIVIDADE ---


// --- SEU CÓDIGO ORIGINAL INTEGRADO ABAIXO ---

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
 * Função para realizar o login do usuário. (SEU CÓDIGO ORIGINAL MANTIDO)
 */
async function login(username, password) {
    console.log("Iniciando requisição de login (MODO ORIGINAL)...");
    try {
        const response = await fetch(`${API_URL}/api/auth/login/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                username,
                password
            }),
            credentials: 'include'
        });

        if (!response.ok) {
            const errorData = await response.json();
            console.error("Detalhes do erro do servidor:", errorData);
            alert('Falha na autenticação: ' + (errorData.detail || 'Usuário ou senha inválidos.'));
            throw new Error('Falha na autenticação');
        }

        const data = await response.json();
        console.log("Dados recebidos (customizado):", data);

        if (data.token) {
            localStorage.setItem('accessToken', data.token);
            console.log("Token de acesso customizado armazenado com sucesso.");

            const decodedToken = jwt_decode(data.token);
            console.log("Token decodificado:", decodedToken);

            if (decodedToken && decodedToken.perfil) {
                localStorage.setItem('userProfile', decodedToken.perfil);
                console.log("Perfil do usuário armazenado com sucesso.");
            } else {
                console.error("Token não contém informações de perfil.");
            }

            window.location.href = '/area-interna/';
            return true;

        } else {
            console.error("Resposta de sucesso, mas sem o token customizado.");
            alert('Ocorreu um erro inesperado durante o login. Tente novamente.');
            return false;
        }

    } catch (error) {
        console.error('Erro geral durante o login:', error);
        localStorage.removeItem('accessToken');
        localStorage.removeItem('userProfile');
        return false;
    }
}

/**
 * Função para fazer logout do usuário, limpando os tokens.
 */
function logout() {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('userProfile');
    window.location.href = '/';
}

/**
 * Verifica se o usuário está autenticado. Se não, redireciona para a página de login.
 */
function verificarAutenticacao() {
    const token = localStorage.getItem('accessToken');
    if (!token) {
        alert('Você precisa estar logado para acessar esta página.');
        window.location.href = '/';
    }
}

/**
 * Decodifica um token JWT para extrair suas informações (payload).
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
    
    // --- INÍCIO DA CORREÇÃO: ADICIONANDO O MÉTODO DELETE ---
    delete: async function(url) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            credentials: 'include'
        });
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            // Lança o erro com a mensagem de "detail" vinda do backend
            throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
        }
        // DELETE bem-sucedido não retorna conteúdo.
        return { data: null }; 
    },
    // --- FIM DA CORREÇÃO ---

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