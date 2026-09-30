// Check-up Intelligence — экран. Вся логика подбора — на сервере (engine.py, правила в spec/rules.json).
const $ = (s, el = document) => el.querySelector(s);
const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const PAY = { free_gobmp: 'Бесплатно (ГОБМП)', free_osms: 'Бесплатно (ОСМС)', paid_prime: 'Пакет PRIME', paid_extra: 'Сверх пакета' };

// ---------- Анкета (правки медэксперта 30.09: без жалоб, простые слова, семья, лекарства) ----------
const CONDITIONS = [
  ['pressure', 'Повышенное давление', 'hypertension'], ['heart', 'Боли в сердце, инфаркт', 'ihd'],
  ['diabetes', 'Сахарный диабет', 'diabetes'], ['glaucoma', 'Глаукома', 'glaucoma'],
  ['head_vessels', 'Инсульт, сосуды головы, частые головные боли', 'cerebrovascular'],
  ['legs', 'Боли в ногах при ходьбе', null], ['breast', 'Уплотнения в молочной железе', 'breast_cancer'],
  ['hpv', 'Носительство ВПЧ', null], ['bowel', 'Запоры, полипы, проблемы с кишечником', 'colorectal'],
  ['lungs', 'Проблемы с лёгкими', 'lung_cancer'], ['tb', 'Туберкулёз', null],
  ['hepatitis', 'Хронический гепатит B или C', 'chronic_hepatitis'], ['urine', 'Проблемы с мочеиспусканием', null],
  ['bleeding', 'Кровотечения, синяки без причины', null],
];
const FAMILY = [['colorectal_cancer', 'Рак кишечника'], ['breast_cancer', 'Рак молочной железы или яичников'],
  ['other_cancer', 'Другой рак'], ['early_cvd', 'Инфаркт или инсульт до 60 лет'], ['hypertension', 'Повышенное давление'],
  ['diabetes', 'Сахарный диабет'], ['tb', 'Туберкулёз']];

const Q = [
  { block: 'О вас', items: [
    { id: 'for_child', label: 'Для кого подбираем?', type: 'radio', opts: [['false', 'Для себя'], ['true', 'Для ребёнка']], def: 'false' },
    { id: 'sex', label: 'Пол', type: 'radio', opts: [['F', 'Женский'], ['M', 'Мужской']], req: true },
    { id: 'birth_date', label: 'Дата рождения', type: 'date', req: true },
  ] },
  { block: 'Самочувствие сейчас', items: [
    { id: 'urgent', label: 'Что-то беспокоит прямо сейчас?', type: 'radio', req: true, def: 'none', opts: [
      ['none', 'Нет, чувствую себя как обычно'], ['chest_pain', 'Боль или давление в груди'], ['dyspnea', 'Сильная одышка'],
      ['stroke_signs', 'Внезапная слабость в руке или ноге, нарушение речи'], ['other_now', 'Другое беспокоит сейчас']] },
    { id: 'pregnant', label: 'Вы беременны или можете быть беременны?', type: 'radio', opts: [['no', 'Нет'], ['yes', 'Да'], ['unsure', 'Не уверена']], def: 'no', show: (a) => a.sex === 'F' && a.for_child !== 'true' },
  ] },
  { block: 'История здоровья', hint: 'Отметьте, что есть или было. Если наблюдаетесь у врача — поставьте «на учёте».', items: [
    { id: 'conditions', type: 'conditions' },
    { id: 'medications', label: 'Какие лекарства принимаете сейчас?', type: 'text', ph: 'например: эналаприл 10 мг утром' },
  ] },
  { block: 'Семья', items: [
    { id: 'family_history', label: 'Было ли у родителей, братьев или сестёр?', type: 'checks', opts: FAMILY },
  ] },
  { block: 'Образ жизни', show: (a) => a.for_child !== 'true', items: [
    { id: 'smoke_status', label: 'Курение', type: 'radio', opts: [['never', 'Не курю и не курил(а)'], ['now', 'Курю'], ['quit', 'Бросил(а)']], def: 'never' },
    { id: 'cigs', label: 'Сигарет в день', type: 'number', show: (a) => a.smoke_status && a.smoke_status !== 'never' },
    { id: 'smoke_years', label: 'Сколько лет курите (курили)', type: 'number', show: (a) => a.smoke_status && a.smoke_status !== 'never' },
    { id: 'quit_years_ago', label: 'Сколько лет назад бросили', type: 'number', show: (a) => a.smoke_status === 'quit' },
    { id: 'hazardous_work_10y', label: 'Последние 10 лет работали на вредном производстве?', type: 'radio', opts: [['false', 'Нет'], ['true', 'Да']], def: 'false' },
  ] },
  { block: 'Женское здоровье', show: (a) => a.sex === 'F' && a.for_child !== 'true', items: [
    { id: 'last_period', label: 'Первый день последних месячных', type: 'date' },
    { id: 'pregnancies', label: 'Беременностей', type: 'number' }, { id: 'births', label: 'Из них родов', type: 'number' },
    { id: 'contraception', label: 'Метод контрацепции', type: 'radio', opts: [['none', 'Нет'], ['condom', 'Презерватив'], ['pills', 'Таблетки'], ['iud', 'Спираль'], ['other', 'Другое'], ['not_needed', 'Не нужно']] },
    { id: 'discharge', label: 'Есть выделения из половых путей, неприятный запах?', type: 'radio', opts: [['no', 'Нет'], ['yes', 'Да']], def: 'no' },
    { id: 'ls_pap', label: 'Год последнего анализа на онкоцитологию или ВПЧ', type: 'number', ph: 'если помните' },
    { id: 'ls_mammo', label: 'Год последней маммографии', type: 'number', ph: 'если помните' },
  ] },
  { block: 'Мужское здоровье', show: (a) => a.sex === 'M' && a.for_child !== 'true', items: [
    { id: 'dysuria', label: 'Есть боль, жжение при мочеиспускании, выделения?', type: 'radio', opts: [['no', 'Нет'], ['yes', 'Да']], def: 'no' },
  ] },
  { block: 'Для процедур в день чекапа', items: [
    { id: 'anesthesia_reaction', label: 'Были плохие реакции на наркоз?', type: 'radio', opts: [['no', 'Нет'], ['yes', 'Да'], ['never', 'Наркоза не было']], def: 'no' },
    { id: 'blood_thinners', label: 'Принимаете препараты, разжижающие кровь?', type: 'radio', opts: [['no', 'Нет'], ['yes', 'Да'], ['unsure', 'Не знаю']], def: 'no' },
    { id: 'allergy', label: 'Есть аллергия на лекарства?', type: 'radio', opts: [['no', 'Нет'], ['yes', 'Да']], def: 'no' },
    { id: 'companion', label: 'Будет сопровождающий? (после наркоза нельзя за руль)', type: 'radio', opts: [['yes', 'Да'], ['no', 'Нет']], def: 'yes' },
    { id: 'attached_to', label: 'К какой поликлинике вы прикреплены?', type: 'radio', opts: [['green_clinic', 'Green Clinic'], ['other', 'Другая'], ['unknown', 'Не знаю']], def: 'green_clinic' },
  ] },
];

