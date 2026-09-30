// Общие для автопоказа: темп, подсветка элемента, крупная подпись с номером этапа, остановка по клику на подписи.
window.TOUR = (function () {
  const SPEED = 1.7;  // во сколько раз медленнее базовых пауз
  const wait = (ms) => new Promise((r) => setTimeout(r, ms * SPEED));
  let bar, lit, stopped = false;
  const style = document.createElement('style');
  style.textContent = `
    .tour-lit { position:relative; z-index:60; outline:4px solid #ffca79 !important; outline-offset:6px; border-radius:12px;
      box-shadow:0 0 0 9999px rgba(15,40,30,.42) !important; transition:box-shadow .3s, outline-color .3s; }
    .tour-click { animation: tourPulse .9s ease-out 1; }
    @keyframes tourPulse { 0% { box-shadow:0 0 0 0 rgba(255,202,121,.95); } 100% { box-shadow:0 0 0 22px rgba(255,202,121,0); } }
    .tour-caption { position:fixed; left:50%; bottom:28px; transform:translateX(-50%); z-index:99; background:#184d3b; color:#fff;
      font:500 24px/1.35 Geologica,system-ui,sans-serif; padding:18px 30px; border-radius:16px; max-width:min(92vw,1100px);
      text-align:center; box-shadow:0 12px 36px rgba(0,0,0,.35); border:3px solid #ffca79; cursor:pointer; }
    .tour-caption small { display:block; font-size:15px; color:#ffca79; letter-spacing:.06em; margin-bottom:4px; }
    @media (max-width:700px) { .tour-caption { font-size:17px; padding:12px 16px; bottom:12px; } }`;
  document.head.appendChild(style);

  function caption(text, stage) {
    if (!bar) {
      bar = document.createElement('div');
      bar.className = 'tour-caption';
      bar.title = 'Нажмите, чтобы остановить показ';
      bar.addEventListener('click', stop);
      document.body.appendChild(bar);
    }
    bar.innerHTML = (stage ? `<small>${stage}</small>` : '') + text;
  }
  function spot(el) {
    if (lit) lit.classList.remove('tour-lit');
    lit = el || null;
    if (!el) return;
    el.classList.add('tour-lit');
    const top = (document.querySelector('.topbar')?.offsetHeight || 0) + 28;  // выше подписи, под шапкой
    window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - top), behavior: 'smooth' });
  }
  function pulse(el) {
    if (!el) return;
    const t = el.closest('label, button, .chip, .choice') || el;
    t.classList.remove('tour-click'); void t.offsetWidth; t.classList.add('tour-click');
  }
  function stop() {
    stopped = true;
    spot(null);
    if (bar) { bar.remove(); bar = null; }
  }
  return { wait, caption, spot, pulse, stop, get stopped() { return stopped; }, SPEED };
})();
