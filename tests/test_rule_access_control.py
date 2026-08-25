"""Checks of the per-object access control rules (xbsl/rules/access_control.py)."""

from xbsl import engine
from xbsl.cli import discover

COMMON = "code/per-object-permissions-need-common"
FIELD = "code/permission-field-not-declared"

_YAML = """ВидЭлемента: Справочник
Ид: 12121212-1212-1212-1212-121212121212
Имя: Записи
КонтрольДоступа:
{control}Реквизиты:
    -
        Ид: 12121212-0000-0000-0000-000000000001
        Имя: Владелец
        Тип: Строка
"""

_CONTROL = """    РасчетРазрешенийПо:
        - Владелец
    Разрешения:
        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта
"""

_COMMON_HANDLER = """@Обработчик
метод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>
    возврат новый Массив<РазрешениеДоступа>()
;

"""


def _has(diags, rule_id):
    return any(d.rule_id == rule_id for d in diags)


def _pair(tmp_path, module, control=_CONTROL, select=None):
    (tmp_path / "Записи.yaml").write_text(_YAML.format(control=control), encoding="utf-8")
    (tmp_path / "Записи.xbsl").write_text(module, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select=select or {COMMON, FIELD})


def _per_object(body):
    return (
        "@Обработчик\n"
        "метод ВычислитьРазрешенияДоступаДляОбъектов(Данные: ЧитаемыйМассив<Записи.Объект>)\n"
        "    для Запись из Данные\n"
        f"        {body}\n"
        "    ;\n"
        ";\n"
    )


# --- code/per-object-permissions-need-common -------------------------------------------

def test_common_handler_missing_flagged(tmp_path):
    d = _pair(tmp_path, _per_object("возврат"))
    assert any(x.rule_id == COMMON and "Записи" in x.message for x in d)


def test_common_handler_present_ok(tmp_path):
    d = _pair(tmp_path, _COMMON_HANDLER + _per_object("возврат"))
    assert not _has(d, COMMON)


def test_object_without_per_object_rights_not_checked(tmp_path):
    """Nothing asks for a per-object calculation, so nothing requires the common one."""
    d = _pair(tmp_path, _per_object("возврат"), control="    РасчетРазрешенийПо:\n        - Владелец\n")
    assert not _has(d, COMMON)


def test_module_without_any_handler_flagged(tmp_path):
    """A module that declares NEITHER handler is the same defect, not an unknown case."""
    d = _pair(tmp_path, "// пока пусто\n")
    assert _has(d, COMMON)


def test_common_handler_missing_english_flagged(tmp_path):
    (tmp_path / "Records.yaml").write_text(
        "ElementKind: Catalog\n"
        "Ид: 12121212-1212-1212-1212-121212121213\n"
        "Name: Records\n"
        "AccessControl:\n"
        "    PermissionsCalculatedBy:\n"
        "        - Owner\n"
        "    Permissions:\n"
        "        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта\n",
        encoding="utf-8",
    )
    (tmp_path / "Records.xbsl").write_text("// пока пусто\n", encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={COMMON})
    assert any(x.rule_id == COMMON and "Records" in x.message for x in d)


# --- code/permission-field-not-declared ------------------------------------------------

def test_undeclared_record_field_flagged(tmp_path):
    d = _pair(tmp_path, _COMMON_HANDLER + _per_object("знч Х = Запись.Пользователь"))
    assert any(x.rule_id == FIELD and "Пользователь" in x.message for x in d)


def test_declared_record_field_ok(tmp_path):
    d = _pair(tmp_path, _COMMON_HANDLER + _per_object("знч Х = Запись.Владелец"))
    assert not _has(d, FIELD)


def test_declared_field_through_entity_flagged(tmp_path):
    """`Сущность.Владелец` is the record read through the wrong root."""
    d = _pair(tmp_path, _COMMON_HANDLER + _per_object("знч Х = Сущность.Владелец"))
    assert any(x.rule_id == FIELD and "Запись.Владелец" in x.message for x in d)