let A = {};           // ответы
let RESULT = null;    // ответ движка
window.RESULT_READY = () => !!(RESULT && PLAN);
let PLAN = null;      // программа после выбора пациента и правок куратора
let SAMPLES = [];

function renderForm() {
  const f = $('#anketa');
  const dc = CONSENT && CONSENT.data;
  f.innerHTML = (dc ? `<fieldset class="block consent-data"><legend>${esc(dc.title)}</legend><p class="small">${esc(dc.text)}</p>
      <label class="chip ${A.consent_data === 'yes' ? 'on' : ''}"><input type="checkbox" name="consent_data_cb" ${A.consent_data === 'yes' ? 'checked' : ''}>Согласен(на) — продолжить</label></fieldset>` : '') + Q.filter((b) => !b.show || b.show(A)).map((b) => `
    <fieldset class="block"><legend>${esc(b.block)}</legend>${b.hint ? `<p class="muted small">${esc(b.hint)}</p>` : ''}
      ${b.items.filter((q) => !q.show || q.show(A)).map(fieldHTML).join('')}
    </fieldset>`).join('');
}

function fieldHTML(q) {
  const v = A[q.id];
  if (q.type === 'radio') return `<div class="q"><div class="q-label">${esc(q.label)}${q.req ? ' *' : ''}</div><div class="chips">
    ${q.opts.map(([k, t]) => `<label class="chip ${v === k ? 'on' : ''}"><input type="radio" name="${q.id}" value="${k}" ${v === k ? 'checked' : ''}>${esc(t)}</label>`).join('')}</div></div>`;
  if (q.type === 'checks') return `<div class="q"><div class="q-label">${esc(q.label)}</div><div class="chips">
    ${q.opts.map(([k, t]) => `<label class="chip ${(v || []).includes(k) ? 'on' : ''}"><input type="checkbox" name="${q.id}" value="${k}" ${(v || []).includes(k) ? 'checked' : ''}>${esc(t)}</label>`).join('')}</div></div>`;
  if (q.type === 'conditions') {
    const cond = A.conditions || [], reg = A.reg || [];
    return `<div class="cond-grid">${CONDITIONS.map(([k, t, code]) => `<div class="cond ${cond.includes(k) ? 'on' : ''}">
      <label><input type="checkbox" name="conditions" value="${k}" ${cond.includes(k) ? 'checked' : ''}> ${esc(t)}</label>
      ${cond.includes(k) && code ? `<label class="reg small"><input type="checkbox" name="reg" value="${k}" ${reg.includes(k) ? 'checked' : ''}> на учёте у врача</label>` : ''}
    </div>`).join('')}</div>`;
  }
  const type = q.type === 'number' ? 'number' : q.type;
  return `<div class="q"><label class="q-label" for="f-${q.id}">${esc(q.label)}${q.req ? ' *' : ''}</label>
    <input id="f-${q.id}" name="${q.id}" type="${type}" value="${esc(v ?? '')}" placeholder="${esc(q.ph || '')}"></div>`;
}

function readForm(e) {
  const t = e.target; if (!t.name) return;
  if (t.name === 'consent_data_cb') { A.consent_data = t.checked ? 'yes' : ''; renderForm(); checkStop(); return; }
  if (t.type === 'checkbox') {
    const set = new Set(A[t.name] || []); t.checked ? set.add(t.value) : set.delete(t.value); A[t.name] = [...set];
    if (t.name === 'conditions' && !t.checked) A.reg = (A.reg || []).filter((x) => x !== t.value);
  } else A[t.name] = t.value;
  if (t.type === 'radio' || t.type === 'checkbox') renderForm();
  checkStop();
}

function defaults() { Q.forEach((b) => b.items.forEach((q) => { if (q.def && A[q.id] === undefined) A[q.id] = q.def; })); }

function checkStop() {
  const s = $('#stop');
  if (A.urgent && A.urgent !== 'none') {
    s.innerHTML = `<b>Это не чекап.</b> Если что-то беспокоит прямо сейчас — обратитесь к врачу. При острой боли в груди, сильной одышке, признаках инсульта — звоните <b>103</b>.`;
    s.classList.remove('hidden'); $('#btn-predict').disabled = true;
  } else { s.classList.add('hidden'); $('#btn-predict').disabled = A.consent_data !== 'yes'; }
}

