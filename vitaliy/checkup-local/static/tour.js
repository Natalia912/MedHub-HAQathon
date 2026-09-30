// ▶ Демо, часть 2: после анкеты — программа, согласие, подготовка, куратор, утро клиники, карта, 12 пациентов.
(function () {
  const $$ = (s) => [...document.querySelectorAll(s)];
  const q = (s) => document.querySelector(s);
  const tick = (el) => { if (el && !el.checked) { TOUR.pulse(el); el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); } };
  const press = (el) => { if (el) { TOUR.pulse(el); el.click(); } };
  const N = 8;
  const st = (n, name) => `Этап ${n} из ${N} · ${name}`;

  async function play() {
    const { wait, caption, spot } = TOUR;
    for (let i = 0; i < 30 && !(window.RESULT_READY && window.RESULT_READY()); i++) await wait(150);
    const alive = () => !TOUR.stopped;

    go('program'); await wait(600);
    caption('Бесплатно по госпрограмме — по приказу ДСМ-174 (ред. № 75), с причиной и сроком', st(2, 'Программа'));
    spot(q('.h-free')?.parentElement); await wait(4500); if (!alive()) return;
    caption('Пациент выбирает: бесплатно в поликлинике до 60 дней — или в PRIME сегодня', st(2, 'Программа'));
    spot(q('.card.free .choice')); await wait(4000); if (!alive()) return;
    caption('Пакет PRIME: акценты по анамнезу, онкомаркеры — по выбору куратора', st(2, 'Программа'));
    spot(q('.card.prime')); await wait(4500); if (!alive()) return;
    if (q('.card.extra')) { caption('Сверх пакета — только по ответам анкеты, уточнит врач', st(2, 'Программа')); spot(q('.card.extra')); await wait(4000); }
    if (!alive()) return;

    caption('Информированное согласие простыми словами: что, зачем, риски, альтернатива', st(3, 'Согласие'));
    spot(q('.card.consent')); await wait(3000);
    for (let i = 0; i < 6 && alive(); i++) {
      const item = $$('.consent-item')[i]; if (!item) break;
      spot(item); await wait(1500); tick(item.querySelector('[data-consent]')); await wait(900);
    }
    if (!alive()) return;

    caption('Маршрут дня по кабинетам — к каждой процедуре «как подготовиться»', st(4, 'Маршрут'));
    spot(q('.route')); await wait(3000);
    for (const el of $$('.route li').filter((li) => li.querySelector('.prep-line b')).slice(0, 4)) {
      if (!alive()) return;
      spot(el); await wait(2600);
    }

    go('prep'); await wait(600);
    caption('Подготовка по дням: под каждым пунктом вопрос — пациент подтверждает, что понял', st(5, 'Подготовка'));
    for (let i = 0; i < 8 && alive(); i++) {
      const p = RESULT.prep[i]; if (!p) break;
      const b = q(`[data-quiz="${p.id}"][data-i="${p.correct}"]`);
      spot(b && b.closest('.card')); await wait(1600); press(b); await wait(900);
    }
    if (!alive()) return;

    go('curator'); await wait(600);
    caption('Врач-куратор видит анкету: давление на учёте, кишечник, лекарства', st(6, 'Куратор'));
    spot(q('#curator .card')); await wait(4000); if (!alive()) return;
    caption('Куратор выбирает состав: например, добавляет онкомаркер CA 19-9', st(6, 'Куратор'));
    const onc = $$('[data-toggle^="items:"]').find((x) => x.closest('tr').innerText.includes('CA 19-9'));
    if (onc) { spot(onc.closest('tr')); await wait(2200); tick(onc); await wait(1800); }
    if (!alive()) return;
    caption('Без подписанного согласия утвердить нельзя — отмечаем подпись', st(6, 'Куратор'));
    spot(q('.consent-check')); await wait(2500); tick(q('#consent-signed')); await wait(1800);
    caption('Утверждено — готов итоговый лист', st(6, 'Куратор'));
    const ap = q('#btn-approve'); spot(ap); await wait(1500); press(ap); await wait(2000);
    if (!alive()) return;

    go('morning'); await wait(1500);
    caption('Утро клиники: кабинеты медэксперта; каждому своё время прихода — ожидание падает', st(7, 'Утро клиники'));
    spot(q('.compare')); await wait(5000); if (!alive()) return;
    caption('Сколько полных чекапов клиника берёт в день — при 3 местах УЗИ', st(7, 'Утро клиники'));
    spot(q('.capacity')); await wait(4000);
    caption('Переключаем УЗИ на 2 места — скрипт пересчитывает весь день', st(7, 'Утро клиники'));
    press(q('[data-places="r103:2"]')); await wait(1500); spot(q('.capacity')); await wait(4000);
    press(q('[data-places="r103:3"]')); await wait(1500);
    caption('Табло: каждый пациент по кабинетам, узкое место видно заранее', st(7, 'Утро клиники'));
    spot(q('.gantt')); await wait(4500); if (!alive()) return;

    go('card'); await wait(800);
    caption('Карта здоровья: отмечаем пройденное, пишем результат, ставим оценку', st(8, 'Карта здоровья'));
    spot(q('#card .tbl')); await wait(1500);
    for (let i = 0; i < 4 && alive(); i++) { tick($$('[data-done]')[i]); await wait(700); }
    press(q('[data-star="5"]')); await wait(1200);
    caption('Когда повторить — напоминание в календарь', st(8, 'Карта здоровья'));
    spot(q('.next')); await wait(4500); if (!alive()) return;

    go('scenario'); await wait(1500);
    caption('И так — каждый из 12 пациентов: запись по дням, без очередей', 'Итог');
    spot(q('.kpis')); await wait(5000); spot(q('.scn-wrap')); await wait(5000);
    caption('Диагноз не ставим. Врач утверждает правила один раз — скрипт применяет их к каждому пациенту', 'Итог');
    spot(null); await wait(6000);
    TOUR.stop();
  }
  window.startTour = play;
})();
