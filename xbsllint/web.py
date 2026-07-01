"""Веб-интерфейс линтера: указать папку проекта -> увидеть замечания.

Тонкий адаптер поверх ядра (как CLI и MCP), на стандартной библиотеке (http.server, без
внешних зависимостей). Слушает только 127.0.0.1. Запуск: xbsllint-web (или
python -m xbsllint.web), затем открыть http://127.0.0.1:8771/.

Оформление повторяет панель edt-bridge (тёмная/светлая тема, палитра 1С:Фреш), наполнение –
под линтер: ввод пути, настройки правил по тирам, сводка, фильтры по severity и тексту.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from xbsllint import __version__, dataset
from xbsllint.cli import discover
from xbsllint.diagnostics import Diagnostic
from xbsllint.engine import RULES, run


def _diag_dict(d: Diagnostic) -> dict:
    return {
        "path": d.path,
        "line": d.line,
        "col": d.col,
        "rule": d.rule_id,
        "severity": d.severity.value,
        "message": d.message,
    }


def _summary(diags: list[Diagnostic], n_files: int) -> dict:
    c = Counter(d.severity.value for d in diags)
    return {
        "files": n_files,
        "diagnostics": len(diags),
        "errors": c.get("error", 0),
        "warnings": c.get("warning", 0),
        "info": c.get("info", 0),
    }


def _lint(body: dict) -> dict:
    version = body.get("element_version")
    if version:
        dataset.set_version(version)
        dataset.resolve_version()  # бросит DatasetError, если версия недоступна

    raw_paths = body.get("paths")
    if not raw_paths:
        one = (body.get("path") or "").strip()
        raw_paths = [one] if one else []
    if not raw_paths:
        return {"error": "Укажите путь к папке проекта."}
    missing = [p for p in raw_paths if not Path(p).exists()]
    if missing:
        return {"error": f"Путь не найден: {', '.join(missing)}"}

    select = body.get("select")
    ignore = body.get("ignore")
    files = discover(raw_paths)
    sel = set(select) if select is not None else None
    if sel is not None and not sel:
        diags: list[Diagnostic] = []  # правила не выбраны
    else:
        diags = run(files, select=sel, ignore=set(ignore) if ignore else None)
    diags = sorted(diags, key=lambda x: x.sort_key())
    return {
        "diagnostics": [_diag_dict(d) for d in diags],
        "summary": _summary(diags, len(files)),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # тихий лог
        pass

    def _send(self, status: int, ctype: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200):
        self._send(status, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, "text/html; charset=utf-8", INDEX_HTML.encode("utf-8"))
        elif path == "/api/info":
            info = {"tool_version": __version__, "element_default": None, "element_available": []}
            try:
                info["element_default"] = dataset.default_version()
                info["element_available"] = dataset.available_versions()
            except dataset.DatasetError:
                pass
            self._json(info)
        elif path == "/api/rules":
            self._json([r.as_dict() for r in sorted(RULES, key=lambda x: (x.tier, x.id))])
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/lint":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            result = _lint(body)
        except dataset.DatasetError as exc:
            result = {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - показать пользователю, не падать
            result = {"error": f"{type(exc).__name__}: {exc}"}
        self._json(result)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="xbsllint-web", description="Веб-интерфейс линтера XBSL")
    ap.add_argument("--host", default="127.0.0.1", help="адрес (по умолчанию 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8771, help="порт (по умолчанию 8771)")
    args = ap.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"xbsl-lint web: {url}  (Ctrl-C для остановки)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
    finally:
        server.server_close()
    return 0


INDEX_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>xbsl-lint</title>
<style>
:root{
  --bg:#131215;--surface:#232128;--surface-2:#1A181E;--surface-hover:#2C2A33;
  --border:rgba(255,255,255,0.10);--border-strong:rgba(255,255,255,0.18);
  --text-1:#F4F1EC;--text-2:#C5C0B8;--text-3:#948D82;--text-4:#6A6359;
  --accent:#E2231A;--accent-soft:rgba(226,35,26,0.16);
  --warm:#F59E0B;--success:#2FD27A;--info:#5B8DEF;
  --btn:#FFD21E;--btn-hover:#FFDD55;--btn-fg:#1A1A1A;
  --shadow-card:0 18px 50px rgba(0,0,0,0.55);
  --font-ui:-apple-system,Roboto,"Segoe UI",system-ui,sans-serif;
  --font-mono:"JetBrains Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
:root[data-theme="light"]{
  --bg:#FBFAF8;--surface:#FFFFFF;--surface-2:#F3EFE8;--surface-hover:#ECE6DD;
  --border:rgba(33,28,22,0.12);--border-strong:rgba(33,28,22,0.22);
  --text-1:#1E1B17;--text-2:#4A443B;--text-3:#6E665B;--text-4:#9A9385;
  --accent-soft:rgba(226,35,26,0.10);--warm:#C2780A;--success:#149A50;--info:#3B6FD4;
  --shadow-card:0 16px 40px rgba(40,30,20,0.14);
}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--text-2);font-family:var(--font-ui);font-size:14px;line-height:1.55;transition:background-color .25s,color .25s;}
.wrap{max-width:1040px;margin:0 auto;padding:26px 20px 60px;}
header{display:flex;align-items:center;gap:14px;margin-bottom:22px;}
.logo{font-family:var(--font-mono);font-weight:800;font-size:22px;color:var(--text-1);letter-spacing:-.5px;}
.logo b{color:var(--btn);}
.dot{width:9px;height:9px;border-radius:50%;background:var(--text-4);}
.dot.ok{background:var(--success);box-shadow:0 0 10px var(--success);}
.ver{font-family:var(--font-mono);font-size:12px;color:var(--text-3);}
.spacer{flex:1;}
.tgl{height:38px;min-width:38px;padding:0 12px;background:var(--surface);border:1px solid var(--border-strong);border-radius:10px;color:var(--text-2);cursor:pointer;font:700 13px/1 var(--font-ui);}
.tgl:hover{color:var(--text-1);}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px 18px;margin:14px 0;box-shadow:var(--shadow-card);}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
label.fld{font-size:12px;color:var(--text-3);text-transform:uppercase;letter-spacing:.04em;}
input.path{flex:1;min-width:280px;background:var(--surface-2);color:var(--text-1);border:1px solid var(--border-strong);border-radius:10px;padding:11px 13px;font-family:var(--font-mono);font-size:13px;}
select{background:var(--surface-2);color:var(--text-1);border:1px solid var(--border-strong);border-radius:10px;padding:11px 10px;font-family:var(--font-mono);font-size:13px;}
button.run{background:var(--btn);color:var(--btn-fg);border:1px solid var(--btn);border-radius:10px;padding:11px 22px;cursor:pointer;font-weight:800;font-size:14px;transition:background-color .15s,transform .15s,box-shadow .15s;}
button.run:hover{background:var(--btn-hover);transform:translateY(-2px);box-shadow:0 12px 28px rgba(255,210,30,.30);}
button.run:disabled{opacity:.5;cursor:default;transform:none;box-shadow:none;}
.disc{background:transparent;border:none;color:var(--text-3);cursor:pointer;font:600 13px/1 var(--font-ui);padding:6px 0;display:flex;align-items:center;gap:8px;}
.disc:hover{color:var(--text-1);}
.chev{transition:transform .15s;}
.collapsed .chev{transform:rotate(-90deg);}
.rulegroup{margin:10px 0 0;}
.rgh{font:700 11px/1 var(--font-mono);color:var(--text-3);text-transform:uppercase;letter-spacing:.06em;margin:12px 0 6px;}
.rulerow{display:flex;align-items:center;gap:10px;padding:5px 6px;border-radius:8px;cursor:pointer;}
.rulerow:hover{background:var(--surface-hover);}
.rulerow input{accent-color:var(--btn);width:15px;height:15px;}
.rid{font-family:var(--font-mono);font-size:12px;color:var(--text-2);min-width:210px;}
.rtitle{color:var(--text-3);font-size:12px;}
.sev{font:700 10px/1 var(--font-mono);text-transform:uppercase;letter-spacing:.04em;padding:3px 6px;border-radius:5px;white-space:nowrap;}
.sev-error{color:#fff;background:var(--accent);}
.sev-warning{color:var(--btn-fg);background:var(--warm);}
.sev-info{color:#fff;background:var(--info);}
.summary{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin-bottom:6px;}
.chip{border:1px solid var(--border-strong);background:var(--surface-2);border-radius:999px;padding:6px 13px;font-size:13px;color:var(--text-2);cursor:pointer;user-select:none;}
.chip.on{border-color:var(--btn);color:var(--text-1);}
.chip b{font-family:var(--font-mono);}
.chip .c-err{color:var(--accent);}
.chip .c-warn{color:var(--warm);}
.chip .c-info{color:var(--info);}
.search{flex:1;min-width:160px;background:var(--surface-2);color:var(--text-1);border:1px solid var(--border);border-radius:8px;padding:8px 11px;font-size:13px;}
.group{margin:12px 0;border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--surface-2);}
.ghead{display:flex;align-items:center;gap:11px;padding:11px 14px;cursor:pointer;user-select:none;background:var(--surface);}
.ghead:hover{background:var(--surface-hover);}
.gfile{font-family:var(--font-mono);font-size:13px;color:var(--text-1);word-break:break-all;}
.gcount{margin-left:auto;font-family:var(--font-mono);font-size:12px;color:var(--text-3);}
.gbody{padding:4px 0;}
.diag{display:flex;align-items:flex-start;gap:11px;padding:8px 14px;text-decoration:none;color:inherit;border-top:1px solid var(--border);}
.diag:first-child{border-top:none;}
.diag:hover{background:var(--surface-hover);}
.pos{font-family:var(--font-mono);font-size:12px;color:var(--text-3);min-width:64px;text-align:right;padding-top:2px;}
.msg{flex:1;color:var(--text-2);}
.msg .r{display:block;font-family:var(--font-mono);font-size:11px;color:var(--text-4);margin-top:2px;}
.muted{color:var(--text-3);padding:14px 2px;}
.ok-box{color:var(--success);padding:16px 2px;font-weight:600;display:flex;gap:10px;align-items:center;}
.err-box{color:var(--accent);background:var(--accent-soft);border:1px solid var(--accent);border-radius:10px;padding:12px 14px;}
.hint{color:var(--text-4);font-size:12px;margin-top:8px;}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="dot" id="status"></span>
    <span class="logo">xbsl<b>-</b>lint</span>
    <span class="ver" id="ver"></span>
    <span class="spacer"></span>
    <button class="tgl" id="theme" title="Тема">◐</button>
  </header>

  <section class="panel">
    <div class="row">
      <input class="path" id="path" placeholder="Путь к папке проекта, напр. D:\Repos\site\e1c\site" spellcheck="false">
      <select id="version" title="Версия данных Элемента"></select>
      <button class="run" id="run">Проверить</button>
    </div>
    <div class="hint">Локальный инструмент (только 127.0.0.1). Кликните по замечанию, чтобы открыть файл в VS Code.</div>
  </section>

  <section class="panel" id="settingsPanel">
    <button class="disc" id="settingsToggle"><span class="chev">▾</span> Настройки правил</button>
    <div id="rules"></div>
  </section>

  <section id="results"></section>
</div>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let RULES = [], LAST = null, fSev = 'all', fText = '';

async function jget(u){ return (await fetch(u)).json(); }
async function jpost(u,b){ return (await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})).json(); }

function setTheme(t){ document.documentElement.setAttribute('data-theme', t); localStorage.setItem('xbsllint-theme', t); }
$('#theme').onclick = () => setTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light');

async function init(){
  setTheme(localStorage.getItem('xbsllint-theme') || 'dark');
  try{
    const info = await jget('/api/info');
    $('#ver').textContent = 'v' + info.tool_version + (info.element_default ? ' · Элемент ' + info.element_default : '');
    const vs = $('#version'); vs.innerHTML = '';
    (info.element_available || []).forEach(v => {
      const o = document.createElement('option'); o.value = v; o.textContent = v;
      if (v === info.element_default) o.selected = true; vs.appendChild(o);
    });
    RULES = await jget('/api/rules');
    renderSettings();
    $('#status').classList.add('ok');
  }catch(e){ $('#results').innerHTML = '<div class="err-box">Сервер недоступен: ' + esc(e) + '</div>'; }
}

const TIERS = {A:'A · структура / YAML', B:'B · текст / конвенции', C:'C · код', D:'D · семантика'};
function renderSettings(){
  const box = $('#rules'); box.innerHTML = '';
  const byTier = {};
  RULES.forEach(r => (byTier[r.tier] = byTier[r.tier] || []).push(r));
  Object.keys(TIERS).forEach(t => {
    if (!byTier[t]) return;
    const g = document.createElement('div'); g.className = 'rulegroup';
    g.innerHTML = '<div class="rgh">' + TIERS[t] + '</div>';
    byTier[t].forEach(r => {
      const lab = document.createElement('label'); lab.className = 'rulerow';
      lab.innerHTML = '<input type="checkbox" data-rule="' + esc(r.id) + '"' + (r.enabled_by_default ? ' checked' : '') + '>'
        + '<span class="rid">' + esc(r.id) + '</span>'
        + '<span class="sev sev-' + r.severity + '">' + r.severity + '</span>'
        + '<span class="rtitle">' + esc(r.title) + '</span>';
      g.appendChild(lab);
    });
    box.appendChild(g);
  });
}
function selectedRules(){
  return Array.from(document.querySelectorAll('#rules input[data-rule]:checked')).map(c => c.dataset.rule);
}

$('#settingsToggle').onclick = () => $('#settingsPanel').classList.toggle('collapsed');
$('#settingsPanel').classList.add('collapsed');
document.querySelector('#settingsPanel').addEventListener('click', e => {
  if (e.target.id === 'settingsToggle' || e.target.classList.contains('chev'))
    $('#rules').style.display = $('#settingsPanel').classList.contains('collapsed') ? 'none' : 'block';
});
$('#rules').style.display = 'none';

async function runLint(){
  const path = $('#path').value.trim();
  if (!path){ $('#path').focus(); return; }
  $('#run').disabled = true;
  $('#results').innerHTML = '<div class="muted">Проверяю…</div>';
  try{
    const res = await jpost('/api/lint', {path, select: selectedRules(), element_version: $('#version').value});
    LAST = res; fSev = 'all'; fText = '';
    render();
  }catch(e){ $('#results').innerHTML = '<div class="err-box">Ошибка: ' + esc(e) + '</div>'; }
  finally{ $('#run').disabled = false; }
}
$('#run').onclick = runLint;
$('#path').addEventListener('keydown', e => { if (e.key === 'Enter') runLint(); });

function render(){
  if (!LAST) return;
  if (LAST.error){ $('#results').innerHTML = '<div class="err-box">' + esc(LAST.error) + '</div>'; return; }
  const s = LAST.summary;
  const chip = (key, label, cls, n) =>
    '<span class="chip' + (fSev === key ? ' on' : '') + '" data-sev="' + key + '"><b class="' + cls + '">' + n + '</b> ' + label + '</span>';
  let html = '<div class="panel">';
  html += '<div class="summary">'
    + '<span class="chip' + (fSev==='all'?' on':'') + '" data-sev="all">Файлов <b>' + s.files + '</b> · всего <b>' + s.diagnostics + '</b></span>'
    + chip('error', 'ошибок', 'c-err', s.errors)
    + chip('warning', 'предупр.', 'c-warn', s.warnings)
    + chip('info', 'инфо', 'c-info', s.info)
    + '<input class="search" id="search" placeholder="Фильтр по тексту / правилу / файлу" value="' + esc(fText) + '">'
    + '</div>';

  let diags = LAST.diagnostics;
  if (fSev !== 'all') diags = diags.filter(d => d.severity === fSev);
  if (fText) { const q = fText.toLowerCase(); diags = diags.filter(d => (d.message + ' ' + d.rule + ' ' + d.path).toLowerCase().includes(q)); }

  if (!LAST.diagnostics.length){
    html += '<div class="ok-box">✓ Замечаний нет — чисто.</div>';
  } else if (!diags.length){
    html += '<div class="muted">Ничего не найдено по фильтру.</div>';
  } else {
    const groups = {};
    diags.forEach(d => (groups[d.path] = groups[d.path] || []).push(d));
    Object.keys(groups).sort().forEach(f => {
      const rows = groups[f].map(d =>
        '<a class="diag" href="vscode://file/' + esc(f.replace(/\\/g,'/')) + ':' + d.line + ':' + d.col + '">'
        + '<span class="pos">' + d.line + ':' + d.col + '</span>'
        + '<span class="sev sev-' + d.severity + '">' + d.severity + '</span>'
        + '<span class="msg">' + esc(d.message) + '<span class="r">' + esc(d.rule) + '</span></span>'
        + '</a>').join('');
      html += '<div class="group"><div class="ghead"><span class="gfile">' + esc(f) + '</span>'
        + '<span class="gcount">' + groups[f].length + '</span></div><div class="gbody">' + rows + '</div></div>';
    });
  }
  html += '</div>';
  $('#results').innerHTML = html;

  $('#results').querySelectorAll('.chip').forEach(c => c.onclick = () => { fSev = c.dataset.sev; render(); });
  const search = $('#search');
  if (search) search.oninput = () => { fText = search.value; const p = search.selectionStart; render(); const s2 = $('#search'); if (s2){ s2.focus(); s2.setSelectionRange(p,p);} };
}

init();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
