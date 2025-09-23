document.addEventListener('DOMContentLoaded', () => {
    const menuToggle = document.querySelector('.menu-toggle');
    const mainNavList = document.querySelector('.main-nav ul');

    if (menuToggle && mainNavList) {
        menuToggle.addEventListener('click', () => {
            mainNavList.classList.toggle('active');
        });
    }
});