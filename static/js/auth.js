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
// Qualquer um desses eventos reiniciará o temporizador.
document.addEventListener('load', resetInactivityTimer, true);
document.addEventListener('mousemove', resetInactivityTimer, true);
document.addEventListener('mousedown', resetInactivityTimer, true); // Captura cliques
document.addEventListener('keypress', resetInactivityTimer, true); // Captura teclas pressionadas
document.addEventListener('touchmove', resetInactivityTimer, true); // Para dispositivos móveis
document.addEventListener('scroll', resetInactivityTimer, true); // Captura o scroll

// --- FIM DA LÓGICA DE LOGOUT POR INATIVIDADE ---


// --- LÓGICA DE LOGIN E AUTENTICAÇÃO ---

// Adiciona o listener que espera a página carregar completamente.
document.addEventListener('DOMContentLoaded', function() {
    // Anexa o evento de submit apenas se o formulário de login existir na página.
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            // Chama a função de login
            await login(username, password);
        });
    }
});


/**
 * Função para realizar o login do usuário.
 * @param {string} username - O nome de usuário.
 * @param {string} password - A senha.
 * @returns {Promise<boolean>} - Retorna true em caso de sucesso, false em caso de falha.
 */
async function login(username, password) {
    console.log("Iniciando requisição de login...");
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
        console.log("Dados recebidos:", data);

        if (data.token) {
            localStorage.setItem('accessToken', data.token);
            console.log("Token de acesso armazenado com sucesso.");

            const decodedToken = jwt_decode(data.token);
            console.log("Token decodificado:", decodedToken);

            if (decodedToken && decodedToken.perfil) {
                localStorage.setItem('userProfile', decodedToken.perfil);
                console.log("Perfil do usuário armazenado com sucesso.");
            } else {
                console.error("Token não contém informações de perfil.");
            }

            // Redireciona para a área interna após o login
            window.location.href = '/area-interna/';
            return true;

        } else {
            console.error("Resposta de sucesso, mas sem token.");
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
 * Função para fazer logout do usuário, limpando os dados de sessão.
 */
function logout() {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('userProfile');
    // Redireciona para a página inicial
    window.location.href = '/';
}

/**
 * Verifica se o usuário está autenticado em páginas protegidas.
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
 * @param {string} token - O token JWT.
 * @returns {object|null} - O payload do token ou null em caso de erro.
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
 * Cliente de API para realizar requisições autenticadas.
 */
const apiClient = {
    get: async function(url) {
        const token = localStorage.getItem('accessToken');
        const response = await fetch(`${API_URL}${url}`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            credentials: 'include'
        });
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
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
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
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
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        if (response.status === 204) return { data: null };
        return { data: await response.json() };
    },
    // Método para upload de arquivos (multipart/form-data)
    postMultipart: async function(url, formData) {
        const token = localStorage.getItem('accessToken');
        const headers = {
            'Authorization': `Bearer ${token}`
        };

        const response = await fetch(`${API_URL}${url}`, {
            method: 'POST',
            headers: headers,
            body: formData, // O corpo é o objeto FormData
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