def test_entity_namespace_ok(tmp_path):
    """`Сущность.Право` is the platform namespace and appears in the same handler."""
    d = _pair(tmp_path, _COMMON_HANDLER + _per_object("знч Х = Сущность.Право.Чтение"))
    assert not _has(d, FIELD)


def test_record_outside_the_handler_not_checked(tmp_path):
    """A variable named `Запись` in another method is not this record."""
    d = _pair(
        tmp_path,
        _COMMON_HANDLER + _per_object("возврат")
        + "\n@ВПроекте\nметод Иное(Запись: Строка): Строка\n    возврат Запись.Пользователь\n;\n",
    )
    assert not _has(d, FIELD)


# --- code/permission-handlers-need-recalc ----------------------------------------------

RECALC = "code/permission-handlers-need-recalc"

_RECALC_CALL = (
    "@ВПроекте\n"
    "метод Обновление()\n"
    "    Записи.ПересчитатьРазрешенияДоступа()\n"
    ";\n"
)


def _recalc_project(tmp_path, module, extra=None):
    (tmp_path / "Записи.yaml").write_text(_YAML.format(control=_CONTROL), encoding="utf-8")
    (tmp_path / "Записи.xbsl").write_text(module, encoding="utf-8")
    for name, text in (extra or {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={RECALC})


def test_handler_without_recalc_flagged(tmp_path):
    """The platform never calls the handler by itself: a project that recomputes nowhere
    ships permission edits that silently do not act - the very defect of the registry."""
    d = _recalc_project(tmp_path, _COMMON_HANDLER)
    assert any(x.rule_id == RECALC and "Записи" in x.message for x in d)


def test_recalc_anywhere_in_the_project_silences(tmp_path):
    d = _recalc_project(tmp_path, _COMMON_HANDLER, {"Проект.xbsl": _RECALC_CALL})
    assert not _has(d, RECALC)


def test_recalc_for_objects_counts_too(tmp_path):
    call = _RECALC_CALL.replace(
        "ПересчитатьРазрешенияДоступа()", "ПересчитатьРазрешенияДоступаДляОбъектов()"
    )
    d = _recalc_project(tmp_path, _COMMON_HANDLER, {"Проект.xbsl": call})
    assert not _has(d, RECALC)


def test_a_generic_loop_receiver_stands_the_rule_down(tmp_path):
    """The documentation itself shows the loop form - the receiver is a loop variable, and
    what such a loop covers cannot be told, so the rule does not guess."""
    loop = (
        "@ВПроекте\n"
        "метод Обновление()\n"
        "    для Сервис из HttpСервисы\n"
        "        Сервис.ПересчитатьРазрешенияДоступа()\n"
        "    ;\n"
        ";\n"
    )
    d = _recalc_project(tmp_path, _COMMON_HANDLER, {"Проект.xbsl": loop})
    assert not _has(d, RECALC)


def test_a_rights_element_is_not_judged(tmp_path):
    """A rights element declares the same-named handler yet has no recompute method at all:
    demanding the call would demand code that cannot compile."""
    (tmp_path / "ПравоНаПробу.yaml").write_text(
        "ВидЭлемента: ПравоНаДействие\n"
        "Ид: 34343434-3434-3434-3434-343434343434\n"
        "Имя: ПравоНаПробу\n",
        encoding="utf-8",
    )
    (tmp_path / "ПравоНаПробу.xbsl").write_text(_COMMON_HANDLER, encoding="utf-8")
    d = engine.run(discover([str(tmp_path)]), select={RECALC})
    assert not _has(d, RECALC)


def test_recalc_rule_speaks_both_spellings(tmp_path):
    (tmp_path / "Records.yaml").write_text(
        "ElementKind: Catalog\nИд: 56565656-5656-5656-5656-565656565656\nName: Records\n",
        encoding="utf-8",
    )
    (tmp_path / "Records.xbsl").write_text(
        "@Обработчик\nметод ComputeAccessPermissions(): Массив<РазрешениеДоступа>\n"
        "    возврат новый Массив<РазрешениеДоступа>()\n;\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={RECALC})
    assert any(x.rule_id == RECALC and "Records" in x.message for x in d)

    (tmp_path / "Проект.xbsl").write_text(
        "@ВПроекте\nметод Обновление()\n    Records.RecomputeAccessPermissions()\n;\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={RECALC})
    assert not _has(d, RECALC)


# --- code/access-context-read-noop ------------------------------------------------------------

NOOP = "code/access-context-read-noop"

_EVERYONE_YAML = """ВидЭлемента: Справочник
Ид: 34343434-3434-3434-3434-343434343434
Имя: Заметки
КонтрольДоступа:
    Разрешения:
        Чтение: {read}
"""


def _noop(tmp_path, module: str, read: str = "РазрешеноВсем"):
    (tmp_path / "Заметки.yaml").write_text(_EVERYONE_YAML.format(read=read), encoding="utf-8")
    (tmp_path / "Работа.xbsl").write_text(module, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)]), select={NOOP}) if d.rule_id == NOOP]


