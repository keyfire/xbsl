"""Checks of the environment rule family (xbsl/rules/environment.py)."""

from xbsl import engine
from xbsl.cli import discover


def _has(diags, rule_id):
    return any(d.rule_id == rule_id for d in diags)


# --- code/server-call-from-handler -----------------------------------------------------

_ФОРМА_YAML = (
    "ВидЭлемента: КомпонентИнтерфейса\nИмя: Форма\nСодержимое:\n    -\n"
    "        Тип: Кнопка\n        Обработчик: ПриНажатии\n"
)


def _форма(tmp_path, module, yaml=_ФОРМА_YAML):
    (tmp_path / "Форма.yaml").write_text(yaml, encoding="utf-8")
    (tmp_path / "Форма.xbsl").write_text(module, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={"code/server-call-from-handler"})


def test_server_call_from_handler_flagged(tmp_path):
    d = _форма(
        tmp_path,
        "метод ПриНажатии()\n"
        "    Сохранить()\n"
        ";\n\n"
        "@НаСервере\n"
        "метод Сохранить()\n"
        "    возврат\n"
        ";\n",
    )
    assert any(
        x.rule_id == "code/server-call-from-handler" and "Сохранить" in x.message
        for x in d
    )


def test_handler_with_trailing_comment_flagged(tmp_path):
    # a comment after the handler name in yaml does not take it out of the check
    d = _форма(
        tmp_path,
        "метод ПриНажатии()\n"
        "    Сохранить()\n"
        ";\n\n"
        "@НаСервере\n"
        "метод Сохранить()\n"
        "    возврат\n"
        ";\n",
        yaml=_ФОРМА_YAML.replace("Обработчик: ПриНажатии", "Обработчик: ПриНажатии # клик"),
    )
    assert _has(d, "code/server-call-from-handler")


def test_server_call_with_client_access_ok(tmp_path):
    d = _форма(
        tmp_path,
        "метод ПриНажатии()\n"
        "    Сохранить()\n"
        ";\n\n"
        "@НаСервере @ДоступноСКлиента\n"
        "статический метод Сохранить()\n"
        "    возврат\n"
        ";\n",
    )
    assert not _has(d, "code/server-call-from-handler")


def test_server_handler_itself_ok(tmp_path):
    # the handler itself runs on the server - calling a server method is correct
    d = _форма(
        tmp_path,
        "@НаСервере\n"
        "метод ПриНажатии()\n"
        "    Сохранить()\n"
        ";\n\n"
        "@НаСервере\n"
        "метод Сохранить()\n"
        "    возврат\n"
        ";\n",
    )
    assert not _has(d, "code/server-call-from-handler")


def test_annotation_handler_flagged(tmp_path):
    # the handler is declared via the @Обработчик annotation, not in yaml
    d = _форма(
        tmp_path,
        "@Обработчик\n"
        "метод ПослеСоздания()\n"
        "    Загрузить()\n"
        ";\n\n"
        "@НаСервере\n"
        "метод Загрузить()\n"
        "    возврат\n"
        ";\n",
        yaml="ВидЭлемента: КомпонентИнтерфейса\nИмя: Форма\n",
    )
    assert any("Загрузить" in x.message for x in d)


def test_member_call_not_flagged(tmp_path):
    # 'Объект.Сохранить()' is another object's method, not a bare module-level name
    d = _форма(
        tmp_path,
        "метод ПриНажатии(Объект: Структура)\n"
        "    Объект.Сохранить()\n"
        ";\n\n"
        "@НаСервере\n"
        "метод Сохранить()\n"
        "    возврат\n"
        ";\n",
    )
    assert not _has(d, "code/server-call-from-handler")


