// ui.js - Lógica de Interação da Interface (Modais)

document.addEventListener('DOMContentLoaded', function() {
    // --- Lógica para o Modal de Login ---
    const areaInternaBtn = document.getElementById('areaInternaButton');
    const loginModalOverlay = document.getElementById('loginModalOverlay');
    const cancelarLoginBtn = document.getElementById('cancelarLogin');
    const errorMessageDiv = document.getElementById('error-message'); // A mensagem de erro será controlada por auth.js

    // Se os elementos essenciais do modal não estiverem na página, interrompe a execução.
    if (!areaInternaBtn || !loginModalOverlay || !cancelarLoginBtn) {
        return;
    }

    // Função para mostrar o modal
    function showModal() {
        loginModalOverlay.style.display = 'flex'; // Torna o modal visível
        // Adiciona a classe 'active' após um instante para a transição de opacidade funcionar
        setTimeout(() => {
            loginModalOverlay.classList.add('active');
        }, 10);
        // Garante que a mensagem de erro de uma tentativa anterior seja limpa ao abrir o modal
        if(errorMessageDiv) {
            errorMessageDiv.style.display = 'none';
        }
    }

    // Função para fechar o modal
    function closeModal() {
        loginModalOverlay.classList.remove('active');
        // Espera a transição de opacidade terminar (300ms) antes de esconder o modal
        setTimeout(() => {
            loginModalOverlay.style.display = 'none';
        }, 300);
    }

    // Eventos para abrir e fechar o modal
    areaInternaBtn.addEventListener('click', function(e) {
        e.preventDefault(); // Impede a navegação padrão do link '#'

        // Verifica se já está logado, se sim, redireciona
        if (localStorage.getItem('accessToken')) {
            window.location.href = '/area-interna/';
        } else {
            // Se não estiver logado, abre o modal de login
            showModal();
        }
    });

    cancelarLoginBtn.addEventListener('click', closeModal);

    // Fecha o modal ao clicar fora da área de conteúdo (no overlay)
    loginModalOverlay.addEventListener('click', function(e) {
        if (e.target === loginModalOverlay) {
            closeModal();
        }
    });

    // A lógica de submissão do formulário foi REMOVIDA daqui.
    // Ela agora é de responsabilidade exclusiva do arquivo `auth.js` para evitar conflitos.
});