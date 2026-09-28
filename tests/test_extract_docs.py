"""Page and sidebar parsing in xbsl/extract/docs.py - on mini fixtures (no distribution)."""

from xbsl.extract import _distro
from xbsl.extract import docs as ex

ORIGIN = "https://1cmycloud.com"

# A mini page in Docusaurus markup: breadcrumbs and footer outside the content block, a link to Std,
# a hash anchor, a Prism code block, an image, and a control character inside a word.
PAGE = (
    "<html><body><article>"
    '<nav class="theme-doc-breadcrumbs"><span itemprop="name">Мас\x00сив</span></nav>'
    '<div class="theme-doc-markdown markdown"><div class="row"><div class="col col--12 markdown">'
    "<header><h1>Мас\x00сив</h1></header>"
    "<p><code>Стд::Коллекции::Массив</code>  <code>Доступность: КлиентИСервер</code></p>"
    '<p>См. <a href="/docs/help/stdlib/element/xbsl/Std/Object_ru/">Объект</a> и '
    '<a href="https://example.org/x">внешнее</a>.</p>'
    '<h2 class="anchor anchorWithStickyNavbar" id="r">Раздел'
    '<a href="#r" class="hash-link" title="ссылка">​</a></h2>'
    '<div class="language-xbsl codeBlockContainer"><div class="codeBlockContent">'
    '<pre class="prism-code"><code class="codeBlockLines">'
    '<span class="token-line"><span class="token xbsl-keyword">знч</span>'
    '<span class="token plain"> Х = 1</span><br></span>'
    '<span class="token-line"><span class="token plain">  Х = 2</span><br></span></code></pre></div></div>'
    '<p><img decoding="async" alt="s" src="/docs/help/assets/images/a.png" width="10" class="img_x"></p>'
    "</div></div></div>"
    '<footer class="theme-doc-footer">низ страницы</footer>'
    "</article></body></html>"
)

ENTRY = "data/docs/help/ru/stdlib/element/xbsl/Std/Collections/Array_ru/index.html"


def _rec():
    return ex._record(ENTRY, PAGE, ORIGIN)


def test_fields_extracted():
    r = _rec()
    assert r["id"] == "stdlib/element/xbsl/Std/Collections/Array_ru"  # id = URL path without /docs/help/
    assert r["title"] == "Массив"                                     # the control character is cleaned out
    assert r["qualified"] == "Стд::Коллекции::Массив"
    assert r["availability"] == "КлиентИСервер"
    assert r["url"] == ORIGIN + "/docs/help/stdlib/element/xbsl/Std/Collections/Array_ru/"


def test_topic_does_not_borrow_a_qualifier():
    # On a guide topic the same `Стд::...` pattern matches a name QUOTED in its prose; stored
    # as the page's own qualifier it would then answer symbol lookups for that name.
    topic = ex._record("data/docs/help/ru/topics/set-method-breakpoint/index.html", PAGE, ORIGIN)
    assert topic["id"] == "topics/set-method-breakpoint"
    assert topic["qualified"] == ""


def test_kind_heuristic():
    assert ex._kind("... Иерархия типа ...") == "type"
    assert ex._kind("... Места применения ...") == "annotation"
    assert ex._kind("... Синтаксис ... Параметры ...") == "method"
    assert ex._kind("просто текст") == "member"


def test_chrome_stripped():
    html = _rec()["html"]
    assert "theme-doc" not in html and "breadcrumbs" not in html
    assert "низ страницы" not in html       # the footer is outside the content
    assert "class=" not in html and "<nav" not in html and "<div" not in html
    assert "hash-link" not in html and "​" not in html


def test_internal_link_rewritten_external_kept():
    html = _rec()["html"]
    assert '<a href="#stdlib/element/xbsl/Std/Object_ru">Объект</a>' in html
    assert '<a href="https://example.org/x">внешнее</a>' in html


def test_code_flattened():
    html = _rec()["html"]
    # line breaks and indentation inside a code block survive (not eaten by whitespace normalization)
    assert "<pre><code>знч Х = 1\n  Х = 2</code></pre>" in html
    assert "token" not in html and "<span" not in html


def test_image_preserved_and_ref_collected():
    html = _rec()["html"]
    assert '<img src="assets/images/a.png">' in html
    assert ex._ASSET_REF_RE.findall(html) == ["assets/images/a.png"]


