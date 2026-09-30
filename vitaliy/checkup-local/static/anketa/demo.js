// ▶ Демо: анкета заполняется сама по шагам (с подсветкой поля), затем /app продолжает показ.
(function () {
  const PATIENT = {  // Ж 42, на учёте по давлению, запоры, рак кишечника у отца, выделения — синтетика
    consent_data: 'yes', for_child: 'false', sex: 'F', birth_date: '1984-05-12', urgent: 'none',
    pregnant: 'no', pregnancies: '2', births: '2', contraception: 'iud', discharge: 'yes',
    conditions: ['pressure', 'bowel'], registered_on: ['pressure'], smoke_status: 'never',
    hazardous_work_10y: 'no', attached_to: 'green_clinic', family_history: ['colorectal_cancer'],
    anesthesia_reaction: 'no', blood_thinners: 'no', allergy: 'no', companion: 'yes',
    medications: 'эналаприл 10 мг утром',
  };
  const CAPTIONS = [
    'Согласие на обработку ответов, пол, дата рождения — без имени и ИИН',
    'Беспокоит прямо сейчас? — «Нет». Иначе анкета останавливается: к врачу, 103',
    'Женское здоровье: роды, контрацепция, выделения',
    'История здоровья простыми словами: давление (на учёте), кишечник',
    'Болезни в семье: рак кишечника у отца',
    'Для процедур: лекарства, наркоз, сопровождающий',
  ];
  async function fill(name, value) {
    const els = [...document.querySelectorAll(`[name="${name}"]`)];
    if (!els.length) return;
    const { wait, spot, pulse } = TOUR;
    spot(els[0].closest('.field') || els[0]);
    await wait(700);
    const el = els[0];
    if (el.type === 'radio') {
      const opt = els.find((e) => e.value === String(value));
      if (opt && !opt.checked) { pulse(opt); opt.click(); }
    } else if (el.type === 'checkbox') {
      for (const v of value) { const opt = els.find((e) => e.value === v); if (opt && !opt.checked) { pulse(opt); opt.click(); await wait(500); } }
    } else {
      el.focus(); el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); el.blur();
    }
    await wait(600);
  }
  async function play() {
    const { wait, caption, spot } = TOUR;
    sessionStorage.setItem('checkup_play', '1');
    for (let guard = 0; guard < 12 && !TOUR.stopped; guard++) {
      const n = parseInt(((document.getElementById('step-counter').textContent || '').match(/(\d+)\s*\//) || [])[1] || '0', 10);
      if (!n) break;  // дошли до проверки ответов
      caption(CAPTIONS[n - 1] || 'Анкета', `Этап 1 из 8 · Анкета — шаг ${n} из 6`);
      for (const [name, value] of Object.entries(PATIENT)) { if (TOUR.stopped) return; await fill(name, value); }
      const next = document.getElementById('next');
      spot(next); await wait(900);
      if (next.hidden || next.disabled) break;
      TOUR.pulse(next); next.click();
      await wait(900);
    }
    if (TOUR.stopped) { sessionStorage.removeItem('checkup_play'); return; }
    caption('Проверка ответов — и «Показать программу»', 'Этап 1 из 8 · Анкета');
    spot(document.getElementById('review')); await wait(2500);
    const show = document.getElementById('show-result');
    spot(show); await wait(1200);
    if (show) show.click();
  }
  function button() {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = '▶ Демо';
    b.title = 'Автопоказ: один пациент проходит все этапы';
    b.style.cssText = 'position:fixed;right:24px;bottom:24px;z-index:98;background:#ffca79;color:#184d3b;border:0;border-radius:999px;' +
      'font:600 20px Geologica,system-ui,sans-serif;padding:14px 26px;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.25)';
    b.addEventListener('click', () => { b.remove(); play(); });
    document.body.appendChild(b);
  }
  window.addEventListener('load', () => {
    button();
    if (new URLSearchParams(location.search).get('play') === '1') setTimeout(() => document.querySelector('button[title^="Автопоказ"]')?.click(), 1200);
  });
})();
