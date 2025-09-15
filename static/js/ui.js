// ui.js - Lógica de Interação da Interface (Menu e Modais)

document.addEventListener('DOMContentLoaded', function() {
    // --- Lógica para o Menu Mobile (Refatorada) ---
    const menuToggle = document.getElementById('menu-toggle');
    const mainMenu = document.getElementById('main-menu');

    if (menuToggle && mainMenu) {
        menuToggle.addEventListener('click', function() {
            mainMenu.classList.toggle('active');
        });
    }

    // --- Lógica para o Modal de Login ---
    const areaInternaBtn = document.getElementById('areaInternaButton');
    const loginModalOverlay = document.getElementById('loginModalOverlay');
    const cancelarLoginBtn = document.getElementById('cancelarLogin');
    const loginForm = document.getElementById('loginForm');
    const errorMessageDiv = document.getElementById('error-message');

    // Função para mostrar o modal
    function showModal() {
        loginModalOverlay.style.display = 'flex'; // Torna o modal visível imediatamente
        // Adiciona a classe 'active' após um pequeno atraso para que a transição CSS ocorra
        setTimeout(() => loginModalOverlay.classList.add('active'), 10);
        errorMessageDiv.style.display = 'none'; // Esconde mensagem de erro anterior
    }

    // Função para fechar o modal
    function closeModal() {
        loginModalOverlay.classList.remove('active');
        // Esconde o modal completamente após a transição
        setTimeout(() => loginModalOverlay.style.display = 'none', 300);
    }

    // Eventos para abrir e fechar o modal
    areaInternaBtn.addEventListener('click', function(e) {
        // Verifica se já está logado, se sim, redireciona
        if (localStorage.getItem('accessToken')) {
            window.location.href = '/area-interna/';
        } else {
            // Se não estiver logado, abre o modal
            e.preventDefault();
            showModal();
        }
    });

    cancelarLoginBtn.addEventListener('click', closeModal);

    // Fecha o modal ao clicar fora dele
    loginModalOverlay.addEventListener('click', function(e) {
        if (e.target === loginModalOverlay) {
            closeModal();
        }
    });

    // Submissão do formulário de login (agora usando a função 'login' de auth.js)
    loginForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const username = document.getElementById('username').value;
        const password = document.getElementById('password').value;

        // Chama a função de login que está no auth.js
        const sucesso = await login(username, password);

        if (sucesso) {
            // A própria função login já redireciona se tiver sucesso
        } else {
            // Exibe mensagem de erro
            errorMessageDiv.textContent = 'Usuário ou senha inválidos.';
            errorMessageDiv.style.display = 'block';
        }
    });
});