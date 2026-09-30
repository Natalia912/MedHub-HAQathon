"""Анкета пациента: шаги и вопросы. Форма строится из этого файла — добавлять вопросы здесь.

Поле: name (ключ во входе predict, см. spec/CONTRACT.md), label, type, step (с нуля).
Типы: number, date, text, textarea, select, boolean, multiselect.
Варианты: [значение, подпись] или [значение, подпись, "F"/"M"] — вариант только для этого пола.
show_if — когда показывать вопрос:
  sex: "F"/"M";  age_min / age_max — полных лет (по дате рождения);  adult: true — не для ребёнка;
  when: [[поле, оп, значение], ...] — все условия сразу;
        оп: eq, ne, in, gt, has_any (в списке есть одно из), lacks (в списке нет значения).
options_from: "поле" — показывать только те варианты, что отмечены в этом поле.
exclusive: "none" — этот вариант снимает остальные отметки (и наоборот).
stop: true — любой ответ, кроме "none", останавливает анкету (красный экран «звоните 103»).
"""

STEPS = [
    {"title": "Давайте познакомимся", "nav": "О вас", "nav_hint": "Основная информация",
     "description": "Начнём с основного. Это поможет учесть возраст и пол при подборе обследований."},
    {"title": "Как вы себя чувствуете?", "nav": "Самочувствие", "nav_hint": "Что важно учесть сейчас",
     "description": "Сначала — самое важное. Если заполняете анкету для ребёнка, отвечайте о его самочувствии."},
    {"title": "Женское здоровье", "title_m": "Мужское здоровье", "nav": "Женское здоровье", "nav_m": "Мужское здоровье",
     "nav_hint": "Беременность, роды, жалобы", "nav_hint_m": "Мочеиспускание, выделения",
     "description": "Эти ответы увидит только врач. Они помогают подобрать обследования и подготовку."},
    {"title": "Ваша история здоровья", "nav": "История здоровья", "nav_hint": "Болезни и обследования",
     "description": "Отметьте, что у вас есть или было. Если стоите на учёте — это тоже важно."},
    {"title": "Болезни в семье", "nav": "Семья", "nav_hint": "Родители, братья, сёстры", "optional": True,
     "description": "Некоторые обследования советуют начинать раньше, если болезнь была у близких. Шаг можно пропустить."},
    {"title": "Ещё немного о вас", "nav": "Дополнительно", "nav_hint": "Лекарства и наркоз", "optional": True,
     "description": "Обследования желудка и кишечника в пакетах проходят под наркозом. Эти ответы нужны врачу."},
]

ADULT_F = {"sex": "F", "age_min": 15, "adult": True}
SMOKE_DETAILS = {"adult": True, "when": [["smoke_status", "in", ["smokes", "quit"]]]}
CONDITION_OPTIONS = [
    ["pressure", "Повышенное давление"], ["heart", "Боли в сердце, перенесённый инфаркт"],
    ["diabetes", "Сахарный диабет"], ["glaucoma", "Глаукома"],
    ["head_vessels", "Инсульт, проблемы с сосудами, частые головные боли"],
    ["legs", "Боли в ногах при ходьбе, судороги, спазмы"],
    ["breast", "Молочная железа: уплотнения, фиброаденома, опухоль", "F"],
    ["hpv", "ВПЧ или изменения шейки матки", "F"],
    ["bowel", "Запоры, полипы или опухоль кишечника"], ["lungs", "Проблемы с лёгкими"],
    ["tb", "Туберкулёз"], ["hepatitis", "Хронический гепатит B или C"],
    ["urine", "Проблемы с мочеиспусканием"], ["bleeding", "Кровотечения (были раньше)"],
]
# Состояния, по которым бывает учёт у врача → скрининг по ним не положен (коды — rules.json, not_registered)
REGISTERED_AS = {"pressure": "hypertension", "heart": "ihd", "diabetes": "diabetes", "glaucoma": "glaucoma",
                 "head_vessels": "cerebrovascular", "breast": "breast_cancer", "hpv": "cervical_cancer",
                 "bowel": "colorectal", "lungs": "lung_cancer", "hepatitis": "chronic_hepatitis"}
REGISTRABLE = list(REGISTERED_AS)

