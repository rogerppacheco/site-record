document.addEventListener('DOMContentLoaded', () => {
    const menuToggle = document.querySelector('.menu-toggle');
    const mainNavList = document.querySelector('.main-nav ul');

    if (menuToggle && mainNavList) {
        menuToggle.addEventListener('click', () => {
            // Adiciona/remove a classe 'active' no ícone (para o estilo 'X')
            menuToggle.classList.toggle('active'); 
            // Adiciona/remove a classe 'active' na lista de links (para exibir/esconder)
            mainNavList.classList.toggle('active');
        });
    }
});