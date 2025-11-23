document.addEventListener('DOMContentLoaded', () => {
    const menuToggle = document.getElementById('menu-toggle');
    const mainNav = document.querySelector('.main-nav');
    const userDisplay = document.getElementById('welcome-user');

    // Lógica do Botão Hambúrguer
    if (menuToggle && mainNav) {
        menuToggle.addEventListener('click', () => {
            mainNav.classList.toggle('active');
            
            // Animação simples do ícone X
            const bars = menuToggle.querySelectorAll('.bar');
            if (mainNav.classList.contains('active')) {
                // Transforma em X (opcional, visual)
                // Você pode adicionar classes CSS para girar as barras aqui se quiser
            }
        });
    }

    // Lógica para Submenus no Mobile (Toque)
    const submenus = document.querySelectorAll('.has-submenu > a');
    submenus.forEach(link => {
        link.addEventListener('click', (e) => {
            // Se for mobile (largura < 992px), previne o link e abre o menu
            if (window.innerWidth <= 992) {
                e.preventDefault();
                const parent = link.parentElement;
                const submenu = parent.querySelector('.submenu');
                if (submenu) {
                    const isVisible = submenu.style.display === 'block';
                    submenu.style.display = isVisible ? 'none' : 'block';
                }
            }
        });
    });

    // Carregar nome do usuário (se existir token)
    const token = localStorage.getItem('accessToken');
    if (token && userDisplay) {
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            userDisplay.textContent = `Olá, ${payload.username || 'Usuário'}`;
        } catch (e) {
            console.error('Erro ao ler token', e);
        }
    }
});

function logout() {
    localStorage.removeItem('accessToken');
    localStorage.removeItem('refreshToken');
    window.location.href = '/';
}