function toInput() {
  const code = Object.fromEntries(CONDITIONS.map(([k, , c]) => [k, c]));
  const inp = { sex: A.sex, birth_date: A.birth_date, checkup_year: 2026, for_child: A.for_child === 'true', urgent: A.urgent || 'none',
    pregnant: A.pregnant, conditions: A.conditions || [], registered: (A.reg || []).map((k) => code[k]).filter(Boolean),
    family_history: A.family_history || [], hazardous_work_10y: A.hazardous_work_10y === 'true', discharge: A.discharge, dysuria: A.dysuria,
    anesthesia_reaction: A.anesthesia_reaction, blood_thinners: A.blood_thinners, allergy: A.allergy, companion: A.companion,
    attached_to: A.attached_to, medications: A.medications, last_period: A.last_period, pregnancies: A.pregnancies, births: A.births,
    contraception: A.contraception };
  if (A.smoke_status && A.smoke_status !== 'never') inp.smoking = { pack_years: Math.round((+A.cigs || 0) / 20 * (+A.smoke_years || 0)), quit_years_ago: A.smoke_status === 'quit' ? +A.quit_years_ago || 0 : 0 };
  const ls = {}; if (A.ls_pap) ls.scr_cervix = +A.ls_pap; if (A.ls_mammo) ls.scr_breast = +A.ls_mammo; inp.last_screening = ls;
  return inp;
}

function fromInput(inp) {
  const back = Object.fromEntries(CONDITIONS.filter((c) => c[2]).map(([k, , c]) => [c, k]));
  A = { ...inp, for_child: String(!!inp.for_child), hazardous_work_10y: String(!!inp.hazardous_work_10y),
    conditions: [...(inp.conditions || [])], reg: (inp.registered || []).map((c) => back[c]).filter(Boolean),
    family_history: [...(inp.family_history || [])] };
  (inp.registered || []).forEach((c) => { const k = back[c]; if (k && !A.conditions.includes(k)) A.conditions.push(k); });
  if (!A.birth_date && inp.birth_year) A.birth_date = `${inp.birth_year}-06-01`;
  if (inp.smoking && inp.smoking.pack_years) { A.smoke_status = inp.smoking.quit_years_ago ? 'quit' : 'now'; A.cigs = 20; A.smoke_years = inp.smoking.pack_years; A.quit_years_ago = inp.smoking.quit_years_ago; }
  if (inp.last_screening) { A.ls_pap = inp.last_screening.scr_cervix; A.ls_mammo = inp.last_screening.scr_breast; }
  defaults(); renderForm(); checkStop();
}

async function doPredict() {
  if (A.consent_data !== 'yes') { alert('Нужно согласие на обработку ответов'); return; }
  if (!A.sex || !A.birth_date) { alert('Укажите пол и дату рождения'); return; }
  const r = await fetch('/api/predict', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(toInput()) });
  RESULT = await r.json();
  if (RESULT.error) { alert('Ошибка расчёта: ' + RESULT.error); return; }
  PLAN = {
    free: RESULT.free.map((f) => ({ ...f, choice: 'free', on: true })),
    items: RESULT.items.map((x) => ({ ...x, on: !x.optional && !x.free_option })),
    extras: RESULT.extras.map((x) => ({ ...x, on: true })),
    added: [], approved: null, answers: {}, consent_ok: {}, consent_signed: null,
  };
  renderProgram(); go('program');
}

// ---------- 2. Программа ----------
function srcHTML(s) { return s ? `<span class="src" title="${esc(s.full)}">Источник: ${esc(s.text)}</span>` : ''; }

function renderProgram() {
  const R = RESULT;
  if (R.red_flag) { $('#program').innerHTML = `<div class="alert-red">${esc(R.message)}</div>`; return; }
  $('#program-lead').textContent = `Возраст для скрининга — ${R.age_year} (по году рождения, как в приказе); полных лет — ${R.full_age}.`;
  const freeHTML = PLAN.free.length ? PLAN.free.map((f, i) => `
    <div class="card free">
      <div class="card-top"><span class="pill pill-free">${PAY[f.payment]}</span><h3>${esc(f.name)}</h3></div>
      <ul class="dots">${f.exams.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>
      ${f.note ? `<p class="muted small">${esc(f.note)}</p>` : ''}
      ${f.in_package ? `<div class="choice">
        <label class="${f.choice === 'free' ? 'on' : ''}"><input type="radio" name="ch${i}" value="free" ${f.choice === 'free' ? 'checked' : ''} data-free="${i}">Бесплатно в поликлинике — до ${f.deadline_days} дней</label>
        <label class="${f.choice === 'prime' ? 'on' : ''}"><input type="radio" name="ch${i}" value="prime" ${f.choice === 'prime' ? 'checked' : ''} data-free="${i}">В PRIME — сегодня, в составе пакета</label></div>`
    : `<p class="small"><b>Где:</b> ${A.attached_to === 'green_clinic' ? 'Green Clinic, по прикреплению' : 'ваша поликлиника прикрепления'}, в течение ${f.deadline_days} дней. В пакете PRIME этого нет.</p>`}
      <div class="meta">Повтор — раз в ${f.repeat_years} ${f.repeat_years < 5 ? 'года' : 'лет'} · ${srcHTML(f.source)}</div>
    </div>`).join('') : '<p class="muted">В этом году бесплатный скрининг по возрасту не положен.</p>';

  const itemsHTML = PLAN.items.map((x) => `<li class="${x.emphasis.length ? 'emph' : ''} ${x.optional ? 'opt' + (x.on ? ' on' : '') : ''}">
      <div>${esc(x.exam)}${x.free_option ? ` <span class="pill pill-free-s">${x.on ? 'есть бесплатно — выбрано в PRIME' : 'делаете бесплатно в поликлинике'}</span>` : ''}${x.optional ? ` <span class="pill pill-opt">${x.on ? 'куратор включил' : 'по показаниям — выбирает куратор'}</span>` : ''}</div>
      ${x.emphasis.length ? `<div class="small accent">Особое внимание: ${esc([...new Set(x.emphasis)].join('; '))}</div>` : ''}
      ${x.flags.map((f) => `<div class="small warn">${esc(f)}</div>`).join('')}
    </li>`).join('');

  const extrasHTML = PLAN.extras.length ? `<div class="card extra"><div class="card-top"><span class="pill pill-extra">Сверх пакета — по вашим ответам</span></div>
      ${PLAN.extras.map((x, i) => `<label class="extra-row"><input type="checkbox" data-extra="${i}" ${x.on ? 'checked' : ''}>
        <div><b>${esc(x.exam)}</b><div class="small">${esc(x.why)} · <span class="warn">уточнит врач-куратор</span></div></div></label>`).join('')}
      <div class="meta">${srcHTML(PLAN.extras[0].source)}</div></div>` : '';

  const noHTML = RESULT.not_eligible.length ? `<div class="card muted-card"><h3>Не включили — и почему</h3>
      ${RESULT.not_eligible.map((n) => `<p class="small"><b>${esc(n.name)}:</b> ${esc(n.why)}</p>`).join('')}</div>` : '';

  $('#program').innerHTML = `
    <div class="grid2">
      <div><h2 class="h-free">1 · Положено бесплатно</h2>${freeHTML}${noHTML}</div>
      <div><h2 class="h-prime">2 · ${esc(R.package.name)}</h2>
        <div class="card prime"><p class="small muted">У каждого пункта — причина: «входит в пакет PRIME», ${srcHTML(R.items[0].source)}</p>
        <ul class="exams">${itemsHTML}</ul></div>${extrasHTML}</div>
    </div>
    <h2>3 · Информированное согласие</h2>${consentHTML()}
    <h2>4 · Маршрут на один день — и как подготовиться к каждой процедуре</h2>${routeHTML(R.route)}
    <div class="actions"><button class="btn-primary" data-go="prep">Дальше: подготовка по дням →</button></div>`;
}

