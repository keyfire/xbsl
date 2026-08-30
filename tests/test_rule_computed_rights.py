"""Checks of code/permission-right-not-computable (xbsl/rules/access_control.py).

Every test builds a small project in tmp_path and runs the engine - the rule is
project-scoped and its findings depend on the pairing of the yaml with the module and on
the call closure, so calling the reduce function directly would test nothing real.
"""

import pytest

from xbsl import engine
from xbsl.cli import discover

RULE = "code/permission-right-not-computable"

# A register computes `Update` alone: `Read` is settled statically, the default covers
# the rest of the universe - the exact shape of the measured live failure.
_REGISTER_YAML = """ВидЭлемента: РегистрСведений
Ид: 12312312-1231-1231-1231-123123123123
Имя: Переводы
КонтрольДоступа:
    Разрешения:
        Чтение: РазрешеноВсем
        ПоУмолчанию: РазрешенияВычисляются
Измерения:
    -
        Ид: 12312312-0000-0000-0000-000000000001
        Имя: Код
        Тип: Строка
"""

_HANDLER = """@Обработчик
метод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>
    возврат [новый РазрешениеДоступа([новый КлючДоступаЗаписей.Объект()],
        [{rights}])]
;
"""


def _run(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE})
            if d.rule_id == RULE]


def _register(tmp_path, module):
    return _run(tmp_path, {"Переводы.yaml": _REGISTER_YAML, "Переводы.xbsl": module})


@pytest.mark.needs_data
def test_static_right_granted_directly_flagged(tmp_path):
    hits = _register(
        tmp_path,
        _HANDLER.format(rights="Сущность.Право.Чтение, Сущность.Право.Изменение"))
    assert len(hits) == 1
    assert "'Чтение'" in hits[0].message
    assert hits[0].path.endswith("Переводы.xbsl")
    assert hits[0].severity.value == "error"


@pytest.mark.needs_data
def test_computable_right_granted_ok(tmp_path):
    assert not _register(tmp_path, _HANDLER.format(rights="Сущность.Право.Изменение"))


@pytest.mark.needs_data
def test_undergranting_ok(tmp_path):
    """A computed permission nobody returns is legal - seeding-time records live so."""
    module = """@Обработчик
метод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>
    возврат новый Массив<РазрешениеДоступа>()
;
"""
    assert not _register(tmp_path, module)


@pytest.mark.needs_data
def test_delegated_grant_flagged_in_the_helper(tmp_path):
    """Rights collected one hop away: the finding sits at the constructor in the helper
    module and names both the entity and the delegation it came through."""
    handler = """@Обработчик
метод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>
    возврат Права.РазрешенияРегистра()
;
"""
    helper = """@ВПроекте
@НаСервере
метод РазрешенияРегистра(): Массив<РазрешениеДоступа>
    возврат [новый РазрешениеДоступа([новый КлючДоступаЗаписей.Объект()],
        [Сущность.Право.Чтение])]
;
"""
    hits = _run(tmp_path, {
        "Переводы.yaml": _REGISTER_YAML, "Переводы.xbsl": handler, "Права.xbsl": helper,
    })
    assert len(hits) == 1
    assert hits[0].path.endswith("Права.xbsl")
    assert "Переводы" in hits[0].message
    assert "Права.РазрешенияРегистра" in hits[0].message


@pytest.mark.needs_data
def test_no_access_control_block_means_nothing_is_computable(tmp_path):
    yaml = """ВидЭлемента: Справочник
Ид: 32132132-3213-3213-3213-321321321321
Имя: Кэш
"""
    hits = _run(tmp_path, {
        "Кэш.yaml": yaml,
        "Кэш.xbsl": _HANDLER.format(rights="Сущность.Право.Чтение"),
    })
    assert len(hits) == 1 and "ни одно право" in hits[0].message


