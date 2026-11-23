(() => {
    const button = document.querySelector('.mobile-menu-toggle');
    const navigation = document.querySelector('.mobile-navigation');
    if (!button || !navigation) return;

    const close = () => {
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-label', 'Open navigation');
        navigation.classList.remove('is-open');
    };

    button.addEventListener('click', () => {
        const open = button.getAttribute('aria-expanded') !== 'true';
        button.setAttribute('aria-expanded', String(open));
        button.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
        navigation.classList.toggle('is-open', open);
    });
    navigation.addEventListener('click', (event) => {
        if (event.target.closest('a')) close();
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') close();
    });
})();