function routeHTML(route) {
  return `<ol class="route">${route.steps.map((s) => `<li>
      <span class="time">${s.time}</span>
      <div class="r-body"><div class="r-title">${s.room && s.room !== '—' ? `<span class="room">каб. ${esc(s.room)}</span> ` : ''}${esc(s.title)}</div>
        ${s.exams && s.exams.length ? `<div class="small muted">${esc(s.exams.join(' · '))}</div>` : ''}
        ${s.room && s.room !== '—' ? `<details class="prep-info" ${s.prep ? 'open' : ''}><summary>Как подготовиться</summary>${s.prep
          ? s.prep.map((p) => `<div class="prep-line">${prepImg(p.id)}<b>${esc(p.title)}.</b> ${esc(p.text)}<div class="meta">${esc(p.source)}</div></div>`).join('')
          : '<div class="prep-line small">Особой подготовки в памятке PRIME нет — уточнит врач-куратор.</div>'}</details>` : (s.prep ? s.prep.map((p) => `<div class="prep-line small"><b>${esc(p.title)}.</b> ${esc(p.text)}</div>`).join('') : '')}
      </div>
      ${s.minutes ? `<span class="muted small">${s.minutes} мин</span>` : '<span></span>'}</li>`).join('')}</ol>
    <p class="small muted">${esc(route.final)} · Время — если вы в клинике одни; в загруженный день куратор даст своё время прихода (вкладка «Утро клиники»). Кабинеты — по списку медэксперта, длительности уточняет клиника.</p>`;
}

function prepImg(id, size = '') {
  return id ? `<img class="prep-img ${size}" src="/static/img/prep/${esc(id)}.svg" alt="" onerror="this.remove()">` : '';
}

function consentHTML() {
  const cs = RESULT.consents || [];
  const ok = cs.filter((c) => PLAN.consent_ok[c.id]).length;
  return `<div class="card consent"><p class="small">Медицинская помощь оказывается после информированного согласия; на процедуры ниже — письменно, на бланке клиники у врача-куратора. Прочитайте и отметьте «понятно» — вопросы задайте куратору.</p>
    ${cs.map((c) => `<div class="consent-item ${PLAN.consent_ok[c.id] ? 'ok' : ''}">
      <h3>${esc(c.title)}</h3>
      <dl><dt>Что это</dt><dd>${esc(c.what)}</dd><dt>Зачем</dt><dd>${esc(c.why)}</dd><dt>Риски</dt><dd>${esc(c.risks)}</dd><dt>Альтернатива</dt><dd>${esc(c.alternative)}</dd></dl>
      ${c.exams ? `<div class="small muted">Касается: ${esc(c.exams.join(' · '))}</div>` : ''}
      <label class="chip ${PLAN.consent_ok[c.id] ? 'on' : ''}"><input type="checkbox" data-consent="${c.id}" ${PLAN.consent_ok[c.id] ? 'checked' : ''}>Понятно, подпишу у куратора</label>
    </div>`).join('')}
    <div class="meta">Понятно: ${ok} из ${cs.length} · ${srcHTML(cs[0] && cs[0].source)}</div></div>`;
}

// ---------- 3. Подготовка ----------
const DAYS = { now: 'Сейчас', eve: 'Накануне', morning: 'Утром в день чекапа', after: 'После процедур' };
function renderPrep() {
  if (!RESULT || RESULT.red_flag) { $('#prep').innerHTML = '<p class="muted">Сначала заполните анкету.</p>'; return; }
  const by = {}; RESULT.prep.forEach((p) => (by[p.day] ||= []).push(p));
  $('#prep').innerHTML = Object.keys(DAYS).filter((d) => by[d]).map((d) => `<h2>${DAYS[d]}</h2>${by[d].map((p) => {
    const ans = PLAN.answers[p.id];
    return `<div class="card prep">${prepImg(p.id, 'big')}<h3>${esc(p.title)}</h3><p>${esc(p.text)}</p>
      <div class="quiz"><div class="q-label">${esc(p.question)}</div><div class="chips">
      ${p.options.map((o, i) => `<button class="chip ${ans === i ? (i === p.correct ? 'ok' : 'bad') : ''}" data-quiz="${p.id}" data-i="${i}">${esc(o)}</button>`).join('')}</div>
      ${ans === undefined ? '' : ans === p.correct ? '<div class="small ok-t">Верно</div>' : '<div class="small bad-t">Не совсем — перечитайте пункт выше</div>'}</div>
      <div class="meta">${esc(p.source)}</div></div>`;
  }).join('')}`).join('') + `<div class="actions"><span class="muted small" id="prep-done"></span><button class="btn-primary" data-go="curator">Дальше: к врачу-куратору →</button></div>`;
  const ok = RESULT.prep.filter((p) => PLAN.answers[p.id] === p.correct).length;
  $('#prep-done').textContent = `Понято: ${ok} из ${RESULT.prep.length}`;
}

