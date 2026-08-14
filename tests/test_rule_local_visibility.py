"""Checks of the code/local-method-cross-component rule (cross-component calls).

The rule needs no stdlib/metamodel catalogs, but the lexer requires language.json - the
module is skipped without the Element data the same way conftest skips the base modules
(this file is not in its list, hence the local guard).
"""

import pytest

from xbsl import dataset, engine
from xbsl.cli import discover

if not dataset.available_versions():
    pytest.skip(
        "нет данных Элемента – сгенерируйте: python tools/extract.py --dist ...",
        allow_module_level=True,
    )

RULE = "code/local-method-cross-component"


def _has(diags, rule_id=RULE):
    return any(d.rule_id == rule_id for d in diags)


def _проект(tmp_path, код_страницы, код_роутера=None, yaml_роутера=None):
    """A mini project: the Страница component + a router that embeds it and calls Загрузить."""
    (tmp_path / "Страница.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Страница\n", encoding="utf-8"
    )
    (tmp_path / "Страница.xbsl").write_text(код_страницы, encoding="utf-8")
    (tmp_path / "Роутер.yaml").write_text(
        yaml_роутера
        or (
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Роутер\nСодержимое:\n"
            "    -\n        Тип: Страница\n        Имя: Страница\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "Роутер.xbsl").write_text(
        код_роутера or "метод Открыть()\n    Компоненты.Страница.Загрузить()\n;\n",
        encoding="utf-8",
    )
    return engine.run(discover([str(tmp_path)]), select={RULE})


_ЛОКАЛЬНЫЙ = "метод Загрузить()\n    возврат\n;\n"
_ВПОДСИСТЕМЕ = "@ВПодсистеме\nметод Загрузить()\n    возврат\n;\n"


# --- Diagnostics ------------------------------------------------------------------


def test_без_аннотации_видимости_ловится(tmp_path):
    d = _проект(tmp_path, _ЛОКАЛЬНЫЙ)
    assert len(d) == 1
    assert d[0].rule_id == RULE
    assert "Загрузить" in d[0].message and "Страница" in d[0].message
    # the position is the call site in the router module
    assert d[0].path.endswith("Роутер.xbsl") and d[0].line == 2


def test_явное_локально_ловится(tmp_path):
    d = _проект(tmp_path, "@Локально\nметод Загрузить()\n    возврат\n;\n")
    assert len(d) == 1


def test_статический_без_видимости_ловится(tmp_path):
    d = _проект(tmp_path, "@НаСервере\nстатический метод Загрузить()\n    возврат\n;\n")
    assert len(d) == 1


# --- Sufficient visibility --------------------------------------------------------


@pytest.mark.parametrize("аннотация", ["ВПодсистеме", "ВПроекте", "ВТипе", "Глобально"])
def test_широкая_видимость_не_ловится(tmp_path, аннотация):
    d = _проект(tmp_path, f"@{аннотация}\nметод Загрузить()\n    возврат\n;\n")
    assert not _has(d)


def test_видимость_среди_других_аннотаций_не_ловится(tmp_path):
    d = _проект(
        tmp_path,
        "@НаСервере @ДоступноСКлиента\n@ВПодсистеме\n"
        "статический метод Загрузить()\n    возврат\n;\n",
    )
    assert not _has(d)


# --- Guards -----------------------------------------------------------------------


def test_встроенный_метод_платформы_не_ловится(tmp_path):
    # ВызватьМетод is not declared in the component module - it is a built-in instance method
    d = _проект(
        tmp_path,
        _ЛОКАЛЬНЫЙ,
        код_роутера="метод Открыть()\n    Компоненты.Страница.ВызватьМетод(\"х\", [])\n;\n",
    )
    assert not _has(d)


def test_свойство_не_вызов_не_ловится(tmp_path):
    d = _проект(
        tmp_path,
        _ЛОКАЛЬНЫЙ,
        код_роутера="метод Открыть()\n    Компоненты.Страница.Видимость = Истина\n;\n",
    )
    assert not _has(d)


def test_затенение_имени_компоненты_пропускает_модуль(tmp_path):
    d = _проект(
        tmp_path,
        _ЛОКАЛЬНЫЙ,
        код_роутера=(
            "метод Открыть(Компоненты: Структура)\n"
            "    Компоненты.Страница.Загрузить()\n;\n"
        ),
    )
    assert not _has(d)


def test_вызов_в_комментарии_не_ловится(tmp_path):
    d = _проект(
        tmp_path,
        _ЛОКАЛЬНЫЙ,
        код_роутера="метод Открыть()\n    // Компоненты.Страница.Загрузить()\n    возврат\n;\n",
    )
    assert not _has(d)


def test_экземпляр_другого_типа_с_тем_же_именем_не_ловится(tmp_path):
    # the 'Страница' instance in the form is NOT the project component Страница
    d = _проект(
        tmp_path,
        _ЛОКАЛЬНЫЙ,
        yaml_роутера=(
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Роутер\nСодержимое:\n"
            "    -\n        Тип: КонтейнерHtml\n        Имя: Страница\n"
        ),
    )
    assert not _has(d)


def test_компонент_не_встроен_в_форму_не_ловится(tmp_path):
    d = _проект(
        tmp_path,
        _ЛОКАЛЬНЫЙ,
        yaml_роутера="ВидЭлемента: КомпонентИнтерфейса\nИмя: Роутер\n",
    )
    assert not _has(d)


def test_вызывающий_не_компонент_не_ловится(tmp_path):
    # a module without a paired КомпонентИнтерфейса yaml - it has no Компоненты collection
    (tmp_path / "Страница.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Страница\n", encoding="utf-8"
    )
    (tmp_path / "Страница.xbsl").write_text(_ЛОКАЛЬНЫЙ, encoding="utf-8")
    (tmp_path / "Модуль.xbsl").write_text(
        "метод Открыть()\n    Компоненты.Страница.Загрузить()\n;\n", encoding="utf-8"
    )
    d = engine.run(discover([str(tmp_path)]), select={RULE})
    assert not _has(d)


def test_вызов_в_своём_модуле_не_ловится(tmp_path):
    # the component calls itself (same module - visibility does not restrict)
    (tmp_path / "Страница.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Страница\nСодержимое:\n"
        "    -\n        Тип: Страница\n        Имя: Страница\n",
        encoding="utf-8",
    )
    (tmp_path / "Страница.xbsl").write_text(
        "метод Загрузить()\n    возврат\n;\n"
        "метод Открыть()\n    Компоненты.Страница.Загрузить()\n;\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={RULE})
    assert not _has(d)


def test_вызов_члена_другого_объекта_не_ловится(tmp_path):
    # Что.Компоненты.Страница.Загрузить() - here Компоненты is another object's member
    d = _проект(
        tmp_path,
        _ЛОКАЛЬНЫЙ,
        код_роутера="метод Открыть(Что: Структура)\n    Что.Компоненты.Страница.Загрузить()\n;\n",
    )
    assert not _has(d)


def test_одиночный_буфер_без_yaml_не_ловится(tmp_path):
    # without the project yaml the components are unknown - a standalone buffer gets no diagnostics
    d = engine.run_sources(
        [engine.load_text("Роутер.xbsl", "метод Ф()\n    Компоненты.Страница.Загрузить()\n;\n")],
        select={RULE},
    )
    assert not _has(d)


# --- code/local-method-cross-module: the call goes through the MODULE NAME ---------------

MODULE_RULE = "code/local-method-cross-module"

_CALLEE_LOCAL = "метод Прочитать(): Строка\n    возврат \"\"\n;\n"
_CALLEE_WIDE = "@ВПодсистеме\nметод Прочитать(): Строка\n    возврат \"\"\n;\n"


def _module_project(tmp_path, callee: str, caller: str, callee_name="Настройки"):
    (tmp_path / f"{callee_name}.xbsl").write_text(callee, encoding="utf-8")
    (tmp_path / "Потребитель.xbsl").write_text(caller, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={MODULE_RULE})


def test_cross_module_call_of_a_local_method(tmp_path):
    diags = _module_project(
        tmp_path, _CALLEE_LOCAL, "метод Тест()\n    Настройки.Прочитать()\n;\n",
    )
    assert _has(diags, MODULE_RULE), [d.message for d in diags]
    message = [d for d in diags if d.rule_id == MODULE_RULE][0].message
    assert "Прочитать" in message and "Настройки.xbsl" in message


def test_wide_annotation_passes(tmp_path):
    diags = _module_project(
        tmp_path, _CALLEE_WIDE, "метод Тест()\n    Настройки.Прочитать()\n;\n",
    )
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


def test_named_arguments_are_still_a_call(tmp_path):
    diags = _module_project(
        tmp_path,
        "метод Записать(Ключ: Строка): Строка\n    возврат Ключ\n;\n",
        "метод Тест()\n    Настройки.Записать(Ключ = \"а\")\n;\n",
    )
    assert _has(diags, MODULE_RULE), [d.message for d in diags]


def test_own_module_is_never_restricted(tmp_path):
    # the module calls itself by name: locality does not restrict calls inside one module
    (tmp_path / "Настройки.xbsl").write_text(
        "метод Прочитать(): Строка\n    возврат \"\"\n;\n"
        "метод Тест()\n    Настройки.Прочитать()\n;\n",
        encoding="utf-8",
    )
    diags = engine.run(discover([str(tmp_path)]), select={MODULE_RULE})
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


def test_method_the_target_does_not_declare_is_skipped(tmp_path):
    diags = _module_project(
        tmp_path, _CALLEE_LOCAL, "метод Тест()\n    Настройки.ПодключитьОбработчик()\n;\n",
    )
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


def test_base_bound_by_the_caller_is_skipped(tmp_path):
    diags = _module_project(
        tmp_path, _CALLEE_LOCAL,
        "метод Тест()\n    пер Настройки = НовыйОбъект()\n    Настройки.Прочитать()\n;\n",
    )
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


def test_twin_module_names_make_the_name_unusable(tmp_path):
    (tmp_path / "вложенная").mkdir()
    (tmp_path / "вложенная" / "Настройки.xbsl").write_text(
        "метод Прочитать(): Строка\n    возврат \"\"\n;\n", encoding="utf-8",
    )
    diags = _module_project(
        tmp_path, _CALLEE_LOCAL, "метод Тест()\n    Настройки.Прочитать()\n;\n",
    )
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


def test_dotted_stem_is_not_callable_by_name(tmp_path):
    # an object module (Имя.Объект.xbsl) is not reachable as `Имя.Метод(...)`
    diags = _module_project(
        tmp_path, _CALLEE_LOCAL, "метод Тест()\n    Настройки.Прочитать()\n;\n",
        callee_name="Настройки.Объект",
    )
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


def test_qualified_name_is_skipped(tmp_path):
    diags = _module_project(
        tmp_path, _CALLEE_LOCAL,
        "метод Тест()\n    Подсистема::Настройки.Прочитать()\n;\n",
    )
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


def test_method_declared_twice_in_the_target_is_dropped(tmp_path):
    diags = _module_project(
        tmp_path,
        "метод Прочитать(): Строка\n    возврат \"\"\n;\n"
        "@ВПодсистеме\nметод Прочитать(Ключ: Строка): Строка\n    возврат Ключ\n;\n",
        "метод Тест()\n    Настройки.Прочитать()\n;\n",
    )
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


# --- Both spellings ---------------------------------------------------------------
#
# The sources are bilingual and a project mixes the forms freely, even within one line.
# While only the Russian annotations were listed, an English one read as NO annotation, the
# default local visibility was assumed, and a run over a foreign reference project answered
# 602 false "visible in its own module only".


@pytest.mark.parametrize("annotation", ["InSubsystem", "InProject", "InType", "Global"])
def test_english_wide_visibility_passes(tmp_path, annotation):
    diags = _module_project(
        tmp_path,
        f"@{annotation}\nметод Прочитать()\n    возврат\n;\n",
        "метод Тест()\n    Настройки.Прочитать()\n;\n",
    )
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


def test_english_local_visibility_is_still_flagged(tmp_path):
    diags = _module_project(
        tmp_path,
        "@Local\nметод Прочитать()\n    возврат\n;\n",
        "метод Тест()\n    Настройки.Прочитать()\n;\n",
    )
    assert _has(diags, MODULE_RULE), [d.message for d in diags]


def test_the_spellings_mix_within_one_declaration(tmp_path):
    diags = _module_project(
        tmp_path,
        "@OnServer @ДоступноСКлиента\n@InSubsystem\n"
        "статический метод Прочитать()\n    возврат\n;\n",
        "метод Тест()\n    Настройки.Прочитать()\n;\n",
    )
    assert not _has(diags, MODULE_RULE), [d.message for d in diags]


def test_english_wide_visibility_passes_across_components(tmp_path):
    # The project is assembled here rather than through the shared helper: renaming that
    # helper would pull the whole file into the language guard's diff.
    (tmp_path / "Страница.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Страница\n", encoding="utf-8"
    )
    (tmp_path / "Страница.xbsl").write_text(
        "@InSubsystem\nметод Загрузить()\n    возврат\n;\n", encoding="utf-8"
    )
    (tmp_path / "Роутер.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Роутер\nСодержимое:\n"
        "    -\n        Тип: Страница\n        Имя: Страница\n", encoding="utf-8"
    )
    (tmp_path / "Роутер.xbsl").write_text(
        "метод Открыть()\n    Компоненты.Страница.Загрузить()\n;\n", encoding="utf-8"
    )
    assert not _has(engine.run(discover([str(tmp_path)]), select={RULE}))
