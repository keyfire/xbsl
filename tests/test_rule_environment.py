"""Проверки семейства правил окружения (xbsllint/rules/environment.py)."""

from xbsllint import engine
from xbsllint.cli import discover


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
    # обработчик сам исполняется на сервере – вызов серверного метода корректен
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
    # обработчик задан аннотацией @Обработчик, а не в yaml
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
    # 'Объект.Сохранить()' – метод другого объекта, не голое имя модуля
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
    # локальная переменная затеняет имя серверного метода
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
    # вызов из обычного (не обработчик) клиентского метода правило не трогает
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
    # вызов в следующем за обработчиком методе не приписывается телу обработчика
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
    # член клиентского модуля с @НаСервере существует на сервере
    d = _сервис(
        tmp_path, "Клиент",
        "@НаСервере\nстатический метод Хелпер(): Строка\n    возврат \"х\"\n;\n",
        "метод Обработать()\n    знч Х = МодульКлиент.Хелпер()\n;\n",
    )
    assert not _has(d, "code/client-module-in-http-service")


def test_unresolved_member_skipped(tmp_path):
    # член не найден в модуле – не гадаем
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
    # 'Данные.МодульКлиент.Хелпер()' – корень не имя модуля
    d = _сервис(
        tmp_path, "Клиент", _КЛИЕНТСКИЙ_ХЕЛПЕР,
        "метод Обработать(Данные: Структура)\n"
        "    знч Х = Данные.МодульКлиент.Хелпер()\n"
        ";\n",
    )
    assert not _has(d, "code/client-module-in-http-service")


def test_call_from_ordinary_module_not_checked(tmp_path):
    # вызов из обычного общего модуля (не HttpСервис) правило не трогает
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