// ---------- 4. Куратор ----------
let CATALOG = [], CONSENT = null;
function planLines() {
  const L = [];
  PLAN.free.forEach((f, i) => L.push({ kind: f.choice === 'free' ? 'Бесплатно, поликлиника' : 'Бесплатное — делаем в PRIME', name: f.name, why: f.note || 'Госскрининг по возрасту и полу', src: f.source.text, on: f.on, ref: ['free', i] }));
  PLAN.items.forEach((x, i) => L.push({ kind: x.optional ? 'Пакет PRIME — по выбору куратора' : 'Пакет PRIME', name: x.exam, why: x.emphasis.length ? 'Особое внимание: ' + [...new Set(x.emphasis)].join('; ') : (x.optional ? x.why : 'Входит в пакет'), src: 'primegc.kz', on: x.on, ref: ['items', i] }));
  PLAN.extras.forEach((x, i) => L.push({ kind: 'Сверх пакета', name: x.exam, why: x.why, src: 'правило анамнеза (утверждает врач)', on: x.on, ref: ['extras', i] }));
  PLAN.added.forEach((x, i) => L.push({ kind: 'Добавил куратор', name: x.name, why: 'решение врача', src: 'каталог PRIME', on: true, ref: ['added', i] }));
  return L;
}

function renderCurator() {
  if (!RESULT || RESULT.red_flag) { $('#curator').innerHTML = '<p class="muted">Сначала заполните анкету.</p>'; return; }
  const inp = toInput();
  const facts = [
    `${inp.sex === 'F' ? 'Женщина' : 'Мужчина'}, ${RESULT.full_age} лет`,
    inp.conditions.length ? 'Отметил(а): ' + inp.conditions.map((c) => CONDITIONS.find((x) => x[0] === c)[1].toLowerCase()).join(', ') : 'Болезней не отмечено',
    inp.registered.length ? 'На учёте: ' + inp.registered.length : '',
    inp.family_history.length ? 'Семья: ' + inp.family_history.map((c) => FAMILY.find((x) => x[0] === c)[1].toLowerCase()).join(', ') : '',
    inp.medications ? 'Лекарства: ' + inp.medications : '',
    inp.blood_thinners === 'yes' ? '⚠ Разжижающие кровь' : '', inp.allergy === 'yes' ? '⚠ Аллергия на лекарства' : '',
    inp.anesthesia_reaction === 'yes' ? '⚠ Реакция на наркоз' : '', inp.companion === 'no' ? '⚠ Без сопровождающего' : '',
    inp.pregnant === 'yes' ? '⚠ Беременность' : '',
  ].filter(Boolean);
  const lines = planLines();
  const ap = PLAN.approved;
  $('#curator').innerHTML = `
    <div class="grid2 curator">
      <div class="card"><h3>Анкета пациента</h3><ul class="dots">${facts.map((f) => `<li>${esc(f)}</li>`).join('')}</ul>
        <p class="small muted">Подготовка понята: ${RESULT.prep.filter((p) => PLAN.answers[p.id] === p.correct).length} из ${RESULT.prep.length}</p>
        <div class="consent-check"><b>Информированное согласие</b>
          <div class="small">Пациент отметил «понятно»: ${RESULT.consents.filter((c) => PLAN.consent_ok[c.id]).length} из ${RESULT.consents.length}</div>
          <div class="small">${RESULT.consents.map((c) => `${PLAN.consent_ok[c.id] ? '✓' : '○'} ${esc(c.title)}`).join('<br>')}</div>
          <label class="chip ${PLAN.consent_signed ? 'on' : ''}"><input type="checkbox" id="consent-signed" ${PLAN.consent_signed ? 'checked' : ''} ${ap ? 'disabled' : ''}>Бланки согласия подписаны пациентом</label></div></div>
      <div class="card"><h3>Добавить услугу из каталога PRIME</h3>
        <select id="add-select">${CATALOG.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
        <button class="btn" id="btn-add" ${ap ? 'disabled' : ''}>Добавить</button></div>
    </div>
    <h2>Состав программы — отметьте, что входит</h2>
    <p class="small muted">Снятая галочка — пункт не делаем. Онкомаркеры по умолчанию не отмечены: выбираются по показаниям.</p>
    <table class="tbl"><thead><tr><th></th><th>Обследование</th><th>Тип</th><th>Почему</th><th>Источник</th></tr></thead><tbody>
      ${lines.map((l) => `<tr class="${l.on ? '' : 'off'}"><td>${l.ref ? `<input type="checkbox" ${l.on ? 'checked' : ''} ${ap ? 'disabled' : ''} data-toggle="${l.ref.join(':')}">` : '✓'}</td>
        <td>${esc(l.name)}</td><td class="small">${esc(l.kind)}</td><td class="small">${esc(l.why)}</td><td class="small muted">${esc(l.src)}</td></tr>`).join('')}
    </tbody></table>
    <div class="actions">${ap ? `<span class="approved">✓ Утверждено врачом-куратором ${ap}</span><button class="btn" id="btn-print">Итоговый лист (печать)</button><button class="btn-primary" data-go="card">Карта здоровья →</button>`
      : `${PLAN.consent_signed ? '' : '<span class="small warn">Утвердить можно после подписи согласия</span>'}<button class="btn-primary" id="btn-approve" ${PLAN.consent_signed ? '' : 'disabled'}>Утвердить программу</button>`}</div>
    ${finalSheetHTML(lines)}`;
}

