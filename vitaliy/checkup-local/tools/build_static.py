"""Онлайн-копия для ссылки claude.ai: две страницы без сервера — dist/index.html (анкета) и dist/app.html.

Движок — тот же engine.py + api_logic.py, исполняется в браузере через Pyodide (cdn.jsdelivr.net/npm/pyodide).
Если Pyodide не загрузился — запасной путь: ответы, записанные с работающего сервера (http://localhost:8010)
для демо-пациентов. Шрифт, логотип, иконки подготовки встраиваются data:-адресами.
Запуск: сервер на 8010 поднят → python tools/build_static.py
"""
import asyncio
import base64
import json
import mimetypes
import os
import re
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://localhost:8010"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PYODIDE = "https://cdn.jsdelivr.net/npm/pyodide@0.26.4/"


def get(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    return json.loads(urllib.request.urlopen(req).read().decode("utf-8"))


async def record_predicts():
    """Запасной путь: /api/predict для каждого демо-пациента (кнопки сценария)."""
    rec = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=EDGE if os.path.exists(EDGE) else None)
        pg = await b.new_page()

        async def on_request(req):
            if req.url.endswith("/api/predict"):
                rec[req.post_data] = await (await req.response()).json()
        pg.on("requestfinished", lambda r: asyncio.ensure_future(on_request(r)))
        await pg.goto(BASE + "/app#scenario")
        await pg.wait_for_timeout(2500)
        n = await pg.evaluate("document.querySelectorAll('#scenario [data-sample]').length")
        for i in range(n):
            await pg.locator('#scenario [data-sample]').nth(i).click()
            await pg.wait_for_timeout(800)
            await pg.evaluate("go('scenario')")
            await pg.wait_for_timeout(600)
        await b.close()
    return rec


def data_uri(f):
    mime = mimetypes.guess_type(f.name)[0] or ("font/ttf" if f.suffix == ".ttf" else "application/octet-stream")
    if f.suffix == ".svg":
        mime = "image/svg+xml"
    return f"data:{mime};base64,{base64.b64encode(f.read_bytes()).decode()}"


def inline_css(css):
    def repl(m):
        f = ROOT / m.group(1).lstrip("/")
        return f"url({data_uri(f)})" if f.exists() else m.group(0)
    return re.sub(r"url\(['\"]?(/static/[^)'\"]+)['\"]?\)", repl, css)


def links(js):
    """Переходы между страницами: на сервере /, /app — в копии index.html, app.html."""
    return (js.replace("location.href = '/app'", "location.href = 'app.html'")
              .replace("location.href = '/?play=1'", "location.href = 'index.html?play=1'")
              .replace("location.href = '/'", "location.href = 'index.html'"))


