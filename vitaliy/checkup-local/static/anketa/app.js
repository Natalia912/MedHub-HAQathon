const $ = (id) => document.getElementById(id);
const form = $('patient-form');
let fields = [];
let steps = [];
let rules = null;
let answers = {};
let step = 0;
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const YEAR = new Date().getFullYear();
const today = () => new Date().toISOString().slice(0, 10);
const pad = (n) => String(n).padStart(2, '0');
const reviewStep = () => steps.length;
const resultStep = () => steps.length + 1;
// После анкеты — пять разделов (flow.js): программа, подготовка, куратор, утро клиники, карта здоровья
const FLOW = ['result', 'prep', 'curator', 'morning', 'card'];
const flowStep = (id) => resultStep() + FLOW.indexOf(id);
const inFlow = () => step >= resultStep();

/* ---------- возраст ---------- */
function birthYear() {
  const y = Number(String(answers.birth_date || '').slice(0, 4));
  return y > 1900 && y <= YEAR ? y : null;
}
// Полных лет — для выбора пакета клиники и показа вопросов
function fullAge() {
  if (!answers.birth_date) return null;
  const b = new Date(answers.birth_date), n = new Date();
  if (Number.isNaN(b.getTime()) || b > n) return null;
  return n.getFullYear() - b.getFullYear() - (n < new Date(n.getFullYear(), b.getMonth(), b.getDate()) ? 1 : 0);
}
// Возраст по году — так считает приказ о скрининге (ДСМ-174/2020)
const ageYear = () => (birthYear() ? YEAR - birthYear() : null);
function plural(n) {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? 'год' : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? 'года' : 'лет';
}

/* ---------- видимость вопросов ---------- */
function check([name, op, value]) {
  const v = answers[name];
  if (op === 'eq') return v === value;
  if (op === 'ne') return v !== value;
  if (op === 'in') return value.includes(v);
  if (op === 'gt') return Number(v) > value;
  if (op === 'has_any') return (v || []).some((x) => value.includes(x));
  if (op === 'lacks') return !(v || []).includes(value);
  console.warn('Неизвестное условие show_if:', op);
  return true;
}
function visible(field) {
  const c = field.show_if;
  if (!c) return true;
  const age = fullAge();
  if (c.sex && answers.sex !== c.sex) return false;
  if (c.adult && answers.for_child) return false;
  if ('age_min' in c && (age === null || age < c.age_min)) return false;
  if ('age_max' in c && (age === null || age > c.age_max)) return false;
  return (c.when || []).every(check);
}
function options(field) {
  return field.options.filter(([value, , sex]) => (!sex || sex === answers.sex) &&
    (!field.options_from || (answers[field.options_from] || []).includes(value)));
}
const isUrgent = () => fields.some((f) => f.stop && answers[f.name] && answers[f.name] !== 'none');
const stepTitle = (s, key) => (answers.sex === 'M' && s[`${key}_m`]) || s[key];

function defaults() {
  answers = {};
  for (const field of fields) if ('default' in field) answers[field.name] = field.default;
}
async function loadFields() {
  $('load-error').hidden = true;
  $('retry').hidden = true;
  try {
    const [f, s, r] = await Promise.all(['/fields', '/steps', '/rules'].map(async (url) => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`${url} недоступен: ${response.status}`);
      return response.json();
    }));
    if (!Array.isArray(f) || !f.length || !Array.isArray(s) || !s.length || !r.packages) throw new Error('invalid schema');
    [fields, steps, rules] = [f, s, r];
    defaults();
    render();
  } catch (error) {
    console.error('Анкета не загрузилась:', error);
    $('fields').replaceChildren();
    $('next').disabled = true;
    $('load-error').textContent = 'Не удалось загрузить анкету. Проверьте подключение к приложению и попробуйте снова.';
    $('load-error').hidden = false;
    $('retry').hidden = false;
  }
}