function finalSheetHTML(lines) {
  return `<div id="final-sheet" class="sheet"><h2>Итоговый лист чекапа</h2>
    <p>${esc(RESULT.package.name)} · утверждено: ${esc(PLAN.approved || '—')} · врач-куратор: ____________</p>
    <p>Информированное согласие подписано: ${esc(PLAN.consent_signed || '—')} (${RESULT.consents.map((c) => esc(c.title)).join('; ')})</p>
    <table class="tbl"><tbody>${lines.filter((l) => l.on).map((l) => `<tr><td>${esc(l.name)}</td><td>${esc(l.kind)}</td><td>результат: ____________</td></tr>`).join('')}</tbody></table>
    <p><b>Повторить:</b> ${RESULT.next_visit.map((n) => `${esc(n.name)} — ${n.year}`).join('; ')}</p>
    <p class="small">Рекомендации не являются диагнозом. Решение о назначениях принимает врач.</p></div>`;
}

// ---------- 5. Карта здоровья ----------
const CARD_KEY = 'checkup_card_v1';
function loadCard() { try { return JSON.parse(localStorage.getItem(CARD_KEY)) || {}; } catch (e) { console.warn('карта: localStorage недоступен', e); return {}; } }
function saveCard(c) { try { localStorage.setItem(CARD_KEY, JSON.stringify(c)); } catch (e) { console.warn('карта: не сохранить', e); } }

function renderCard() {
  if (!PLAN || !PLAN.approved) { $('#card').innerHTML = '<p class="muted">Карта появится после того, как куратор утвердит программу.</p>'; return; }
  const c = loadCard(); c.done ||= {}; c.notes ||= {};
  const lines = planLines().filter((l) => l.on);
  const done = lines.filter((l) => c.done[l.name]).length;
  $('#card').innerHTML = `
    <p class="small">✓ Программа утверждена ${esc(PLAN.approved)} · информированное согласие подписано ${esc(PLAN.consent_signed || '—')}</p>
    <div class="progress"><div style="width:${Math.round(done / lines.length * 100)}%"></div></div>
    <p class="small">Пройдено ${done} из ${lines.length}</p>
    <table class="tbl"><thead><tr><th>Готово</th><th>Обследование</th><th>Результат / заключение</th></tr></thead><tbody>
    ${lines.map((l) => `<tr><td><input type="checkbox" data-done="${esc(l.name)}" ${c.done[l.name] ? 'checked' : ''}></td><td>${esc(l.name)}<div class="small muted">${esc(l.kind)}</div></td>
      <td><input class="note" data-note="${esc(l.name)}" value="${esc(c.notes[l.name] || '')}" placeholder="норма / отклонение / ссылка на файл"></td></tr>`).join('')}</tbody></table>
    <h2>Когда повторить</h2>
    <ul class="next">${RESULT.next_visit.filter((n) => !PLAN.free.some((f) => f.rule_id === n.rule_id && !f.on)).map((n, i) => `<li><b>${n.year}</b> — ${esc(n.name)} ${n.free ? '<span class="pill pill-free-s">бесплатно</span>' : ''}
      <button class="btn small" data-ics="${esc(n.rule_id)}">В календарь</button></li>`).join('')}</ul>
    <h2>Как прошёл чекап?</h2>
    <div class="stars">${[1, 2, 3, 4, 5].map((s) => `<button class="star ${c.rating >= s ? 'on' : ''}" data-star="${s}">★</button>`).join('')}</div>
    <input class="note wide" id="rating-comment" value="${esc(c.comment || '')}" placeholder="что улучшить?">`;
}

function ics(n) {
  const d = `${n.year}${String(new Date().getMonth() + 1).padStart(2, '0')}01`;
  const body = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//PRIME checkup//RU', 'BEGIN:VEVENT', `UID:${n.rule_id}-${n.year}@prime`,
    `DTSTART;VALUE=DATE:${d}`, `SUMMARY:Пора повторить: ${n.name}`, `DESCRIPTION:${n.free ? 'Бесплатно по госскринингу в поликлинике прикрепления' : 'Запись в PRIME'}`,
    'BEGIN:VALARM', 'TRIGGER:-P7D', 'ACTION:DISPLAY', 'DESCRIPTION:Напоминание о чекапе', 'END:VALARM', 'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([body], { type: 'text/calendar' }));
  a.download = `checkup_${n.rule_id}_${n.year}.ics`; a.click();
}