FIELDS = [
    # 0 — О вас
    {"name": "for_child", "label": "Для кого подбираем программу?", "type": "boolean", "step": 0,
     "default": False, "options": [[False, "Для себя"], [True, "Для ребёнка"]]},
    {"name": "sex", "label": "Пол", "type": "select", "step": 0, "required": True,
     "options": [["F", "Женский"], ["M", "Мужской"]]},
    {"name": "birth_date", "label": "Дата рождения", "type": "date", "step": 0, "required": True,
     "hint": "Дата рождения человека, для которого заполняете анкету."},

    # 1 — Самочувствие
    {"name": "urgent", "label": "Беспокоит ли что-то прямо сейчас?", "type": "select", "step": 1,
     "required": True, "layout": "stack", "stop": True,
     "hint": "Если да — это не чекап: нужна помощь врача сегодня.", "options": [
         ["none", "Нет, чувствую себя как обычно"],
         ["chest_pain", "Боль или давление в груди"], ["dyspnea", "Сильная одышка"],
         ["stroke_signs", "Внезапная слабость в руке или ноге, трудно говорить"],
         ["other_now", "Другое, что беспокоит сейчас"]]},

    # 2 — Женское / мужское здоровье
    {"name": "last_period", "label": "Дата начала последних месячных", "type": "date", "step": 2,
     "show_if": {"sex": "F", "age_min": 12, "age_max": 55, "adult": True},
     "hint": "Если месячных уже нет — оставьте пустым."},
    {"name": "pregnant", "label": "Вы беременны или можете быть беременны?", "type": "select", "step": 2,
     "show_if": {"sex": "F", "age_min": 15, "age_max": 55, "adult": True},
     "options": [["no", "Нет"], ["yes", "Да"], ["unsure", "Не уверена"]],
     "hint": "При беременности КТ и маммографию не проводят — обсудите обследования с врачом."},
    {"name": "pregnancies", "label": "Сколько у вас было беременностей?", "type": "number", "step": 2,
     "min": 0, "max": 30, "placeholder": "0", "show_if": ADULT_F, "hint": "Если не было — поставьте 0."},
    {"name": "births", "label": "Сколько было родов?", "type": "number", "step": 2, "min": 0, "max": 30,
     "placeholder": "0", "show_if": {**ADULT_F, "when": [["pregnancies", "gt", 0]]}},
    {"name": "contraception", "label": "Чем предохраняетесь?", "type": "select", "step": 2,
     "show_if": {"sex": "F", "age_min": 15, "age_max": 55, "adult": True}, "options": [
         ["none", "Ничем"], ["condom", "Презерватив"], ["pills", "Таблетки"], ["iud", "Спираль"],
         ["other", "Другое"], ["not_needed", "Не нужно"]]},
    {"name": "discharge", "label": "Есть ли выделения из половых путей, неприятный запах?", "type": "select",
     "step": 2, "show_if": ADULT_F, "options": [["no", "Нет"], ["yes", "Да"]]},
    {"name": "dysuria", "label": "Есть ли боль или жжение при мочеиспускании, выделения?", "type": "select",
     "step": 2, "show_if": {"sex": "M", "age_min": 15, "adult": True}, "options": [["no", "Нет"], ["yes", "Да"]]},

    # 3 — История здоровья
    {"name": "conditions", "label": "Что из этого у вас есть или было?", "type": "multiselect", "step": 3,
     "layout": "stack", "exclusive": "none", "hint": "Отметьте всё, что подходит.",
     "options": CONDITION_OPTIONS + [["none", "Ничего из этого"]]},
    {"name": "conditions_other", "label": "Другое — впишите своё", "type": "text", "step": 3,
     "hint": "Если чего-то нет в списке.", "show_if": {"when": [["conditions", "lacks", "none"]]}},
    {"name": "registered_on", "label": "По чему из отмеченного вы стоите на учёте у врача?", "type": "multiselect",
     "step": 3, "layout": "stack", "options_from": "conditions", "contract": "registered", "maps_to": REGISTERED_AS,
     "hint": "Если стоите на учёте — это обследование ведёт ваш врач, отдельный бесплатный скрининг не нужен.",
     "show_if": {"when": [["conditions", "has_any", REGISTRABLE]]},
     "options": [o for o in CONDITION_OPTIONS if o[0] in REGISTRABLE]},
    {"name": "smoke_status", "label": "Вы курите или курили?", "type": "select", "step": 3,
     "show_if": {"adult": True}, "options": [["never", "Не курил(а)"], ["smokes", "Курю"], ["quit", "Бросил(а)"]]},
    {"name": "quit_years_ago", "label": "Сколько лет назад бросили?", "type": "number", "step": 3, "min": 0,
     "max": 80, "placeholder": "Лет", "show_if": {"adult": True, "when": [["smoke_status", "eq", "quit"]]}},
    {"name": "cigs_per_day", "label": "Сколько сигарет в день?", "type": "number", "step": 3, "min": 0,
     "max": 100, "placeholder": "Штук", "show_if": SMOKE_DETAILS},
    {"name": "smoke_years", "label": "Сколько лет курите (курили)?", "type": "number", "step": 3, "min": 0,
     "max": 80, "placeholder": "Лет", "show_if": SMOKE_DETAILS},
    {"name": "hazardous_work_10y", "label": "Последние 10 лет работали на вредном производстве?", "type": "select",
     "step": 3, "show_if": {"age_min": 50, "age_max": 70, "adult": True},
     "hint": "Если не уверены — отметьте «Да», врач уточнит.", "options": [["no", "Нет"], ["yes", "Да"]]},
    {"name": "last_screening", "label": "Что проходили за последние 2 года?", "type": "multiselect", "step": 3,
     "show_if": {"adult": True}, "hint": "Если не помните — оставьте без отметки.", "options": [
         ["scr_breast", "Маммография", "F"], ["scr_cervix", "Мазок на онкоцитологию или ВПЧ", "F"],
         ["scr_colorectal", "Анализ кала на скрытую кровь"], ["scr_cvd", "Анализы на холестерин и сахар"]]},
    {"name": "attached_to", "label": "Вы прикреплены к поликлинике?", "type": "select", "step": 3,
     "layout": "stack", "options": [["green_clinic", "К Green Clinic"], ["other", "К другой поликлинике"],
                                    ["unknown", "Не знаю"]]},

    # 4 — Болезни в семье
    {"name": "family_history", "label": "Было ли у родителей, братьев, сестёр?", "type": "multiselect", "step": 4,
     "layout": "stack", "exclusive": "none", "options": [
         ["colorectal_cancer", "Рак кишечника"], ["breast_cancer", "Рак молочной железы или яичников"],
         ["other_cancer", "Другой рак"], ["early_cvd", "Инфаркт или инсульт до 60 лет"],
         ["hypertension", "Повышенное давление"], ["diabetes", "Сахарный диабет"], ["tb", "Туберкулёз"],
         ["none", "Нет или не знаю"]]},

    # 5 — Дополнительно
    {"name": "anesthesia_reaction", "label": "Были ли плохие реакции на наркоз?", "type": "select", "step": 5,
     "show_if": {"adult": True}, "options": [["no", "Нет"], ["yes", "Да"], ["never", "Наркоза не было"]]},
    {"name": "blood_thinners", "label": "Принимаете препараты, разжижающие кровь?", "type": "select", "step": 5,
     "show_if": {"adult": True},
     "hint": "Например, аспирин, варфарин. Перед гастро- и колоноскопией врач скажет, как с ними быть.",
     "options": [["no", "Нет"], ["yes", "Да"], ["unknown", "Не знаю"]]},
    {"name": "allergy", "label": "Была ли аллергия на лекарства или контраст?", "type": "select", "step": 5,
     "options": [["no", "Нет"], ["yes", "Да"], ["unknown", "Не знаю"]]},
    {"name": "medications", "label": "Какие лекарства принимаете сейчас?", "type": "textarea", "step": 5,
     "hint": "Названия и как принимаете, если помните. Если никаких — оставьте пустым."},
    {"name": "companion", "label": "Сможет ли кто-то проводить вас домой в день обследования?", "type": "select",
     "step": 5, "show_if": {"adult": True}, "hint": "После наркоза в этот день нельзя садиться за руль.",
     "options": [["yes", "Да"], ["no", "Нет"]]},
]
