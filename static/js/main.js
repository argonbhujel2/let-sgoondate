// Floating hearts, flowers & sparkles
(function () {
    const container = document.getElementById('decorations');
    if (!container) return;

    const items = ['🌸', '💕', '✨', '🌷', '💖', '🦋', '🌺', '💗', '🌼', '⭐'];
    const count = window.innerWidth < 600 ? 12 : 20;

    for (let i = 0; i < count; i++) {
        const el = document.createElement('span');
        el.className = 'float-item';
        el.textContent = items[Math.floor(Math.random() * items.length)];
        el.style.left = Math.random() * 100 + '%';
        el.style.top = Math.random() * 100 + '%';
        el.style.animationDelay = (Math.random() * 6) + 's';
        el.style.animationDuration = (6 + Math.random() * 6) + 's';
        el.style.fontSize = (0.9 + Math.random() * 0.9) + 'rem';
        container.appendChild(el);
    }
})();