def test_shadowed_name_not_flagged(tmp_path):
    # a local variable shadows the server method name
    d = _форма(
        tmp_path,
        "метод ПриНажатии(Данные: Структура)\n"
        "    знч Сохранить = Данные.Действие\n"
        "    Сохранить()\n"
        ";\n\n"
        "@НаСервере\n"
        "метод Сохранить()\n"
        "    возврат\n"
        ";\n",
    )
    assert not _has(d, "code/server-call-from-handler")


def test_call_outside_handler_not_flagged(tmp_path):
    # the rule does not touch a call from an ordinary (non-handler) client method
    d = _форма(
        tmp_path,
        "метод Вспомогательный()\n"
        "    Сохранить()\n"
        ";\n\n"
        "@НаСервере\n"
        "метод Сохранить()\n"
        "    возврат\n"
        ";\n",
        yaml="ВидЭлемента: КомпонентИнтерфейса\nИмя: Форма\n",
    )
    assert not _has(d, "code/server-call-from-handler")


def test_call_in_next_method_not_attributed_to_handler(tmp_path):
    # a call in the method following the handler is not attributed to the handler body
    d = _форма(
        tmp_path,
        "метод ПриНажатии()\n"
        "    возврат\n"
        ";\n\n"
        "метод Другой()\n"
        "    Сохранить()\n"
        ";\n\n"
        "@НаСервере\n"
        "метод Сохранить()\n"
        "    возврат\n"
        ";\n",
    )
    assert not _has(d, "code/server-call-from-handler")