_ONLY_READ = """метод Прочитать()
    исп КонтекстДоступа.Дополнить(Тип<Заметки.Объект>, [Сущность.Право.Чтение])
;
"""

_READ_AND_WRITE = """метод Записать()
    исп КонтекстДоступа.Дополнить(Тип<Заметки.Объект>,
        [Сущность.Право.Чтение, Сущность.Право.Изменение])
;
"""


def test_read_extension_of_an_open_type_is_flagged(tmp_path):
    hits = _noop(tmp_path, _ONLY_READ)
    assert len(hits) == 1 and "Заметки" in hits[0].message
    assert (hits[0].line, hits[0].col) == (2, 72)  # the right itself, not the call


def test_a_call_carrying_only_that_right_is_called_dead(tmp_path):
    assert "снять" in _noop(tmp_path, _ONLY_READ)[0].message


def test_a_call_carrying_other_rights_names_the_right_alone(tmp_path):
    hits = _noop(tmp_path, _READ_AND_WRITE)
    assert len(hits) == 1 and "только Чтение" in hits[0].message


def test_a_type_that_does_not_open_reading_is_left_alone(tmp_path):
    assert not _noop(tmp_path, _ONLY_READ, read="РазрешеноАутентифицированным")


def test_computed_permissions_are_left_alone(tmp_path):
    assert not _noop(tmp_path, _ONLY_READ, read="РазрешенияВычисляютсяДляКаждогоОбъекта")


def test_an_extension_without_the_read_right_is_left_alone(tmp_path):
    module = """метод Записать()
    исп КонтекстДоступа.Дополнить(Тип<Заметки.Объект>, [Сущность.Право.Изменение])
;
"""
    assert not _noop(tmp_path, module)


def test_a_type_of_another_project_is_left_alone(tmp_path):
    """The judged name has to be an object of THIS project - the yaml is what decides."""
    module = """метод Прочитать()
    исп КонтекстДоступа.Дополнить(Тип<Чужой.Объект>, [Сущность.Право.Чтение])
;
"""
    assert not _noop(tmp_path, module)


def test_english_sources_are_judged_too(tmp_path):
    (tmp_path / "Notes.yaml").write_text(
        "ElementKind: Catalog\nId: 34343434-3434-3434-3434-343434343435\nName: Notes\n"
        "AccessControl:\n    Permissions:\n        Read: PermitEveryone\n",
        encoding="utf-8",
    )
    (tmp_path / "Work.xbsl").write_text(
        "method Read()\n    use AccessContext.Append(Type<Notes.Object>, [Entity.Privilege.Read])\n;\n",
        encoding="utf-8",
    )
    hits = [d for d in engine.run(discover([str(tmp_path)]), select={NOOP}) if d.rule_id == NOOP]
    assert len(hits) == 1 and "Notes" in hits[0].message