def test_text_has_no_tags():
    text = _rec()["text"]
    assert "<" not in text and ">" not in text
    assert "Массив" in text and "знч Х = 1" in text


def test_no_content_block_returns_none():
    assert ex._record("x/index.html", "<html><body>нет разметки</body></html>", ORIGIN) is None


# The same page as a minified docs site writes it: a value without spaces goes unquoted
# (`class=hash-link`, `href=/docs/help/...`, `id=r`).
PAGE_MINIFIED = (
    "<html><body><article>"
    "<nav class=theme-doc-breadcrumbs><span itemprop=name>Мас\x00сив</span></nav>"
    '<div class="theme-doc-markdown markdown"><div class=row><div class="col col--12 markdown">'
    "<header><h1>Мас\x00сив</h1></header>"
    "<p><code>Стд::Коллекции::Массив</code>  <code>Доступность: КлиентИСервер</code></p>"
    "<p>См. <a href=/docs/help/stdlib/element/xbsl/Std/Object_ru/>Объект</a> и "
    "<a href=https://example.org/x>внешнее</a>.</p>"
    '<h2 class="anchor anchorTargetStickyNavbar" id=r>Раздел'
    "<a href=#r class=hash-link title=ссылка translate=no>​</a></h2>"
    '<div class="language-xbsl codeBlockContainer"><div class=codeBlockContent>'
    "<pre class=prism-code><code class=codeBlockLines>"
    '<span class=token-line><span class="token xbsl-keyword">знч</span>'
    '<span class="token plain"> Х = 1</span><br></span>'
    '<span class=token-line><span class="token plain">  Х = 2</span><br></span></code></pre></div></div>'
    "<p><img decoding=async alt=s src=/docs/help/assets/images/a.png width=10 class=img_x></p>"
    "</div></div></div>"
    "<footer class=theme-doc-footer>низ страницы</footer>"
    "</article></body></html>"
)


def test_minified_page_reads_as_the_quoted_one():
    assert ex._record(ENTRY, PAGE_MINIFIED, ORIGIN) == _rec()


def test_normalize_markup_keeps_quoted_values_whole():
    # `url=` inside a quoted value is not an attribute; `>` inside quotes does not end the tag
    assert (_distro.normalize_markup('<meta http-equiv=refresh content="0; url=/docs/help/x/">')
            == '<meta http-equiv="refresh" content="0; url=/docs/help/x/">')
    assert _distro.normalize_markup("<div data-x='a>b' id=y>т=1</div>") == "<div data-x='a>b' id=\"y\">т=1</div>"
    assert _distro.normalize_markup(PAGE) == PAGE


def test_normalize_markup_escapes_a_bare_angle_bracket_in_text():
    # a minified page writes `>` in text as it is; a script keeps its own
    assert (_distro.normalize_markup("<p><code>Стд::Коллекции::Массив&lt;ТипЭлемента></code></p>")
            == "<p><code>Стд::Коллекции::Массив&lt;ТипЭлемента&gt;</code></p>")
    script = "<script>if(a>b){x='<a href=y>'}</script><!-- a>b -->"
    assert _distro.normalize_markup(script) == script


# --- sidebar parsing ------------------------------------------------------------------

# A mini bundle: two sidebars; the second has a label with extra quote escaping (as in the real
# bundle, 'Ключевое слово \\"ничто\\"') that plain json.loads cannot handle.
JS = (
    'x={"developer":[{"type":"category","label":"Основы","items":['
    '{"type":"link","label":"Обзор","href":"/docs/help/topics/overview"}]},'
    '{"type":"link","label":"Тип","href":"/docs/help/stdlib/element/xbsl/Std/String_ru"}],'
    '"xbslStdlib":[{"type":"link","label":"Ключевое слово \\\\"ничто\\\\"",'
    '"href":"/docs/help/topics/void"}]}'
)


def test_sidebar_items_parsed():
    dev = ex._sidebar_items(JS, "developer")
    assert dev is not None and len(dev) == 2
    assert dev[0]["label"] == "Основы" and dev[0]["items"][0]["href"].endswith("/overview")