@pytest.mark.needs_data
def test_http_service_call_namespace(tmp_path):
    yaml = """ВидЭлемента: HttpСервис
Ид: 45645645-4564-4564-4564-456456456456
Имя: Сервис
КонтрольДоступа:
    Разрешения:
        Вызов: {value}
"""
    module = _HANDLER.format(rights="HttpСервисПраво.Вызов")
    hits = _run(tmp_path, {
        "Сервис.yaml": yaml.format(value="РазрешеноВсем"), "Сервис.xbsl": module,
    })
    assert len(hits) == 1 and "Вызов" in hits[0].message

    (tmp_path / "Сервис.yaml").write_text(
        yaml.format(value="РазрешенияВычисляются"), encoding="utf-8")
    assert not _run(tmp_path, {})


@pytest.mark.needs_data
def test_english_sources_judged_too(tmp_path):
    yaml = """ElementKind: Catalog
Id: 65465465-6546-6546-6546-654654654654
Name: Wares
AccessControl:
    Permissions:
        Read: PermitEveryone
        Default: PermissionsComputed
"""
    module = """@Handler
method ComputeAccessPermissions(): Array<AccessPermission>
    return [new AccessPermission([new AdministratorAccessKey.Object()],
        [Entity.Privilege.Read, Entity.Privilege.Update])]
;
"""
    hits = _run(tmp_path, {"Wares.yaml": yaml, "Wares.xbsl": module})
    assert len(hits) == 1
    assert "Read" in hits[0].message and "Wares" in hits[0].message


@pytest.mark.needs_data
def test_a_kind_without_access_control_is_not_judged(tmp_path):
    """A rights element declares the same-named handler for a different mechanism - its
    kind has no access control in the metamodel, so there is no universe to judge by."""
    yaml = """ВидЭлемента: ПравоНаДействие
Ид: 78978978-7897-7897-7897-789789789789
Имя: ПравоПробы
"""
    hits = _run(tmp_path, {
        "ПравоПробы.yaml": yaml,
        "ПравоПробы.xbsl": _HANDLER.format(rights="Сущность.Право.Чтение"),
    })
    assert not hits


@pytest.mark.needs_data
def test_context_extension_is_not_a_grant(tmp_path):
    """`КонтекстДоступа.Дополнить` names the same rights without granting them for the
    entity - inside a handler or out, only a constructor argument counts."""
    module = """@Обработчик
метод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>
    исп КонтекстДоступа.Дополнить(Тип<Переводы.Объект>, [Сущность.Право.Чтение])
    возврат [новый РазрешениеДоступа([новый КлючДоступаЗаписей.Объект()],
        [Сущность.Право.Изменение])]
;

@ВПроекте
метод Наполнение()
    исп КонтекстДоступа.Дополнить(Тип<Переводы.Объект>, [Сущность.Право.Чтение])
;
"""
    assert not _register(tmp_path, module)


@pytest.mark.needs_data
def test_call_cycle_terminates(tmp_path):
    """Two methods calling each other must not hang the closure."""
    module = """@Обработчик
метод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>
    возврат Первый()
;

@НаСервере
метод Первый(): Массив<РазрешениеДоступа>
    возврат Второй()
;

@НаСервере
метод Второй(): Массив<РазрешениеДоступа>
    если Ложь
        возврат Первый()
    ;
    возврат [новый РазрешениеДоступа([новый КлючДоступаЗаписей.Объект()],
        [Сущность.Право.Изменение])]
;
"""
    assert not _register(tmp_path, module)


@pytest.mark.needs_data
def test_both_computed_values_count(tmp_path):
    """The computed set is the union of both enum values: a per-object permission is
    served by the common handler too."""
    yaml = _REGISTER_YAML.replace(
        "Чтение: РазрешеноВсем", "Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта")
    hits = _run(tmp_path, {
        "Переводы.yaml": yaml,
        "Переводы.xbsl": _HANDLER.format(
            rights="Сущность.Право.Чтение, Сущность.Право.Изменение"),
    })
    assert not hits
