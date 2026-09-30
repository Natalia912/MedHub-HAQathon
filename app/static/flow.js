/* После анкеты: программа → подготовка → экран куратора (утверждение и итоговый лист) → карта здоровья.
   Всё строится из spec/rules.json: пакеты, anamnesis_rules, prep_catalog, prime_catalog. В коде медицинской логики нет.
   Демо: пациент и куратор работают в одном браузере, состояние — в localStorage. */
const PROGRAM_KEY = 'gc-program-v1';
const CARD_KEY = 'gc-health-card-v1';
const DAYS = { now: 'Сейчас, до визита', eve: 'Накануне', morning: 'Утро чекапа', after: 'После обследования' };
const DAY_ORDER = ['now', 'eve', 'morning', 'after'];
const store = {
  get(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch (error) { console.warn('Не прочитано из браузера:', key, error); return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (error) { console.warn('Не сохранено в браузере:', key, error); }
  },
};
const fmtDate = (d) => new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
const addDays = (iso, n) => { const d = new Date(iso); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
const has = (text, word) => text.toLowerCase().includes(word.toLowerCase());
let program = null;

/* ---------- сборка программы ---------- */
function ruleMatches(when) {
  return Object.entries(when).every(([key, value]) => {
    if (key === 'sex') return answers.sex === value;
    const answer = answers[key];
    return Array.isArray(answer) ? answer.includes(value) : answer === value;
  });
}
function buildProgram() {
  const r = compute();
  const catalog = Object.fromEntries(rules.prime_catalog.map((c) => [c.id, c]));
  const pkgUrl = r.pkg && (r.pkg.id === 'prime_child' ? r.pkg.url_mini : answers.sex === 'F' ? r.pkg.url_f : r.pkg.url_m);
  const items = r.pkgExams.map((x) => ({
    key: `p:${x.exam}`, name: x.exam, kind: 'package', included: !x.preg, free: x.free, part: x.part, preg: x.preg,
    reasons: x.preg ? ['не проводится при беременности'] : [], url: pkgUrl,
  }));
  if (r.pkg?.id === 'prime_child') {
    r.pkg.exams.forEach((e) => items.push({ key: `p:${e}`, name: e, kind: 'package', included: true, reasons: [], url: r.pkg.url_mini }));
    r.pkg.extended_exams.forEach((e) => items.push({ key: `o:${e}`, name: e, kind: 'option', included: false, reasons: ['из расширенного детского пакета'], url: r.pkg.url_extended }));
  }
  for (const rule of rules.anamnesis_rules.filter((x) => ruleMatches(x.when))) {
    for (const word of rule.emphasize || []) {
      items.filter((i) => i.kind === 'package' && has(i.name, word)).forEach((i) => {
        if (!i.reasons.includes(rule.why)) i.reasons.push(rule.why);
        i.emphasis = true;
      });
    }
    if (rule.skip_if_in_package && items.some((i) => i.kind === 'package' && has(i.name, rule.skip_if_in_package))) continue;
    for (const id of rule.add || []) {
      const c = catalog[id];
      if (!c) { console.warn('В каталоге нет услуги', id); continue; }
      const found = items.find((i) => i.key === `a:${id}`);
      if (found) { found.reasons.push(rule.why); continue; }
      items.push({ key: `a:${id}`, name: c.name, kind: 'addon', included: true, reasons: [rule.why], url: c.url, validate: rule.needs_doctor_validation });
    }
  }
  return { answersKey: JSON.stringify(answers), items, prep: {}, date: addDays(new Date().toISOString().slice(0, 10), 7),
    approved: null, results: {}, conclusion: { outcome: 'ok', specialist: '', note: '' }, sheetAt: null };
}
function currentProgram() {
  const saved = program || store.get(PROGRAM_KEY, null);
  program = saved && saved.answersKey === JSON.stringify(answers) ? saved : buildProgram();
  store.set(PROGRAM_KEY, program);
  return program;
}
const saveProgram = () => store.set(PROGRAM_KEY, program);
const included = () => program.items.filter((i) => i.included);
function prepItems() {
  const names = included().map((i) => i.name).join(' | ');
  return rules.prep_catalog.filter((p) => {
    if (p.when_answer && !Object.entries(p.when_answer).every(([k, v]) => answers[k] === v)) return false;
    return p.match.some((word) => has(names, word));
  }).sort((a, b) => DAY_ORDER.indexOf(a.day) - DAY_ORDER.indexOf(b.day));
}
const hhmm = (min) => `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`;
// Маршрут дня: шаги route_plan, для которых в программе есть подходящая услуга; время — от начала дня подряд
function routePlan() {
  const plan = rules.route_plan, names = included().map((i) => i.name).join(' | ');
  const [h, m] = plan.start.split(':').map(Number);
  const start = h * 60 + m;
  let t = start;
  const steps = [];
  for (const s of plan.steps) {
    const skip = s.only_without ? s.only_without.some((w) => has(names, w)) : !s.match.some((w) => has(names, w));
    if (skip) continue;
    steps.push({ ...s, time: hhmm(t), at: t });
    t += s.minutes;
  }
  return { steps, minutes: t - start };
}
function routeBlock() {
  const r = routePlan();
  if (!r.steps.length) return '';
  return `<section class="result-block route"><span class="result-label">Маршрут на один день · ${fmtDate(program.date)}</span>` +
    `<h3>Около ${Math.floor(r.minutes / 60)} ч ${r.minutes % 60} мин в клинике</h3><ol class="route-list">${r.steps.map((s) =>
      `<li><b>${s.time}</b>${escapeHtml(s.title)}</li>`).join('')}</ol>` +
    `<p class="card-note">${escapeHtml(rules.route_plan.final)}</p><small class="src">Время ориентировочное — расписание кабинетов уточняет клиника.</small></section>`;
}
function dayDate(day) {
  if (day === 'eve') return addDays(program.date, -1);
  if (day === 'now') return new Date().toISOString().slice(0, 10);
  return program.date;
}

/* ---------- общие куски ---------- */
function flowNav(active) {
  const tabs = [['result', 'Программа'], ['prep', 'Подготовка'], ['curator', 'Куратор'], ['card', 'Карта здоровья']];
  return `<nav class="flow-nav" aria-label="Разделы">${tabs.map(([id, label]) =>
    `<button type="button" data-flow="${id}" ${id === active ? 'aria-current="page"' : ''}>${label}</button>`).join('')}</nav>`;
}
function bindFlow(root) {
  root.querySelectorAll('[data-flow]').forEach((b) => b.addEventListener('click', () => { step = flowStep(b.dataset.flow); render(true); }));
}
const kindTag = { package: '', addon: '<span class="tag">по вашим ответам</span>', manual: '<span class="tag">добавил врач</span>', option: '<span class="tag">по желанию</span>' };
function itemLine(i, forCurator = false) {
  const reasons = i.reasons.length ? `<small class="src">Почему: ${escapeHtml(i.reasons.join('; '))}</small>` : '';
  const free = i.free ? '<span class="tag">бесплатно в поликлинике прикрепления, до 60 дней — или в PRIME сегодня</span>'
    : i.part ? '<span class="tag">часть — бесплатно по скринингу</span>' : '';
  const validate = i.validate && !program.approved ? '<span class="tag warn">подтверждает врач</span>' : '';
  const emph = i.emphasis && !i.reasons.length ? '' : i.emphasis ? '<span class="tag warn">важно для вас</span>' : '';
  if (!forCurator) return `<li class="${i.included ? '' : 'muted'}">${escapeHtml(i.name)}${kindTag[i.kind] || ''}${free}${emph}${validate}${reasons}</li>`;
  return `<label class="cur-row"><input type="checkbox" data-item="${escapeHtml(i.key)}" ${i.included ? 'checked' : ''}><span><b>${escapeHtml(i.name)}</b>${kindTag[i.kind] || ''}${free}${emph}${validate}${reasons}</span></label>`;
}

/* ---------- 1. Программа (видит пациент) ---------- */
function renderProgram() {
  const r = compute(), a = answers, full = fullAge();
  currentProgram();
  const where = { green_clinic: 'в Green Clinic', other: 'в вашей поликлинике по прикреплению', unknown: 'в поликлинике по прикреплению — уточните его на egov.kz' }[a.attached_to] || 'в поликлинике по прикреплению';
  const who = a.for_child ? (a.sex === 'F' ? 'Девочка' : 'Мальчик') : (a.sex === 'F' ? 'Женщина' : 'Мужчина');
  const status = program.approved ? `<p class="review-notice ok-notice">Программу утвердил врач-куратор ${fmtDate(program.approved)}.</p>`
    : '<p class="review-notice">Это черновик программы по вашим ответам. Врач-куратор PRIME проверит и утвердит её на первом приёме.</p>';
  let h = flowNav('result') + `<p class="who-line">${who}, ${full} ${plural(full)}</p>` + status;
  if (!a.for_child) {
    h += `<section class="result-block free"><span class="result-label">Положено бесплатно</span>`;
    h += r.free.length ? `<h3>По госпрограмме ${where}, в течение 60 дней</h3><ul>` + r.free.map((s) =>
      `<li><b>${escapeHtml(plainName(s))}</b> — ${escapeHtml(plainWhat(s))}<small class="src">${escapeHtml(s.name)} · ${escapeHtml(s.source)}</small></li>`).join('') + '</ul>'
      : `<h3>В ${YEAR} году по возрасту бесплатный скрининг не положен</h3>`;
    if (r.notFree.length) h += '<ul>' + r.notFree.map((x) => `<li class="muted">${escapeHtml(plainName(x.s))}: ${escapeHtml(x.why)}</li>`).join('') + '</ul>';
    h += '</section>';
  }
  const pkgName = r.pkg ? (r.pkg.id === 'prime_child' ? r.pkg.name_mini : a.sex === 'F' ? r.pkg.name_f : r.pkg.name_m) : 'Пакет не подобран';
  const pkgItems = program.items.filter((i) => i.kind === 'package' || i.kind === 'option');
  const extra = program.items.filter((i) => i.kind === 'addon' || i.kind === 'manual');
  h += `<section class="result-block paid"><span class="result-label">Ваш пакет PRIME</span><h3>${escapeHtml(pkgName)}</h3><ul>${pkgItems.map((i) => itemLine(i)).join('')}</ul>` +
    '<small class="src">Состав — по сайту клиники, цена — по прайсу PRIME.</small></section>';
  if (extra.length) {
    h += `<section class="result-block extra"><span class="result-label">Добавлено под вас</span><h3>К пакету — по вашим ответам</h3><ul>${extra.map((i) => itemLine(i)).join('')}</ul>` +
      '<small class="src">Каждую добавку проверяет врач-куратор. Цена — по прайсу PRIME.</small></section>';
  }
  h += routeBlock();
  if (r.free.length) h += `<p class="next-visit"><b>Когда повторить бесплатно:</b> ${r.free.map((s) => `${escapeHtml(plainName(s))} — ${YEAR + s.repeat_years}`).join(' · ')}</p>`;
  h += `<div class="form-actions"><button id="to-review" class="back-button" type="button">← К ответам</button><button class="primary-button" type="button" data-flow="prep">Подготовка к чекапу <span aria-hidden="true">→</span></button></div>`;
  $('result').innerHTML = h;
  bindFlow($('result'));
  $('to-review').addEventListener('click', () => { step = reviewStep(); render(true); });
}

/* ---------- 2. Подготовка ---------- */
function renderPrep() {
  currentProgram();
  const list = prepItems();
  const done = list.filter((p) => program.prep[p.id]).length;
  let h = flowNav('prep');
  h += `<div class="field"><label for="checkup-date">Дата чекапа</label><div class="date-row"><input class="number-input" id="checkup-date" type="date" min="${today()}" value="${program.date}"></div></div>`;
  if (!list.length) h += '<p class="review-notice">Для этой программы особой подготовки нет. Детали уточните у врача при записи.</p>';
  else {
    h += `<div class="prep-progress"><span>Понятно и подтверждено</span><span>${done} из ${list.length}</span></div><div class="prep-bar"><span style="width:${list.length ? (done / list.length) * 100 : 0}%"></span></div>`;
    let lastDay = '';
    for (const p of list) {
      if (p.day !== lastDay) { h += `<h3 class="prep-day">${DAYS[p.day]}${p.day === 'now' ? '' : `, ${fmtDate(dayDate(p.day))}`}</h3>`; lastDay = p.day; }
      const ok = program.prep[p.id];
      const endo = p.id === 'pr_gastro' && routePlan().steps.find((s) => s.endoscopy);
      const personal = endo ? `<p class="prep-time">Ваше время по маршруту — ${endo.time}: воду можно пить до ${hhmm(endo.at - 120)}.</p>` : '';
      h += `<section class="prep-item ${ok ? 'ok' : ''} ${p.when_answer ? 'personal' : ''}"><h4>${escapeHtml(p.title)}</h4><p>${escapeHtml(p.text)}</p>${personal}` +
        (ok ? '<p class="prep-ok">✓ Понятно — пункт подтверждён</p>'
          : `<p class="prep-q">${escapeHtml(p.question)}</p><div class="choices">${p.options.map((o, idx) =>
            `<button type="button" class="choice" data-prep="${p.id}" data-idx="${idx}">${escapeHtml(o)}</button>`).join('')}</div><p class="prep-fb" id="fb-${p.id}" role="status"></p>`) +
        `<small class="src">${escapeHtml(p.source)}</small></section>`;
    }
    h += done === list.length ? '<p class="review-notice ok-notice">Готово: подготовка подтверждена. Врач-куратор видит, что вы всё поняли.</p>'
      : `<p class="review-notice">Осталось подтвердить ${list.length - done}. Врач-куратор увидит, что вы готовы.</p>`;
    h += `<div class="reminders"><b>Напомним:</b> ${reminders().filter((x) => x.kind === 'prep').map((x) => `<span class="tag">${fmtDate(x.date)} — ${escapeHtml(x.text)}</span>`).join(' ') || '—'}</div>`;
  }
  h += '<div class="form-actions"><button class="back-button" type="button" data-flow="result">← Программа</button><button class="primary-button" type="button" id="print-prep">Скачать памятку <span aria-hidden="true">↓</span></button></div>';
  $('result').innerHTML = h;
  bindFlow($('result'));
  $('checkup-date').addEventListener('change', (e) => { if (e.target.value) { program.date = e.target.value; saveProgram(); renderPrep(); } });
  $('print-prep').addEventListener('click', () => printSection('Памятка по подготовке'));
  $('result').querySelectorAll('[data-prep]').forEach((b) => b.addEventListener('click', () => {
    const p = rules.prep_catalog.find((x) => x.id === b.dataset.prep);
    if (Number(b.dataset.idx) === p.correct) { program.prep[p.id] = new Date().toISOString(); saveProgram(); renderPrep(); }
    else $(`fb-${p.id}`).textContent = 'Не совсем. Перечитайте пункт выше — от этого зависит, пройдёт ли обследование в этот день.';
  }));
}

/* ---------- 3. Куратор: утверждение программы и итоговый лист ---------- */
function renderCurator() {
  const r = compute();
  currentProgram();
  const a = answers, full = fullAge(), list = prepItems();
  const flags = [];
  if (r.pregnant) flags.push(['warn', `Беременность: ${label('pregnant', a.pregnant)}`]);
  if (a.blood_thinners === 'yes' || a.blood_thinners === 'unknown') flags.push(['warn', `Разжижающие кровь: ${label('blood_thinners', a.blood_thinners)}`]);
  if (a.anesthesia_reaction === 'yes') flags.push(['warn', 'Были реакции на наркоз']);
  if (a.allergy === 'yes' || a.allergy === 'unknown') flags.push(['warn', `Аллергия на лекарства или контраст: ${label('allergy', a.allergy)}`]);
  if (a.companion === 'no') flags.push(['warn', 'Некому проводить после наркоза']);
  const prepDone = list.filter((p) => program.prep[p.id]).length;
  flags.push([prepDone === list.length ? 'ok' : '', `Подготовка: подтверждено ${prepDone} из ${list.length}`]);
  const feedback = store.get(CARD_KEY, []).find((x) => x.date === program.date)?.feedback;
  if (feedback) flags.push([feedback.score >= 4 ? 'ok' : 'warn', `Оценка пациента: ${feedback.score} из 5${feedback.text ? ` — «${feedback.text}»` : ''}`]);
  let h = flowNav('curator') + `<p class="who-line">Экран врача-куратора · ${a.sex === 'F' ? 'Ж' : 'М'}, ${full} ${plural(full)}</p>`;
  h += `<div class="flag-row">${flags.map(([cls, t]) => `<span class="tag ${cls === 'warn' ? 'warn' : ''} ${cls === 'ok' ? 'good' : ''}">${escapeHtml(t)}</span>`).join('')}</div>`;
  h += `<section class="result-block doctor"><span class="result-label">Со слов пациента</span><ul>${r.doctor.map((d) => `<li>${escapeHtml(d)}</li>`).join('') || '<li class="muted">Ничего не отмечено</li>'}</ul></section>`;
  if (!a.for_child) {
    h += `<section class="result-block free"><span class="result-label">Госскрининг ${YEAR}</span><ul>` +
      (r.free.map((s) => `<li>${escapeHtml(s.name)} <small class="src">${escapeHtml(s.source)}</small></li>`).join('') || '<li class="muted">По возрасту в этом году не положен</li>') +
      r.notFree.map((x) => `<li class="muted">${escapeHtml(x.s.name)}: ${escapeHtml(x.why)}</li>`).join('') + '</ul></section>';
  }
  h += `<section class="result-block paid"><span class="result-label">Программа — отметьте, что оставить</span>${program.items.map((i) => itemLine(i, true)).join('')}` +
    `<div class="add-row"><select id="add-service" class="number-input"><option value="">Добавить услугу PRIME…</option>${rules.prime_catalog.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('')}</select>` +
    '<button type="button" class="secondary-button" id="add-btn">Добавить</button></div>' +
    `<small class="src">В программе: ${included().length} · добавки из таблицы анамнеза — черновик, утверждает медэксперт</small></section>`;
  h += routeBlock();
  h += program.approved ? `<p class="review-notice ok-notice">Программа утверждена ${fmtDate(program.approved)}. Пациент видит её и подготовку.</p>`
    : '<div class="form-actions"><button class="primary-button" type="button" id="approve">Утвердить программу <span aria-hidden="true">✓</span></button></div>';
  if (program.approved) h += renderSheetForm();
  $('result').innerHTML = h;
  bindFlow($('result'));
  $('result').querySelectorAll('[data-item]').forEach((cb) => cb.addEventListener('change', () => {
    program.items.find((i) => i.key === cb.dataset.item).included = cb.checked;
    saveProgram();
  }));
  $('add-btn').addEventListener('click', () => {
    const id = $('add-service').value;
    if (!id) return;
    const c = rules.prime_catalog.find((x) => x.id === id);
    const existing = program.items.find((i) => i.key === `a:${id}` || i.key === `m:${id}`);
    if (existing) existing.included = true;
    else program.items.push({ key: `m:${id}`, name: c.name, kind: 'manual', included: true, reasons: ['по решению врача-куратора'], url: c.url });
    saveProgram(); renderCurator();
  });
  $('approve')?.addEventListener('click', () => { program.approved = new Date().toISOString(); saveProgram(); renderCurator(); });
  bindSheetForm();
}
const RESULT_OPTIONS = [['', 'не внесено'], ['norm', 'норма'], ['dev', 'отклонение'], ['not_done', 'не проведено']];
function renderSheetForm() {
  const specialists = rules.prime_catalog.filter((c) => c.id.startsWith('c_'));
  const c = program.conclusion;
  return `<section class="result-block route"><span class="result-label">Итоговый лист — после обследований</span><h3>Результаты</h3>` +
    included().map((i) => `<div class="sheet-row"><span>${escapeHtml(i.name)}</span><select data-res="${escapeHtml(i.key)}">${RESULT_OPTIONS.map(([v, t]) =>
      `<option value="${v}" ${program.results[i.key] === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>`).join('') +
    `<h3>Заключение</h3><div class="choices stack">
      <label class="choice"><input type="radio" name="outcome" value="ok" ${c.outcome === 'ok' ? 'checked' : ''}><span>Всё в порядке — следующий чекап через год</span></label>
      <label class="choice"><input type="radio" name="outcome" value="refer" ${c.outcome === 'refer' ? 'checked' : ''}><span>Направить к профильному специалисту</span></label></div>
    <select id="specialist" class="number-input" ${c.outcome === 'refer' ? '' : 'hidden'}><option value="">Выберите специалиста…</option>${specialists.map((s) =>
      `<option value="${s.id}" ${c.specialist === s.id ? 'selected' : ''}>${escapeHtml(s.name)}</option>`).join('')}</select>
    <label for="sheet-note" class="sheet-label">Рекомендации врача</label><textarea id="sheet-note" class="number-input text-area" rows="3">${escapeHtml(c.note)}</textarea>
    <div class="form-actions"><button class="primary-button" type="button" id="make-sheet">Сформировать итоговый лист <span aria-hidden="true">→</span></button></div></section>`;
}
function bindSheetForm() {
  if (!program.approved) return;
  $('result').querySelectorAll('[data-res]').forEach((s) => s.addEventListener('change', () => { program.results[s.dataset.res] = s.value; saveProgram(); }));
  $('result').querySelectorAll('input[name=outcome]').forEach((r) => r.addEventListener('change', () => {
    program.conclusion.outcome = r.value; $('specialist').hidden = r.value !== 'refer'; saveProgram();
  }));
  $('specialist').addEventListener('change', (e) => { program.conclusion.specialist = e.target.value; saveProgram(); });
  $('sheet-note').addEventListener('input', (e) => { program.conclusion.note = e.target.value; saveProgram(); });
  $('make-sheet').addEventListener('click', () => {
    if (program.conclusion.outcome === 'refer' && !program.conclusion.specialist) { $('specialist').focus(); return; }
    program.sheetAt = new Date().toISOString(); saveProgram();
    const card = store.get(CARD_KEY, []).filter((x) => x.date !== program.date);
    card.push({ date: program.date, items: included().map((i) => ({ name: i.name, result: program.results[i.key] || '' })), conclusion: { ...program.conclusion } });
    store.set(CARD_KEY, card.sort((x, y) => y.date.localeCompare(x.date)));
    step = flowStep('card'); render(true);
  });
}

/* ---------- 4. Карта здоровья и напоминания ---------- */
function reminders() {
  const out = [];
  if (!program) return out;
  for (const p of prepItems()) {
    if (p.day === 'now') out.push({ kind: 'prep', date: dayDate('now'), text: p.id === 'pr_thinners' ? 'позвонить врачу-куратору о препаратах' : p.title });
    if (p.day === 'eve') out.push({ kind: 'prep', date: dayDate('eve'), time: '18:00', text: p.title });
    if (p.day === 'morning' && !out.some((x) => x.date === program.date && x.kind === 'prep')) out.push({ kind: 'prep', date: program.date, time: '06:00', text: 'натощак, без еды; воду — по памятке' });
  }
  const c = program.conclusion;
  if (program.sheetAt && c.outcome === 'refer' && c.specialist) {
    out.push({ kind: 'follow', date: addDays(program.date, 7), text: `записаться: ${rules.prime_catalog.find((x) => x.id === c.specialist)?.name || 'к специалисту'}` });
  }
  out.push({ kind: 'repeat', date: addDays(program.date, 365), text: 'следующий чекап PRIME' });
  if (!answers.for_child) compute().free.forEach((s) => out.push({ kind: 'repeat', date: `${YEAR + s.repeat_years}-01-15`, text: `бесплатный скрининг: ${plainName(s).charAt(0).toLowerCase()}${plainName(s).slice(1)}` }));
  return out.sort((x, y) => x.date.localeCompare(y.date));
}
function icsFile() {
  const stamp = (d, t) => d.replaceAll('-', '') + 'T' + (t || '09:00').replace(':', '') + '00';
  const events = reminders().map((x, i) => ['BEGIN:VEVENT', `UID:gc-${i}-${x.date}@checkup`, `DTSTAMP:${stamp(today())}`, `DTSTART:${stamp(x.date, x.time)}`,
    `SUMMARY:PRIME: ${x.text}`, 'END:VEVENT'].join('\r\n'));
  return ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Qorgan//Check-up//RU', ...events, 'END:VCALENDAR'].join('\r\n');
}
const RESULT_TEXT = { norm: 'норма', dev: 'отклонение — обсудить с врачом', not_done: 'не проведено', '': 'результат ещё не внесён' };
function renderCard() {
  currentProgram();
  const card = store.get(CARD_KEY, []);
  let h = flowNav('card');
  if (!card.length) {
    h += '<p class="review-notice">Карта здоровья появится после чекапа: врач-куратор внесёт результаты и заключение в итоговый лист.</p>';
  } else {
    const last = card[0], c = last.conclusion;
    const spec = rules.prime_catalog.find((x) => x.id === c.specialist)?.name;
    h += `<section class="result-block paid"><span class="result-label">Чекап ${fmtDate(last.date)}</span><h3>Заключение</h3>` +
      `<p class="card-conc">${c.outcome === 'refer' ? `Нужна консультация <b>${escapeHtml(spec ? spec.replace(/^Консультация /, '') : 'профильного специалиста')}</b>` : 'Всё в порядке — следующий чекап через год.'}</p>` +
      (c.note ? `<p class="card-note">${escapeHtml(c.note)}</p>` : '') +
      `<ul>${last.items.map((i) => `<li class="${i.result === 'dev' ? 'dev' : ''}">${escapeHtml(i.name)} — ${RESULT_TEXT[i.result]}</li>`).join('')}</ul></section>`;
    const fb = last.feedback;
    h += `<section class="result-block extra"><span class="result-label">Ваша оценка</span>` + (fb
      ? `<p class="card-note">Спасибо! Оценка ${fb.score} из 5${fb.text ? ` — «${escapeHtml(fb.text)}»` : ''}. Её видит клиника.</p>`
      : `<h3>Как прошёл чекап?</h3><div class="rating" role="group" aria-label="Оценка от 1 до 5">${[1, 2, 3, 4, 5].map((n) =>
        `<button type="button" class="choice" data-score="${n}" aria-pressed="false">${n}</button>`).join('')}</div>` +
        '<label for="fb-text" class="sheet-label">Что улучшить? Необязательно</label><textarea id="fb-text" class="number-input text-area" rows="2" maxlength="500"></textarea>' +
        '<p class="prep-fb" id="fb-msg" role="status"></p><div class="form-actions"><button class="primary-button" type="button" id="fb-send">Отправить оценку</button></div>') + '</section>';
    if (card.length > 1) h += `<section class="result-block prep"><span class="result-label">История</span><ul>${card.slice(1).map((x) => `<li>Чекап ${fmtDate(x.date)} ${new Date(x.date).getFullYear()}</li>`).join('')}</ul></section>`;
  }
  h += `<section class="result-block route"><span class="result-label">Напоминания</span><ul>${reminders().map((x) =>
    `<li><b>${fmtDate(x.date)} ${new Date(x.date).getFullYear()}${x.time ? `, ${x.time}` : ''}</b> — ${escapeHtml(x.text)}</li>`).join('')}</ul>` +
    '<small class="src">Напоминания уйдут в WhatsApp или SMS после подключения клиники; сейчас их можно добавить в календарь.</small></section>';
  h += '<div class="form-actions"><button class="back-button" type="button" data-flow="result">← Программа</button><button class="primary-button" type="button" id="to-calendar">Добавить в календарь <span aria-hidden="true">↓</span></button></div>';
  $('result').innerHTML = h;
  bindFlow($('result'));
  let score = 0;
  $('result').querySelectorAll('[data-score]').forEach((b) => b.addEventListener('click', () => {
    score = Number(b.dataset.score);
    $('result').querySelectorAll('[data-score]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    $('fb-msg').textContent = '';
  }));
  $('fb-send')?.addEventListener('click', () => {
    if (!score) { $('fb-msg').textContent = 'Выберите оценку от 1 до 5.'; return; }
    const all = store.get(CARD_KEY, []);
    all[0].feedback = { score, text: $('fb-text').value.trim(), at: new Date().toISOString() };
    store.set(CARD_KEY, all);
    renderCard();
  });
  $('to-calendar').addEventListener('click', () => {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([icsFile()], { type: 'text/calendar' }));
    link.download = 'prime_checkup_reminders.ics';
    link.click();
    URL.revokeObjectURL(link.href);
  });
}
function printSection(title) {
  document.title = `${title} — Green Clinic`;
  window.print();
}