def test_sidebar_double_escaped_quote_repaired():
    std = ex._sidebar_items(JS, "xbslStdlib")   # contains the label with \\"ничто\\"
    assert std is not None and len(std) == 1
    assert "ничто" in std[0]["label"]


def test_sidebar_javascript_escapes_repaired():
    # a newer bundle writes a guillemet as `\xab` and a quote as `\'` - not JSON escapes
    js = ('x={"developer":[{"type":"link","href":"/docs/help/topics/overview",'
          '"label":"\\xab1\\u0421:\\u042d\\u043b\\u0435\\u043c\\u0435\\u043d\\u0442\\xbb, \\\\x \\\'ok\\\'"}]}')
    dev = ex._sidebar_items(js, "developer")
    assert dev is not None and dev[0]["label"] == "\u00ab1С:Элемент\u00bb, \\x 'ok'"


def test_collect_hrefs_skips_template_ns():
    items = [
        {"type": "link", "label": "ok", "href": "/docs/help/topics/x"},
        {"type": "category", "label": "tpl",
         "href": "/docs/help/stdlib/element/xbsl/DeveloperName/P/S",
         "items": [{"type": "link", "label": "y", "href": "/docs/help/stdlib/element/xbsl/DeveloperName/P/S/y"}]},
    ]
    out: set[str] = set()
    ex._collect_hrefs(items, out)
    assert out == {"topics/x"}                  # the template namespace and its subtree are skipped


def test_href_to_page():
    assert ex._href_to_page("/docs/help/topics/x") == "topics/x"
    assert ex._href_to_page("https://external/x") is None
    assert ex._href_to_page("") is None


# --- the whole build over a mini distribution ------------------------------------------

def _page(title: str, body: str = "") -> str:
    return (f'<article><div class="theme-doc-markdown markdown"><header><h1>{title}</h1></header>'
            f"{body}</div></article>")


def test_build_takes_the_property_reference_panels(tmp_path):
    """The property references are panels of their own; their pages and sections land in the base.

    A panel the bundle lacks (an older distribution) yields no section, and the order of the
    sections is that of SIDEBARS - the order of the site menu.
    """
    import sqlite3
    import zipfile

    prop = "stdlib/element/ProjectElements/Std/Enums/EventImportance_ru"
    js = (
        'x={"developer":[{"type":"link","label":"Обзор","href":"/docs/help/topics/overview"}],'
        '"projectElementsStdlib":[{"type":"category","label":"Перечисления",'
        '"href":"/docs/help/stdlib/element/ProjectElements/Std/Enums/","items":['
        f'{{"type":"link","label":"ВажностьСобытия","href":"/docs/help/{prop}"}}]}}]}}'
    )
    dist = tmp_path / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "element-server-with-ide-1.0.0-x.car", "w") as car:
        car.writestr(ex.SITE_ROOT + "assets/js/sidebars.js", js)
        car.writestr(ex.SITE_ROOT + "topics/overview/index.html", _page("Обзор"))
        car.writestr(ex.SITE_ROOT + "stdlib/element/ProjectElements/Std/Enums/index.html",
                     _page("Перечисления"))
        car.writestr(ex.SITE_ROOT + prop + "/index.html", _page(
            "ВажностьСобытия", '<h2 id="литералы">Литералы</h2><h4 id="изконструктора">ИзКонструктора</h4>'))
    out = tmp_path / "data" / "docs.sqlite"
    out.parent.mkdir()
    pages, _nodes = ex.build(dist, out)
    assert pages == 3
    con = sqlite3.connect(out)
    try:
        assert con.execute("SELECT title FROM pages WHERE id = ?", (prop,)).fetchone() == ("ВажностьСобытия",)
        sections = [row[0] for row in con.execute("SELECT label FROM tree WHERE parent IS NULL ORDER BY ord")]
        link = con.execute("SELECT kind FROM tree WHERE page = ? AND anchor IS NULL", (prop,)).fetchone()
    finally:
        con.close()
    assert sections == ["Руководство разработчика", "Свойства элементов проекта"]
    assert link == ("link",)
    assert [label for key, label in ex.SIDEBARS if key.endswith("Stdlib")] == [
        "Типы языка 1С:Элемент", "Свойства элементов проекта", "Свойства компонентов интерфейса",
        "Схема процесса интеграции", "Язык запросов",
    ]