/* ---------- поля ---------- */
function renderField(field) {
  const id = field.name.replaceAll('.', '-');
  const value = answers[field.name];
  const hint = field.hint || '';
  const title = escapeHtml(field.label) + (field.required ? ' <span class="required" aria-hidden="true">*</span>' : '');
  const description = hint ? ` aria-describedby="${id}-hint"` : '';
  const req = field.required ? 'required' : '';
  let input;
  if (field.type === 'number') {
    input = `<label for="${id}">${title}</label><input class="number-input" id="${id}" name="${field.name}" type="number" inputmode="numeric" step="1" min="${field.min ?? 0}" max="${field.max ?? ''}" ${req} value="${escapeHtml(value ?? '')}" placeholder="${escapeHtml(field.placeholder || '')}"${description}>`;
  } else if (field.type === 'date') {
    const age = field.name === 'birth_date' && fullAge() !== null ? `<span class="age-note">${fullAge()} ${plural(fullAge())}</span>` : '';
    input = `<label for="${id}">${title}</label><div class="date-row"><input class="number-input" id="${id}" name="${field.name}" type="date" max="${today()}" min="1900-01-01" ${req} value="${escapeHtml(value ?? '')}"${description}>${age}</div>`;
  } else if (field.type === 'text') {
    input = `<label for="${id}">${title}</label><input class="number-input" id="${id}" name="${field.name}" type="text" maxlength="300" ${req} value="${escapeHtml(value ?? '')}"${description}>`;
  } else if (field.type === 'textarea') {
    input = `<label for="${id}">${title}</label><textarea class="number-input text-area" id="${id}" name="${field.name}" maxlength="1000" rows="3" ${req}${description}>${escapeHtml(value ?? '')}</textarea>`;
  } else {
    input = `<legend>${title}</legend><div class="choices ${field.layout === 'stack' ? 'stack' : ''}">` + options(field).map(([option, label], index) => {
      const checked = field.type === 'multiselect' ? (value || []).includes(option) : value === option;
      return `<label class="choice"><input type="${field.type === 'multiselect' ? 'checkbox' : 'radio'}" id="${id}-${index}" name="${field.name}" value="${escapeHtml(option)}" ${checked ? 'checked' : ''} ${field.type === 'multiselect' ? '' : req}${description}><span>${escapeHtml(label)}</span></label>`;
    }).join('') + '</div>';
  }
  const tag = ['select', 'boolean', 'multiselect'].includes(field.type) ? 'fieldset' : 'div';
  return `<${tag} class="field" data-name="${field.name}">${input}${hint ? `<p class="hint" id="${id}-hint">${escapeHtml(hint)}</p>` : ''}</${tag}>`;
}
function renderNav() {
  $('steps-nav').innerHTML = steps.map((s, index) =>
    `<li data-step="${index}"><span class="step-number">${pad(index + 1)}</span><div><strong>${escapeHtml(stepTitle(s, 'nav'))}</strong><small>${escapeHtml(stepTitle(s, 'nav_hint'))}</small></div></li>`).join('');
  document.querySelectorAll('.steps li').forEach((item, index) => {
    item.classList.toggle('completed', index < step);
    if (index === step) item.setAttribute('aria-current', 'step');
    else item.removeAttribute('aria-current');
  });
}
// Шаг без единого видимого вопроса (например, мужское здоровье для ребёнка) пропускаем
const hasQuestions = (index) => fields.some((f) => f.step === index && visible(f));
function render(focus = false) {
  const total = steps.length;
  const FLOW_TITLES = {
    result: ['Ваша программа обследования', 'Пакет PRIME и добавки по вашим ответам. Итог утверждает врач-куратор.'],
    prep: ['Подготовка к чекапу', 'Что можно и что нельзя — по дням. Под каждым пунктом один вопрос: так мы убедимся, что всё понятно.'],
    curator: ['Экран врача-куратора', 'Анкета, флаги, программа с причинами. Уберите или добавьте услуги, утвердите, после обследований — итоговый лист.'],
    morning: ['Утро клиники: карусель кабинетов', 'Все пациенты приходят утром. Каждый идёт в свободный кабинет своей программы — без очереди в один кабинет. Опоздание пересчитывает всех.'],
    card: ['Карта здоровья', 'Результаты чекапа, заключение врача и напоминания о следующих шагах.'],
  };
  const title = inFlow() ? FLOW_TITLES[FLOW[step - resultStep()]]
    : step === reviewStep() ? ['Проверьте ваши ответы', 'Всё готово. Вы можете вернуться к любому разделу и изменить ответы.']
      : [stepTitle(steps[step], 'title'), steps[step].description];
  $('step-title').textContent = title[0];
  $('step-description').textContent = title[1];
  $('step-counter').textContent = inFlow() ? 'ПРОГРАММА' : step === reviewStep() ? 'ПРОВЕРКА ОТВЕТОВ' : `ШАГ ${pad(step + 1)} / ${pad(total)}`;
  $('progress-fill').style.width = `${step >= reviewStep() ? 100 : ((step + 1) / total) * 100}%`;
  const track = document.querySelector('.progress-track');
  track.setAttribute('aria-valuemax', total);
  track.setAttribute('aria-valuenow', Math.min(step + 1, total));
  renderNav();
  form.hidden = step >= reviewStep();
  $('review').hidden = step !== reviewStep();
  $('result').hidden = !inFlow();
  if (step === reviewStep()) renderReview();
  else if (inFlow()) ({ result: renderProgram, prep: renderPrep, curator: renderCurator, morning: renderMorning, card: renderCard })[FLOW[step - resultStep()]]();
  else {
    $('fields').innerHTML = fields.filter((field) => field.step === step && visible(field)).map(renderField).join('');
    $('back').hidden = step === 0;
    $('skip').hidden = !steps[step].optional;
    $('next').innerHTML = (step === total - 1 ? 'Проверить ответы' : 'Продолжить') + ' <span aria-hidden="true">→</span>';
    updateSafety();
  }
  if (focus) $('step-title').focus();
}
function updateSafety() {
  const urgent = isUrgent();
  $('urgent-alert').hidden = !urgent;
  $('back').hidden = step === 0 || urgent;
  $('next').disabled = urgent;
  $('next').hidden = urgent;
  $('skip').hidden = !steps[step]?.optional || urgent;
  // Вопрос-триггер остаётся доступным для правки, всё после него — скрыто
  let afterTrigger = false;
  for (const wrapper of $('fields').querySelectorAll('.field')) {
    wrapper.hidden = urgent && afterTrigger;
    wrapper.querySelectorAll('input, textarea').forEach((input) => { input.disabled = wrapper.hidden; });
    if (fields.find((f) => f.name === wrapper.dataset.name)?.stop) afterTrigger = true;
  }
}
form.addEventListener('input', (event) => {
  const input = event.target;
  const field = fields.find((f) => f.name === input.name);
  if (!field) return;
  const before = fields.filter(visible).map((f) => f.name).join() + JSON.stringify(fields.filter((f) => f.options_from).map((f) => answers[f.options_from]));
  if (field.type === 'multiselect') {
    let picked = Array.from(form.elements).filter((el) => el.name === field.name && el.checked).map((el) => el.value);
    if (field.exclusive && picked.includes(field.exclusive) && picked.length > 1) {
      picked = input.value === field.exclusive ? [field.exclusive] : picked.filter((v) => v !== field.exclusive);
    }
    answers[field.name] = picked;
  } else if (input.value === '') delete answers[field.name];
  else answers[field.name] = field.type === 'number' ? Number(input.value) : field.type === 'boolean' ? input.value === 'true' : input.value;
  // Ответы на вопросы, которые больше не показываются, — убираем
  for (const candidate of fields) if (!visible(candidate)) delete answers[candidate.name];
  for (const f of fields.filter((x) => x.options_from && Array.isArray(answers[x.name]))) {
    answers[f.name] = answers[f.name].filter((v) => (answers[f.options_from] || []).includes(v));
  }
  const birth = $('birth_date');
  if (birth) birth.setCustomValidity(answers.birth_date && fullAge() === null ? 'Проверьте дату рождения: она не может быть в будущем.' : '');
  const after = fields.filter(visible).map((f) => f.name).join() + JSON.stringify(fields.filter((f) => f.options_from).map((f) => answers[f.options_from]));
  // Состав вопросов на шаге поменялся (или отметились «ничего»/варианты) — перерисовать, сохранив фокус
  if (before !== after || field.exclusive || field.name === 'birth_date') {
    const focusId = document.activeElement?.id;
    $('fields').innerHTML = fields.filter((f) => f.step === step && visible(f)).map(renderField).join('');
    if (focusId) $(focusId)?.focus();
    renderNav();
  }
  updateSafety();
});
function go(delta) {
  let next = step + delta;
  while (next > 0 && next < steps.length && !hasQuestions(next)) next += delta;
  step = Math.max(0, next);
  render(true);
}
form.addEventListener('submit', (event) => {
  event.preventDefault();
  if (isUrgent() || !form.reportValidity()) return;
  go(1);
});
$('back').addEventListener('click', () => go(-1));
$('skip').addEventListener('click', () => {
  if (isUrgent()) return;
  fields.filter((field) => field.step === step).forEach((field) => { delete answers[field.name]; });
  go(1);
});
$('retry').addEventListener('click', loadFields);

