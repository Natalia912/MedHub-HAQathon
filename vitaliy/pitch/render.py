"""Рендер deck.html в deck.pdf и slide1.png ... slide3.png через Edge/Playwright.

Запуск из любой папки: python <путь к pitch_final>/render.py
Все создаваемые файлы, включая профиль браузера, остаются в pitch_final.
Сеть запрещена: браузер читает только локальные файлы.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "qa"
TEMP = WORK / "browser-temp"
TEMP.mkdir(parents=True, exist_ok=True)
for name in ("TEMP", "TMP", "TMPDIR"):
    os.environ[name] = str(TEMP)
tempfile.tempdir = str(TEMP)
sys.dont_write_bytecode = True
# Windows consoles may default to cp1251, which cannot print the flow arrows.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

EDGE_PATHS = (
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)
EDGE = next((p for p in EDGE_PATHS if p.is_file()), None)
if EDGE is None:
    raise SystemExit("Microsoft Edge не найден ни в одном из двух ожидаемых путей.")


def main() -> None:
    report = {"slides": [], "network_requests": [], "errors": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(EDGE), headless=True, args=["--no-sandbox"]
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 810},
            device_scale_factor=1,
            locale="ru-RU",
            offline=True,
        )

        def local_only(route):
            url = route.request.url
            if url.startswith(("file:", "data:", "about:")):
                route.continue_()
            else:
                report["network_requests"].append(url)
                route.abort()

        context.route("**/*", local_only)
        page = context.new_page()
        page.on("pageerror", lambda error: report["errors"].append(str(error)))
        page.goto((ROOT / "deck.html").as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready")
        page.evaluate("""async () => {
            await Promise.all([...document.images].map(image => image.decode()));
        }""")
        slides = page.locator(".slide")
        if slides.count() != 3:
            raise RuntimeError(f"Ожидались 3 слайда, получено: {slides.count()}")

        report["fonts"] = page.evaluate("""() => [...document.fonts].map(font => ({
            family: font.family, status: font.status
        }))""")
        for i in range(3):
            slide = slides.nth(i)
            slide.screenshot(path=str(ROOT / f"slide{i+1}.png"), animations="disabled")
            result = slide.evaluate("""slide => {
                const outer = slide.getBoundingClientRect();
                const overflow = [], smallText = [];
                for (const el of slide.querySelectorAll('*')) {
                    const box = el.getBoundingClientRect();
                    if (box.width === 0 || box.height === 0) continue;
                    const style = getComputedStyle(el);
                    const directText = [...el.childNodes].some(n =>
                        n.nodeType === Node.TEXT_NODE && n.textContent.trim());
                    if (box.left < outer.left - .5 || box.top < outer.top - .5 ||
                        box.right > outer.right + .5 || box.bottom > outer.bottom + .5 ||
                        el.scrollWidth > el.clientWidth + 1 ||
                        el.scrollHeight > el.clientHeight + 1) {
                        overflow.push({element: el.className || el.tagName,
                            text: el.innerText?.slice(0, 100),
                            width: box.width, height: box.height,
                            scrollWidth: el.scrollWidth, scrollHeight: el.scrollHeight});
                    }
                    // Only the explicitly small legal reference and demo
                    // disclosure may use a smaller font than the slide body.
                    const minFont = el.matches('.legal-note') ? 14 :
                        el.closest('.demo-disclosure') ? 16 : 18;
                    if (directText && parseFloat(style.fontSize) < minFont) {
                        smallText.push({text: el.textContent, size: style.fontSize});
                    }
                }
                return {id: slide.id, width: outer.width, height: outer.height,
                    overflow, smallText, text: slide.innerText};
            }""")
            report["slides"].append(result)
        # 1440 CSS px = 1080 PDF points. Scale 4/3 reproduces the
        # organizer's actual PDF MediaBox of 1440 x 810 points exactly.
        page.add_style_tag(content="@page { size: 1440pt 810pt; margin: 0; }")
        page.pdf(
            path=str(ROOT / "deck.pdf"),
            width="20in", height="11.25in",
            scale=4 / 3, prefer_css_page_size=True,
            print_background=True, display_header_footer=False,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        browser.close()

    (WORK / "layout-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    bad = [s for s in report["slides"] if s["overflow"] or s["smallText"]]
    if bad or report["errors"] or report["network_requests"]:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit("Проверка не пройдена; см. qa/layout-report.json")
    print("Готово: deck.pdf, slide1.png, slide2.png, slide3.png; переполнений нет.")


if __name__ == "__main__":
    main()
