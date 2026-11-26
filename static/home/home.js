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

(() => {
    const carousel = document.querySelector('#inspiration');
    if (!carousel) return;
    const track = carousel.querySelector('.inspiration-track');
    const slides = Array.from(track.children);
    if (slides.length < 2) return;
    const controls = carousel.querySelector('.inspiration-controls');
    const [previous, next] = controls.querySelectorAll(':scope > button');
    const pages = Array.from(controls.querySelectorAll('.inspiration-pages button[aria-controls]'));
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let timer;
    function preview(slide) {
        const copy = slide.cloneNode(true);
        copy.inert = true;
        copy.setAttribute('aria-hidden', 'true');
        return copy;
    }
    track.prepend(...slides.slice(-2).map(preview));
    track.append(...slides.slice(0, 2).map(preview));
    const wrap = (index) => ((index % slides.length) + slides.length) % slides.length;
    const centerOffset = (slide) => slide.offsetLeft - (track.clientWidth - slide.offsetWidth) / 2;
    const position = () => Math.round((track.scrollLeft - centerOffset(slides[0])) /
        (slides[1].offsetLeft - slides[0].offsetLeft));
    const current = () => wrap(position());

    function schedule() {
        clearTimeout(timer);
        if (!motion.matches && !document.hidden && !track.contains(document.activeElement)) {
            timer = setTimeout(() => show(current() + 1), 5000);
        }
    }

    function update() {
        pages.forEach((page, index) => page.setAttribute('aria-current', String(index === current())));
        schedule();
    }

    function show(index) {
        const target = wrap(index);
        track.scrollLeft = centerOffset(slides[target]);
        if (track.contains(document.activeElement)) {
            slides[target].querySelector('a').focus({ preventScroll: true });
        }
        update();
    }

    previous.addEventListener('click', () => show(current() - 1));
    next.addEventListener('click', () => show(current() + 1));
    pages.forEach((page, index) => page.addEventListener('click', () => show(index)));
    motion.addEventListener('change', schedule);
    carousel.addEventListener('keydown', (event) => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        show(current() + (event.key === 'ArrowLeft' ? -1 : 1));
    });
    track.addEventListener('focusin', schedule);
    track.addEventListener('focusout', () => queueMicrotask(schedule));
    track.addEventListener('scroll', update, { passive: true });
    track.addEventListener('scrollend', () => {
        if (position() !== current()) show(current());
    });
    document.addEventListener('visibilitychange', schedule);
    window.addEventListener('resize', update);
    controls.hidden = false;
    show(0);
})();

// Installable app: register the service worker and show the install button when the browser offers it.
(function () {
    if (!('serviceWorker' in navigator)) return;
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function () {});
    var deferred = null;
    var buttons = document.querySelectorAll('[data-install-app]');
    window.addEventListener('beforeinstallprompt', function (event) {
        event.preventDefault();
        deferred = event;
        buttons.forEach(function (b) { b.hidden = false; });
    });
    buttons.forEach(function (b) {
        b.addEventListener('click', function () {
            if (!deferred) return;
            deferred.prompt();
            deferred.userChoice.finally(function () { deferred = null; buttons.forEach(function (x) { x.hidden = true; }); });
        });
    });
})();