/* ---------- вход для движка (spec/CONTRACT.md) ---------- */
function packYears() {
  if (!['smokes', 'quit'].includes(answers.smoke_status)) return 0;
  return (Number(answers.cigs_per_day) || 0) / 20 * (Number(answers.smoke_years) || 0);
}
const quitYears = () => (answers.smoke_status === 'quit' ? Number(answers.quit_years_ago) || 0 : 0);
function collectInput() {
  const payload = {};
  for (const field of fields.filter(visible)) {
    let value = answers[field.name];
    if (value === undefined || value === '' || (Array.isArray(value) && !value.length)) continue;
    if (field.exclusive && Array.isArray(value)) value = value.filter((v) => v !== field.exclusive);
    if (field.maps_to) value = value.map((v) => field.maps_to[v]).filter(Boolean);
    if (Array.isArray(value) && !value.length) continue;
    payload[field.contract || field.name] = value;
  }
  payload.birth_year = birthYear();
  payload.checkup_year = YEAR;
  if (payload.last_screening) payload.last_screening = Object.fromEntries(payload.last_screening.map((s) => [s, YEAR - 1]));
  if (answers.smoke_status) payload.smoking = { pack_years: Math.round(packYears() * 10) / 10, quit_years_ago: quitYears() };
  if (answers.hazardous_work_10y) payload.hazardous_work_10y = answers.hazardous_work_10y === 'yes';
  return payload;
}
function displayValue(field) {
  const value = answers[field.name];
  if (value === undefined || value === '' || (Array.isArray(value) && !value.length)) return 'Не указано';
  if (field.type === 'date') return new Date(value).toLocaleDateString('ru-RU');
  if (field.options) return field.options.filter(([option]) => Array.isArray(value) ? value.includes(option) : value === option).map(([, label]) => label).join('; ');
  return String(value);
}
function renderReview() {
  $('review').innerHTML = steps.map((s, index) => {
    const shown = fields.filter((field) => field.step === index && visible(field));
    if (!shown.length) return '';
    const t = stepTitle(s, 'title');
    return `<section class="review-section"><h3>${escapeHtml(t)}<button class="edit-button" type="button" data-edit="${index}" aria-label="Изменить раздел: ${escapeHtml(t)}">Изменить</button></h3><dl>` +
      shown.map((field) => `<dt>${escapeHtml(field.label)}</dt><dd>${escapeHtml(displayValue(field))}</dd>`).join('') + '</dl></section>';
  }).join('') + '<div class="form-actions"><button id="show-result" class="primary-button" type="button">Показать программу <span aria-hidden="true">→</span></button></div>' +
    '<button id="restart" class="secondary-button" type="button">Заполнить заново</button>';
  $('review').querySelectorAll('[data-edit]').forEach((button) => button.addEventListener('click', () => {
    step = Number(button.dataset.edit);
    render(true);
  }));
  $('show-result').addEventListener('click', () => {
    // Ответы → движок: дальше программа, согласие, подготовка, куратор, утро клиники, карта здоровья
    try { sessionStorage.setItem('checkup_input', JSON.stringify({ ...collectInput(), birth_date: answers.birth_date, consent_data: answers.consent_data })); }
    catch (e) { console.error('Не сохранить ответы для программы', e); }
    location.href = '/app';
  });
  $('restart').addEventListener('click', () => { defaults(); step = 0; render(true); });
}