// ---------- ★ Утро клиники ----------
let MORNING = null, MODE = 'staggered', PLACES = {};
async function renderMorning() {
  const box = $('#morning');
  if (!MORNING) { box.innerHTML = '<p class="muted">Считаем…</p>'; MORNING = await (await fetch('/api/morning', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ places: PLACES }) })).json(); }
  const a = MORNING.same_time, b = MORNING.staggered, m = MORNING[MODE];
  const t0 = 8 * 60, toMin = (s) => +s.slice(0, 2) * 60 + +s.slice(3) - t0;
  const span = Math.max(...m.patients.map((p) => toMin(p.finish))) + 10;
  const cls = (title) => /наркоз|Эндоскоп/i.test(title) ? 'b-endo' : /куратор/i.test(title) ? 'b-cur' : /кровь|Процедур/i.test(title) ? 'b-lab' : /перекус|Отдых/i.test(title) ? 'b-rest' : 'b-diag';
  box.innerHTML = `
    <div class="mode chips">
      <button class="chip ${MODE === 'same_time' ? 'on' : ''}" data-mode="same_time">Все приходят к 08:00</button>
      <button class="chip ${MODE === 'staggered' ? 'on' : ''}" data-mode="staggered">Каждому — своё время прихода</button>
      ${(() => { const u = m.load.find((l) => l.places_options); return u ? `<span class="places">${esc(u.title)}: мест ${u.places_options.map((n) => `<button class="chip small ${u.places === n ? 'on' : ''}" data-places="${u.room_id}:${n}">${n}</button>`).join('')}</span>` : ''; })()}</div>
    <div class="capacity">Сколько полных чекапов клиника берёт в день, чтобы все освободились к ${esc(MORNING.capacity.day_close)}: <b>${MORNING.capacity.fits} из ${MORNING.capacity.of}</b> (последний свободен в ${esc(MORNING.capacity.day_end || '—')})</div>
    <div class="compare"><div><span class="muted small">Среднее ожидание в коридоре</span><b>${a.avg_wait} мин → ${b.avg_wait} мин</b></div>
      <div><span class="muted small">Самое долгое ожидание</span><b>${a.max_wait} мин → ${b.max_wait} мин</b></div>
      <div><span class="muted small">Кабинеты освобождаются</span><b>${a.day_end} → ${b.day_end}</b></div></div>
    <div class="kpis">
      <div class="kpi"><b>${m.patients.length}</b><span>пациентов утра</span></div>
      <div class="kpi"><b>${m.rooms_count}</b><span>кабинетов (список медэксперта)</span></div>
      <div class="kpi"><b>${m.avg_wait} мин</b><span>среднее ожидание</span></div>
      <div class="kpi warn-k"><b>${esc(m.bottleneck.room)}</b><span>узкое место: ${esc(m.bottleneck.title)}, занят ${Math.round(m.bottleneck.share * 100)}% дня</span></div>
    </div>
    <div class="gantt">${m.patients.map((p) => `<div class="g-row"><div class="g-label">${esc(p.label)}<div class="small muted">приход ${p.arrive} · свободен ${p.finish} · ждал ${p.wait_total} мин</div></div>
      <div class="g-track">${p.steps.map((s) => `<div class="g-bar ${cls(s.title)}" style="left:${toMin(s.start) / span * 100}%;width:${Math.max(0.6, (toMin(s.end) - toMin(s.start)) / span * 100)}%" title="${esc(s.start + '–' + s.end + ' ' + s.room + ' ' + s.title)}">${esc(s.room !== '—' ? s.room : '')}</div>`).join('')}</div></div>`).join('')}
      <div class="g-axis">${Array.from({ length: Math.ceil(span / 60) + 1 }, (_, h) => `<span style="left:${h * 60 / span * 100}%">${String(8 + h).padStart(2, '0')}:00</span>`).join('')}</div>
    </div>
    <div class="legend small"><span class="b-cur">куратор</span><span class="b-lab">кровь, моча</span><span class="b-diag">диагностика и консультации</span><span class="b-endo">эндоскопия под наркозом</span><span class="b-rest">перекус, отдых</span></div>
    <h2>Загрузка кабинетов</h2>
    <div class="load">${m.load.map((l) => `<div class="l-row"><span>${esc(l.room)} ${esc(l.title)}</span><div class="l-bar"><div style="width:${Math.round(l.share * 100)}%"></div></div><span>${Math.round(l.share * 100)}%</span></div>`).join('')}</div>
    <p class="small muted">Время прихода: сдвигаем приход на ожидание перед узким местом (эндоскопия), с шагом 15 минут. Кабинеты, места и длительности — демонстрационные (${esc(m.source.full)}). Клиника вносит свои — скрипт считает без изменений кода.</p>`;
}

// ---------- Демо-сценарий: 12 пациентов по всем этапам ----------
let SCN = null;
async function renderScenario() {
  const box = $('#scenario');
  if (!SCN) { box.innerHTML = '<p class="muted">Считаем…</p>'; SCN = await (await fetch('/api/scenario', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ places: PLACES }) })).json(); }
  const ok = SCN.patients.filter((p) => !p.red_flag).length;
  box.innerHTML = `<div class="kpis">
      <div class="kpi"><b>${SCN.patients.length}</b><span>пациентов заполнили анкету</span></div>
      <div class="kpi warn-k"><b>${SCN.patients.length - ok}</b><span>остановлены: беспокоит сейчас — к врачу, не чекап</span></div>
      <div class="kpi"><b>${ok}</b><span>получили программу, согласие, маршрут</span></div>
      <div class="kpi"><b>${SCN.days.length} дня</b><span>${SCN.days.map((d) => `день ${d.day}: ${d.count} чел., ожидание ${d.avg_wait} мин, до ${d.day_end}`).join('; ')}</span></div></div>
    <div class="scn-wrap"><table class="tbl scn"><thead><tr><th>Пациент</th><th>1 Анкета</th><th>2 Программа</th><th>3 Согласие</th><th>4 Подготовка</th><th>5 Запись и утро</th><th>6 Карта: повтор</th></tr></thead><tbody>
    ${SCN.patients.map((p, i) => p.red_flag
      ? `<tr class="stop"><td><button class="chip small" data-sample="${i}" data-go-anketa="1">${esc(p.name)}</button></td><td colspan="6">⛔ «Беспокоит прямо сейчас» — анкета остановлена: к врачу, при острой боли — 103. Чекап не предлагаем.</td></tr>`
      : `<tr><td><button class="chip small" data-sample="${i}" data-go-anketa="1">${esc(p.name)}</button></td>
        <td>✓</td>
        <td><b>${esc(p.package)}</b><div class="small">бесплатно: ${p.free.length ? esc(p.free.join(', ')) : '—'}</div>${p.extras.length ? `<div class="small accent">сверх пакета: ${esc(p.extras.join(', '))}</div>` : ''}</td>
        <td class="small">${esc(p.consents.join('; '))}</td>
        <td class="small">${p.prep} пунктов с вопросом</td>
        <td class="small"><b>день ${p.day}</b>${p.day > 1 ? ' (запись на следующий)' : ''}<br>приход <b>${esc(p.arrive || '—')}</b><br>свободен ${esc(p.finish || '—')}<br>ждал ${p.wait ?? '—'} мин</td>
        <td class="small">${esc(p.next.join('; '))}</td></tr>`).join('')}
    </tbody></table></div>
    <p class="small muted">Демо-пациенты — синтетика: 9 эталонных анкет формы команды и 3 контрольных пациента. Нажмите на имя — анкета заполнится, и пациента можно провести по этапам вручную.</p>`;
}