def test_non_form_module_not_checked(tmp_path):
    (tmp_path / "Модуль.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: КлиентИСервер\n",
        encoding="utf-8",
    )
    (tmp_path / "Модуль.xbsl").write_text(
        "@Обработчик\n"
        "метод ПриНажатии()\n"
        "    Сохранить()\n"
        ";\n\n"
        "@НаСервере\n"
        "метод Сохранить()\n"
        "    возврат\n"
        ";\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={"code/server-call-from-handler"})
    assert not _has(d, "code/server-call-from-handler")


# --- code/client-annotation-in-server-module -------------------------------------------

def _общий(tmp_path, env, module):
    (tmp_path / "Модуль.yaml").write_text(
        f"ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: {env}\n", encoding="utf-8"
    )
    (tmp_path / "Модуль.xbsl").write_text(module, encoding="utf-8")
    return engine.run(
        discover([str(tmp_path)]), select={"code/client-annotation-in-server-module"}
    )


def test_client_access_in_server_module_flagged(tmp_path):
    d = _общий(
        tmp_path, "Сервер",
        "@НаСервере @ДоступноСКлиента\nстатический метод Ф()\n    возврат\n;\n",
    )
    assert any(
        x.rule_id == "code/client-annotation-in-server-module"
        and "ДоступноСКлиента" in x.message
        for x in d
    )


def test_client_annotation_in_server_module_flagged(tmp_path):
    d = _общий(
        tmp_path, "Сервер",
        "@НаСервере @НаКлиенте\nструктура Данные\n    пер Имя: Строка?\n;\n",
    )
    assert any("НаКлиенте" in x.message for x in d)


def test_server_annotation_in_server_module_ok(tmp_path):
    d = _общий(tmp_path, "Сервер", "@НаСервере\nметод Ф()\n    возврат\n;\n")
    assert not _has(d, "code/client-annotation-in-server-module")


def test_client_access_in_mixed_module_ok(tmp_path):
    d = _общий(
        tmp_path, "КлиентИСервер",
        "@НаСервере @ДоступноСКлиента\nстатический метод Ф()\n    возврат\n;\n",
    )
    assert not _has(d, "code/client-annotation-in-server-module")


def test_module_without_environment_not_checked(tmp_path):
    (tmp_path / "Модуль.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\n", encoding="utf-8"
    )
    (tmp_path / "Модуль.xbsl").write_text(
        "@НаСервере @ДоступноСКлиента\nстатический метод Ф()\n    возврат\n;\n",
        encoding="utf-8",
    )
    d = engine.run(
        discover([str(tmp_path)]), select={"code/client-annotation-in-server-module"}
    )
    assert not _has(d, "code/client-annotation-in-server-module")


# --- code/client-available-needs-context -----------------------------------------------

_RULE_CTX = "code/client-available-needs-context"


def _component(tmp_path, module, yaml="ВидЭлемента: КомпонентИнтерфейса\nИмя: Панель\n"):
    (tmp_path / "Панель.yaml").write_text(yaml, encoding="utf-8")
    (tmp_path / "Панель.xbsl").write_text(module, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={_RULE_CTX})


def test_client_available_without_context_flagged(tmp_path):
    d = _component(
        tmp_path,
        "@НаСервере @ДоступноСКлиента\nметод Прочитать()\n    возврат\n;\n",
    )
    assert any(x.rule_id == _RULE_CTX and "Прочитать" in x.message for x in d)


def test_client_available_static_ok(tmp_path):
    d = _component(
        tmp_path,
        "@НаСервере @ДоступноСКлиента\nстатический метод Прочитать()\n    возврат\n;\n",
    )
    assert not _has(d, _RULE_CTX)


def test_client_available_contextual_ok(tmp_path):
    d = _component(
        tmp_path,
        "@НаСервере @Контекстный @ДоступноСКлиента\nметод Прочитать()\n    возврат\n;\n",
    )
    assert not _has(d, _RULE_CTX)


def test_client_available_in_common_module_not_checked(tmp_path):
    """A common module is a singleton type – the plain form is correct there."""
    (tmp_path / "Модуль.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: КлиентИСервер\n",
        encoding="utf-8",
    )
    (tmp_path / "Модуль.xbsl").write_text(
        "@НаСервере @ДоступноСКлиента\nметод Прочитать()\n    возврат\n;\n",
        encoding="utf-8",
    )
    d = engine.run(discover([str(tmp_path)]), select={_RULE_CTX})
    assert not _has(d, _RULE_CTX)


def test_client_available_english_spelling_flagged(tmp_path):
    d = _component(
        tmp_path,
        "@OnServer @AvailableFromClient\nmethod Read()\n    возврат\n;\n",
        yaml="ElementKind: InterfaceComponent\nИмя: Панель\n",
    )
    assert any(x.rule_id == _RULE_CTX and "Read" in x.message for x in d)


def test_client_available_english_contextual_ok(tmp_path):
    d = _component(
        tmp_path,
        "@OnServer @Contextual @AvailableFromClient\nmethod Read()\n    возврат\n;\n",
        yaml="ElementKind: InterfaceComponent\nИмя: Панель\n",
    )
    assert not _has(d, _RULE_CTX)


def test_client_available_in_structure_member_not_checked(tmp_path):
    """Only module-level methods are judged – a structure member belongs to its own type."""
    d = _component(
        tmp_path,
        "структура Данные\n"
        "    пер Имя: Строка?\n"
        "    @НаСервере @ДоступноСКлиента\n"
        "    метод Прочитать()\n"
        "        возврат\n"
        "    ;\n"
        ";\n",
    )
    assert not _has(d, _RULE_CTX)


def test_client_available_broken_module_not_checked(tmp_path):
    """A file the parser cannot read is code/parse-error territory."""
    d = _component(
        tmp_path,
        "@НаСервере @ДоступноСКлиента\nметод Прочитать(\n",
    )
    assert not _has(d, _RULE_CTX)


# --- code/server-module-in-client-context ----------------------------------------------

_RULE_SRV = "code/server-module-in-client-context"

_CALLER = (
    "@Обработчик\nметод ПриНажатии()\n"
    "    СерверныйМодуль.Прочитать()\n"
    ";\n"
)


def _environment_pair(tmp_path, caller_yaml, caller_module=_CALLER,
                    server_yaml="ВидЭлемента: ОбщийМодуль\nИмя: СерверныйМодуль\n"
                                "Окружение: Сервер\n"):
    (tmp_path / "СерверныйМодуль.yaml").write_text(server_yaml, encoding="utf-8")
    (tmp_path / "СерверныйМодуль.xbsl").write_text(
        "@НаСервере @ВПроекте\nметод Прочитать(): Строка\n    возврат \"\"\n;\n",
        encoding="utf-8",
    )
    (tmp_path / "Панель.yaml").write_text(caller_yaml, encoding="utf-8")
    (tmp_path / "Панель.xbsl").write_text(caller_module, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={_RULE_SRV})


_COMPONENT_YAML = "ВидЭлемента: КомпонентИнтерфейса\nИмя: Панель\n"


def test_server_module_from_client_handler_flagged(tmp_path):
    d = _environment_pair(tmp_path, _COMPONENT_YAML)
    assert any(x.rule_id == _RULE_SRV and "СерверныйМодуль.Прочитать" in x.message for x in d)


def test_server_module_from_server_method_ok(tmp_path):
    """A method annotated `@НаСервере` executes where the type does exist."""
    d = _environment_pair(
        tmp_path, _COMPONENT_YAML,
        "@НаСервере @Контекстный\nметод Загрузить()\n"
        "    СерверныйМодуль.Прочитать()\n;\n",
    )
    assert not _has(d, _RULE_SRV)


def test_server_module_from_plain_method_flagged(tmp_path):
    """The twin of the test above: the same method without `@НаСервере` is judged, so the
    silence there comes from the annotation and not from the method being unnamed as a
    handler."""
    d = _environment_pair(
        tmp_path, _COMPONENT_YAML,
        "@Контекстный\nметод Загрузить()\n"
        "    СерверныйМодуль.Прочитать()\n;\n",
    )
    assert any(x.rule_id == _RULE_SRV and "Загрузить" in x.message for x in d)


def test_mixed_environment_module_ok(tmp_path):
    d = _environment_pair(
        tmp_path, _COMPONENT_YAML,
        server_yaml="ВидЭлемента: ОбщийМодуль\nИмя: СерверныйМодуль\n"
                    "Окружение: КлиентИСервер\n",
    )
    assert not _has(d, _RULE_SRV)


def test_server_kind_caller_not_checked(tmp_path):
    """A catalog module lives on the server – the access is legal there."""
    d = _environment_pair(tmp_path, "ВидЭлемента: Справочник\nИмя: Панель\n")
    assert not _has(d, _RULE_SRV)


def test_client_common_module_caller_flagged(tmp_path):
    d = _environment_pair(
        tmp_path,
        "ВидЭлемента: ОбщийМодуль\nИмя: Панель\nОкружение: Клиент\n",
        "метод Показать()\n    СерверныйМодуль.Прочитать()\n;\n",
    )
    assert any(x.rule_id == _RULE_SRV for x in d)


def test_server_module_english_spelling_flagged(tmp_path):
    d = _environment_pair(
        tmp_path,
        "ElementKind: InterfaceComponent\nName: Панель\n",
        server_yaml="ElementKind: CommonModule\nName: СерверныйМодуль\n"
                    "Environment: Server\n",
    )
    assert any(x.rule_id == _RULE_SRV for x in d)


def test_server_module_name_shadowed_ok(tmp_path):
    """A local bound to the name is not the module."""
    d = _environment_pair(
        tmp_path, _COMPONENT_YAML,
        "@Обработчик\nметод ПриНажатии()\n"
        "    знч СерверныйМодуль = ЭтоНеМодуль()\n"
        "    СерверныйМодуль.Прочитать()\n"
        ";\n",
    )
    assert not _has(d, _RULE_SRV)


def test_server_module_as_member_ok(tmp_path):
    """`х.СерверныйМодуль.Прочитать()` is a member of another object, not the module."""
    d = _environment_pair(
        tmp_path, _COMPONENT_YAML,
        "@Обработчик\nметод ПриНажатии()\n"
        "    Контейнер.СерверныйМодуль.Прочитать()\n"
        ";\n",
    )
    assert not _has(d, _RULE_SRV)


# --- code/client-module-in-http-service ------------------------------------------------

def _сервис(tmp_path, env, client_module, service_module):
    (tmp_path / "МодульКлиент.yaml").write_text(
        f"ВидЭлемента: ОбщийМодуль\nИмя: МодульКлиент\nОкружение: {env}\n",
        encoding="utf-8",
    )
    (tmp_path / "МодульКлиент.xbsl").write_text(client_module, encoding="utf-8")
    (tmp_path / "Апи.yaml").write_text(
        "ВидЭлемента: HttpСервис\nИмя: Апи\n", encoding="utf-8"
    )
    (tmp_path / "Апи.xbsl").write_text(service_module, encoding="utf-8")
    return engine.run(
        discover([str(tmp_path)]), select={"code/client-module-in-http-service"}
    )


_КЛИЕНТСКИЙ_ХЕЛПЕР = "статический метод Хелпер(): Строка\n    возврат \"х\"\n;\n"


def test_client_module_call_in_http_service_flagged(tmp_path):
    d = _сервис(
        tmp_path, "Клиент", _КЛИЕНТСКИЙ_ХЕЛПЕР,
        "метод Обработать()\n    знч Х = МодульКлиент.Хелпер()\n;\n",
    )
    assert any(
        x.rule_id == "code/client-module-in-http-service"
        and "МодульКлиент.Хелпер" in x.message
        for x in d
    )


def test_mixed_module_call_in_http_service_ok(tmp_path):
    d = _сервис(
        tmp_path, "КлиентИСервер", _КЛИЕНТСКИЙ_ХЕЛПЕР,
        "метод Обработать()\n    знч Х = МодульКлиент.Хелпер()\n;\n",
    )
    assert not _has(d, "code/client-module-in-http-service")


def test_server_annotated_member_ok(tmp_path):
    # a member of a client module with @НаСервере does exist on the server
    d = _сервис(
        tmp_path, "Клиент",
        "@НаСервере\nстатический метод Хелпер(): Строка\n    возврат \"х\"\n;\n",
        "метод Обработать()\n    знч Х = МодульКлиент.Хелпер()\n;\n",
    )
    assert not _has(d, "code/client-module-in-http-service")


def test_unresolved_member_skipped(tmp_path):
    # the member is not found in the module - do not guess
    d = _сервис(
        tmp_path, "Клиент", _КЛИЕНТСКИЙ_ХЕЛПЕР,
        "метод Обработать()\n    знч Х = МодульКлиент.Неизвестный()\n;\n",
    )
    assert not _has(d, "code/client-module-in-http-service")


def test_shadowed_module_name_skipped(tmp_path):
    d = _сервис(
        tmp_path, "Клиент", _КЛИЕНТСКИЙ_ХЕЛПЕР,
        "метод Обработать(Данные: Структура)\n"
        "    знч МодульКлиент = Данные.Модуль\n"
        "    знч Х = МодульКлиент.Хелпер()\n"
        ";\n",
    )
    assert not _has(d, "code/client-module-in-http-service")


def test_member_root_not_flagged(tmp_path):
    # 'Данные.МодульКлиент.Хелпер()' - the root is not a module name
    d = _сервис(
        tmp_path, "Клиент", _КЛИЕНТСКИЙ_ХЕЛПЕР,
        "метод Обработать(Данные: Структура)\n"
        "    знч Х = Данные.МодульКлиент.Хелпер()\n"
        ";\n",
    )
    assert not _has(d, "code/client-module-in-http-service")


def test_call_from_ordinary_module_not_checked(tmp_path):
    # the rule does not touch a call from an ordinary common module (not an HttpСервис)
    (tmp_path / "МодульКлиент.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: МодульКлиент\nОкружение: Клиент\n",
        encoding="utf-8",
    )
    (tmp_path / "МодульКлиент.xbsl").write_text(_КЛИЕНТСКИЙ_ХЕЛПЕР, encoding="utf-8")
    (tmp_path / "Другой.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: Другой\nОкружение: Клиент\n", encoding="utf-8"
    )
    (tmp_path / "Другой.xbsl").write_text(
        "метод Обработать()\n    знч Х = МодульКлиент.Хелпер()\n;\n", encoding="utf-8"
    )
    d = engine.run(
        discover([str(tmp_path)]), select={"code/client-module-in-http-service"}
    )
    assert not _has(d, "code/client-module-in-http-service")


# --- code/query-needs-server -----------------------------------------------------------

RULE_QUERY = "code/query-needs-server"

_ЗАПРОС = (
    "    знч Итог = Запрос{\n"
    "        ВЫБРАТЬ ПЕРВЫЕ 1\n"
    "            Код КАК Код\n"
    "        ИЗ\n"
    "            Тест\n"
    "    }\n"
)


def _модуль(tmp_path, module, yaml):
    (tmp_path / "Модуль.yaml").write_text(yaml, encoding="utf-8")
    (tmp_path / "Модуль.xbsl").write_text(module, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={RULE_QUERY})


_КЛИЕНТ_И_СЕРВЕР = "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: КлиентИСервер\n"


def test_query_without_server_annotation_flagged(tmp_path):
    d = _модуль(tmp_path, "метод Считать()\n" + _ЗАПРОС + ";\n", _КЛИЕНТ_И_СЕРВЕР)
    assert _has(d, RULE_QUERY)
    found = next(x for x in d if x.rule_id == RULE_QUERY)
    assert "Считать" in found.message and found.line == 2


def test_query_with_server_annotation_ok(tmp_path):
    d = _модуль(tmp_path, "@НаСервере\nметод Считать()\n" + _ЗАПРОС + ";\n", _КЛИЕНТ_И_СЕРВЕР)
    assert not _has(d, RULE_QUERY)


def test_blank_line_and_comment_do_not_break_the_bond(tmp_path):
    # neither separator detaches the annotation from its method
    d = _модуль(
        tmp_path,
        "@НаСервере\n\nметод СПустойСтрокой()\n" + _ЗАПРОС + ";\n"
        "@НаСервере\n// комментарий\nметод СКомментарием()\n" + _ЗАПРОС + ";\n",
        _КЛИЕНТ_И_СЕРВЕР,
    )
    assert not _has(d, RULE_QUERY)


def test_server_module_not_checked(tmp_path):
    d = _модуль(
        tmp_path,
        "метод Считать()\n" + _ЗАПРОС + ";\n",
        "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: Сервер\n",
    )
    assert not _has(d, RULE_QUERY)


def test_kind_without_documented_environment_not_checked(tmp_path):
    # an HttpСервис runs on the server and has no Окружение property - left alone
    d = _модуль(
        tmp_path,
        "метод Считать()\n" + _ЗАПРОС + ";\n",
        "ВидЭлемента: HttpСервис\nИмя: Модуль\nКорневойUrl: /x\n",
    )
    assert not _has(d, RULE_QUERY)


def test_form_module_is_client(tmp_path):
    d = _модуль(
        tmp_path,
        "метод Считать()\n" + _ЗАПРОС + ";\n",
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Модуль\n",
    )
    assert _has(d, RULE_QUERY)


def test_variable_named_query_is_not_a_query_block(tmp_path):
    # the lexer reports `Запрос` as a keyword even when it is just a variable name
    d = _модуль(
        tmp_path,
        "метод Считать()\n    знч Запрос = 1\n    возврат Запрос\n;\n",
        _КЛИЕНТ_И_СЕРВЕР,
    )
    assert not _has(d, RULE_QUERY)