def main():
    st = ROOT / "static"
    logo = data_uri(st / "anketa" / "logo.svg")
    icons = {f.stem: data_uri(f) for f in sorted((st / "img" / "prep").glob("*.svg")) if not f.stem.startswith("_")}
    api = {"GET /fields": get("/fields"), "GET /steps": get("/steps"), "GET /rules": get("/rules"),
           "GET /api/samples": get("/api/samples"), "GET /api/catalog": get("/api/catalog"),
           "GET /api/sources": get("/api/sources"), "GET /api/consent": get("/api/consent")}
    fallback = {}
    for places in ({}, {"r103": 2}, {"r103": 3}):
        key = json.dumps({"places": places}, separators=(",", ":"))
        fallback["POST /api/morning " + key] = get("/api/morning", {"places": places})
        fallback["POST /api/scenario " + key] = get("/api/scenario", {"places": places})
    predicts = asyncio.run(record_predicts())
    pyfiles = {"engine.py": (ROOT / "engine.py").read_text(encoding="utf-8"),
               "api_logic.py": (ROOT / "api_logic.py").read_text(encoding="utf-8"),
               "spec/rules.json": (ROOT / "spec" / "rules.json").read_text(encoding="utf-8"),
               "spec/demo_patients.json": (ROOT / "spec" / "demo_patients.json").read_text(encoding="utf-8")}

    shim = """
const __API = %(api)s, __FALLBACK = %(fallback)s, __PRED = %(pred)s, __PY_FILES = %(py)s;
window.PREP_ICONS = %(icons)s;
let __pyReady = null;
function __note(text) {
  let n = document.getElementById('engine-note');
  if (!n) { n = document.createElement('div'); n.id = 'engine-note';
    n.style.cssText = 'position:fixed;top:12px;left:50%%;transform:translateX(-50%%);z-index:100;background:#fff;color:#184d3b;border:2px solid #ffca79;border-radius:12px;padding:8px 16px;font:500 14px Geologica,system-ui,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.15)';
    document.body.appendChild(n); }
  n.textContent = text; n.hidden = !text;
}
function __engine() {
  if (__pyReady) return __pyReady;
  __pyReady = (async () => {
    __note('Загружаем движок правил (Python в браузере)…');
    await new Promise((ok, fail) => { const s = document.createElement('script'); s.src = '%(pyodide)spyodide.js'; s.onload = ok; s.onerror = fail; document.head.appendChild(s); });
    const py = await loadPyodide({ indexURL: '%(pyodide)s' });
    py.FS.mkdirTree('/work/spec');
    for (const [name, text] of Object.entries(__PY_FILES)) py.FS.writeFile('/work/' + name, text);
    py.runPython("import sys, os, json; sys.path.insert(0, '/work'); os.chdir('/work'); import engine, api_logic");
    __note('');
    return py;
  })().catch((e) => { console.error('Pyodide не загрузился — работают только демо-пациенты', e); __note(''); return null; });
  return __pyReady;
}
const __orig = window.fetch;
window.fetch = async (url, opt = {}) => {
  const m = (opt.method || 'GET').toUpperCase(), path = String(url).replace(location.origin, '');
  const json = (d) => new Response(JSON.stringify(d), { headers: { 'Content-Type': 'application/json' } });
  if (__API[`${m} ${path}`] !== undefined) return json(__API[`${m} ${path}`]);
  if (m === 'POST' && ['/api/predict', '/api/morning', '/api/scenario'].includes(path)) {
    const py = await __engine();
    if (py) {
      py.globals.set('__in', opt.body || '{}');
      const fn = { '/api/predict': 'engine.predict', '/api/morning': 'api_logic.api_morning', '/api/scenario': 'api_logic.api_scenario' }[path];
      return json(JSON.parse(py.runPython(`json.dumps(${fn}(json.loads(__in)), ensure_ascii=False)`)));
    }
    if (path === '/api/predict') return json(__PRED[opt.body] || { error: 'Движок не загрузился: в онлайн-копии сейчас работают только демо-пациенты (вкладка «12 пациентов»).' });
    const key = `${m} ${path} ${JSON.stringify(JSON.parse(opt.body || '{}'))}`;
    return json(__FALLBACK[key] || __FALLBACK[`${m} ${path} {"places":{}}`]);
  }
  return __orig(url, opt);
};
""" % {"api": json.dumps(api, ensure_ascii=False), "fallback": json.dumps(fallback, ensure_ascii=False),
       "pred": json.dumps(predicts, ensure_ascii=False), "py": json.dumps(pyfiles, ensure_ascii=False),
       "icons": json.dumps(icons), "pyodide": PYODIDE}

    def page(html_path, css_paths, js_paths):
        html = html_path.read_text(encoding="utf-8")
        html = re.sub(r'<link rel="stylesheet" href="[^"]+">', "", html)
        html = re.sub(r'<script src="[^"]+"( defer)?></script>\n?', "", html)
        css = "\n".join(inline_css(p.read_text(encoding="utf-8")) for p in css_paths)
        js = "\n".join(links(p.read_text(encoding="utf-8")) for p in js_paths)
        js = js.replace("src=\"/static/img/prep/${esc(id)}.svg\"", "src=\"${(window.PREP_ICONS || {})[id] || ''}\"")
        html = html.replace('src="/static/anketa/logo.svg"', f'src="{logo}"').replace("href=\"/\"", "href=\"index.html\"")
        return html.replace("</head>", f"<style>{css}</style>\n<script>{shim}</script>\n</head>", 1) \
                   .replace("</body>", f"<script>{js}</script>\n</body>", 1)

    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    anketa = page(st / "anketa" / "index.html", [st / "anketa" / "style.css"],
                  [st / "anketa" / "app.js", st / "spotlight.js", st / "anketa" / "demo.js"])
    # анкета: demo.js ждёт window 'load' — в копии скрипты в конце body, событие ещё впереди
    app = page(st / "index.html", [st / "style.css"], [st / "app.js", st / "spotlight.js", st / "tour.js"])
    (out / "index.html").write_text(anketa, encoding="utf-8")
    (out / "app.html").write_text(app, encoding="utf-8")
    print("icons:", len(icons), "fallback predicts:", len(predicts),
          "sizes KB:", len(anketa) // 1024, len(app) // 1024)


if __name__ == "__main__":
    main()