// ---------- навигация и события ----------
function go(v) {
  document.querySelectorAll('.view').forEach((s) => s.classList.toggle('active', s.id === 'view-' + v));
  document.querySelectorAll('.step').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
  if (v === 'program' && RESULT) renderProgram();
  if (v === 'prep') renderPrep();
  if (v === 'curator') renderCurator();
  if (v === 'card') renderCard();
  if (v === 'morning') renderMorning();
  if (v === 'scenario') renderScenario();
  window.scrollTo(0, 0);
}

document.addEventListener('click', (e) => {
  const t = e.target.closest('#btn-play,[data-places],[data-scenario],[data-mode],[data-view],[data-go],[data-quiz],[data-star],[data-ics],#btn-predict,#btn-approve,#btn-add,#btn-print,[data-sample]');
  if (!t) return;
  if (t.dataset.mode) { MODE = t.dataset.mode; renderMorning(); }
  else if (t.dataset.places) { const [r, n] = t.dataset.places.split(':'); PLACES = { [r]: +n }; MORNING = null; renderMorning(); }
  else if (t.dataset.scenario !== undefined) { SCN = null; renderScenario(); }
  else if (t.dataset.view === 'anketa') location.href = '/';
  else if (t.dataset.view) go(t.dataset.view);
  else if (t.dataset.go) go(t.dataset.go);
  else if (t.id === 'btn-predict') { e.preventDefault(); doPredict(); }
  else if (t.dataset.sample !== undefined && t.dataset.goAnketa) { fromInput(SAMPLES[+t.dataset.sample].input); A.consent_data = 'yes'; doPredict(); }
  else if (t.dataset.sample !== undefined) { fromInput(SAMPLES[+t.dataset.sample].input); A.consent_data = 'yes'; renderForm(); checkStop(); }
  else if (t.dataset.quiz) { PLAN.answers[t.dataset.quiz] = +t.dataset.i; renderPrep(); }
  else if (t.id === 'btn-approve') { PLAN.approved = new Date().toLocaleString('ru-RU'); saveCard({}); renderCurator(); }
  else if (t.id === 'btn-add') { const c = CATALOG.find((x) => x.id === $('#add-select').value); if (c && !PLAN.added.some((a) => a.name === c.name)) PLAN.added.push({ name: c.name }); renderCurator(); }
  else if (t.id === 'btn-print') window.print();
  else if (t.id === 'btn-play') location.href = '/?play=1';
  else if (t.dataset.star) { const c = loadCard(); c.rating = +t.dataset.star; saveCard(c); renderCard(); }
  else if (t.dataset.ics) ics(RESULT.next_visit.find((n) => n.rule_id === t.dataset.ics));
});

document.addEventListener('change', (e) => {
  const t = e.target;
  if (t.closest('#anketa')) return readForm(e);
  if (t.dataset.free !== undefined) {
    const f = PLAN.free[+t.dataset.free]; f.choice = t.value;
    PLAN.items.forEach((x) => { if (x.free_option === f.rule_id) x.on = t.value === 'prime'; });  // бесплатное не продаём второй раз
    renderProgram();
  }
  if (t.dataset.extra !== undefined) { PLAN.extras[+t.dataset.extra].on = t.checked; }
  if (t.dataset.consent) { PLAN.consent_ok[t.dataset.consent] = t.checked; renderProgram(); }
  if (t.id === 'consent-signed') { PLAN.consent_signed = t.checked ? new Date().toLocaleString('ru-RU') : null; renderCurator(); }
  if (t.dataset.toggle) { const [k, i] = t.dataset.toggle.split(':'); if (k === 'added') PLAN.added.splice(+i, 1); else PLAN[k][+i].on = t.checked; renderCurator(); }
  if (t.dataset.done !== undefined) { const c = loadCard(); c.done ||= {}; c.done[t.dataset.done] = t.checked; saveCard(c); renderCard(); }
  if (t.dataset.note !== undefined) { const c = loadCard(); c.notes ||= {}; c.notes[t.dataset.note] = t.value; saveCard(c); }
  if (t.id === 'rating-comment') { const c = loadCard(); c.comment = t.value; saveCard(c); }
});
document.addEventListener('input', (e) => { if (e.target.closest('#anketa') && e.target.type !== 'radio' && e.target.type !== 'checkbox') { A[e.target.name] = e.target.value; } });

(async function init() {
  defaults(); renderForm();
  try {
    SAMPLES = await (await fetch('/api/samples')).json();
    $('#sample-buttons').innerHTML = SAMPLES.map((s, i) => `<button class="chip small" data-sample="${i}">${esc(s.name.split(':')[0].split(',').slice(0, 2).join(','))}</button>`).join('');
    CATALOG = await (await fetch('/api/catalog')).json();
    CONSENT = await (await fetch('/api/consent')).json(); renderForm(); checkStop();
    let fromForm = null;
    try { fromForm = JSON.parse(sessionStorage.getItem('checkup_input') || 'null'); sessionStorage.removeItem('checkup_input'); }
    catch (e) { console.error('Ответы анкеты не прочитались', e); }
    if (fromForm) {
      fromInput(fromForm); A.consent_data = fromForm.consent_data === 'yes' ? 'yes' : A.consent_data; A.medications = fromForm.medications; await doPredict();
      if (sessionStorage.getItem('checkup_play')) { sessionStorage.removeItem('checkup_play'); window.startTour && window.startTour(); }
    }
    else if (location.hash === '#scenario') go('scenario');
    const src = await (await fetch('/api/sources')).json();
    $('#foot').innerHTML = `Правила: ${esc(src.DSM174)} · Пакеты: ${esc(src.PRIME)} · Open source, без внешних сервисов.`;
  } catch (err) { console.error('Не загрузились справочники', err); }
})();