/* ---------- подбор программы: правила spec/rules.json ---------- */
// Названия скринингов простыми словами; медицинское название и пункт приказа — мелко, для врача
const PLAIN = {
  scr_cvd: ['Давление, сердце, сахар, глаза', 'анализы крови на холестерин и сахар, измерение давления в глазу'],
  scr_cerebro: ['Сосуды шеи и головы', 'УЗИ сосудов шеи'],
  scr_breast: ['Молочная железа', 'маммография'],
  scr_cervix: ['Шейка матки', 'мазок на онкоцитологию или ВПЧ'],
  scr_colorectal: ['Кишечник', 'анализ кала на скрытую кровь'],
  scr_hepatitis: ['Гепатиты B и C', 'анализ крови'],
  scr_lung: ['Лёгкие', 'КТ лёгких'],
};
const plainName = (s) => (PLAIN[s.id] || [s.name])[0];
const plainWhat = (s) => (PLAIN[s.id] || [null, s.stage1.filter((x) => !/^Приём/.test(x)).join(', ')])[1];
const label = (name, value) => fields.find((f) => f.name === name)?.options?.find(([v]) => v === value)?.[1];

function compute() {
  const a = answers, input = collectInput();
  const age = ageYear(), full = fullAge();
  const out = { free: [], notFree: [], pkg: null, pkgExams: [], doctor: [], pregnant: false };
  out.pregnant = a.sex === 'F' && ['yes', 'unsure'].includes(a.pregnant);
  const reg = input.registered || [], last = Object.keys(input.last_screening || {});
  if (!a.for_child && age !== null) for (const s of rules.screening) {
    const w = s.when;
    if (w.sex && !w.sex.includes(a.sex)) continue;
    if (w.age_year && !w.age_year.includes(age)) continue;
    if (w.age_min != null && age < w.age_min) continue;
    if (!w.age_year && w.age_min == null) continue; // только по группе риска — вопроса в анкете нет
    if (w.not_pregnant && out.pregnant) { out.notFree.push({ s, why: 'при беременности — по отдельному порядку, обсудите с врачом' }); continue; }
    if (w.any_of && !w.any_of.some((c) => (c.pack_years_min != null && packYears() >= c.pack_years_min && quitYears() <= c.quit_years_max) ||
      (c.hazardous_work_10y && a.hazardous_work_10y === 'yes'))) continue;
    if ((w.not_registered || []).some((r) => reg.includes(r))) { out.notFree.push({ s, why: 'вы стоите на учёте — это обследование ведёт ваш врач' }); continue; }
    if (last.includes(s.id) && s.repeat_years >= 2) { out.notFree.push({ s, why: 'проходили в последние 2 года — повтор бесплатно пока не положен' }); continue; }
    out.free.push(s);
  }
  // Пакет клиники — по полным годам: ребёнок 1–17, базовый до 40, расширенный после 40
  const child = a.for_child || (full !== null && full < 18);
  out.pkg = rules.packages.find((p) => (child ? p.id === 'prime_child' : p.id !== 'prime_child' && full >= p.when.age_min && full <= p.when.age_max)) || null;
  if (out.pkg && out.pkg.id !== 'prime_child') {
    const overlap = new Set(out.free.flatMap((s) => s.prime_overlap || []));
    const freeNames = out.free.flatMap((s) => s.stage1.map((n) => n.toLowerCase()));
    const fully = (e) => freeNames.some((n) => n.startsWith(e.split('(')[0].trim().toLowerCase()));
    const list = [...out.pkg.exams, ...(a.sex === 'F' ? out.pkg.female_exams || [] : out.pkg.male_exams || [])];
    const flagged = new Map();
    for (const c of rules.complaints) {
      if (c.action === 'red_flag' || !c.when.family_history || !(a.family_history || []).includes(c.when.family_history)) continue;
      for (const e of c.exams || []) flagged.set(e, c);
    }
    out.pkgExams = list.map((e) => ({ exam: e, free: overlap.has(e) && fully(e), part: overlap.has(e) && !fully(e),
      preg: out.pregnant && /КТ|Маммограф|рентген/i.test(e), family: [...flagged.keys()].some((k) => e.toLowerCase().includes(k.split(' ')[0].toLowerCase())) }));
  }
  // Врачу — всё, что пациент рассказал о себе
  const shown = (name) => { const f = fields.find((x) => x.name === name); return f && visible(f) && a[name] !== undefined && a[name] !== ''; };
  const list = (name) => (a[name] || []).filter((v) => v !== 'none').map((v) => label(name, v)).filter(Boolean);
  if (list('conditions').length) out.doctor.push(`Есть или было: ${list('conditions').join('; ')}`);
  if (shown('conditions_other')) out.doctor.push(`Другое: ${a.conditions_other}`);
  if (list('registered_on').length) out.doctor.push(`На учёте: ${list('registered_on').join('; ')}`);
  if (list('family_history').length) out.doctor.push(`В семье: ${list('family_history').join('; ')}`);
  if ((a.family_history || []).includes('colorectal_cancer')) out.doctor.push('Рак кишечника в семье — обсудить колоноскопию раньше обычного возраста');
  if (shown('last_period')) out.doctor.push(`Последние месячные: ${new Date(a.last_period).toLocaleDateString('ru-RU')}`);
  if (out.pregnant) out.doctor.push(`Беременность: ${label('pregnant', a.pregnant)}`);
  if (shown('pregnancies')) out.doctor.push(`Беременностей: ${a.pregnancies}${shown('births') ? `, родов: ${a.births}` : ''}`);
  if (shown('contraception')) out.doctor.push(`Предохранение: ${label('contraception', a.contraception)}`);
  if (a.smoke_status && a.smoke_status !== 'never') out.doctor.push(`Курение: ${label('smoke_status', a.smoke_status)}${packYears() ? `, ≈ ${Math.round(packYears())} пачка-лет` : ''}`);
  if (a.anesthesia_reaction === 'yes') out.doctor.push('Были плохие реакции на наркоз');
  if (['yes', 'unknown'].includes(a.blood_thinners)) out.doctor.push(`Препараты, разжижающие кровь: ${label('blood_thinners', a.blood_thinners)}`);
  if (['yes', 'unknown'].includes(a.allergy)) out.doctor.push(`Аллергия на лекарства или контраст: ${label('allergy', a.allergy)}`);
  if (shown('medications') && String(a.medications).trim()) out.doctor.push(`Принимает сейчас: ${String(a.medications).trim()}`);
  return out;
}

loadFields();
