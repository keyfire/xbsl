"""yaml/duplicate-key: a scalar key repeated within one YAML mapping.

The loader keeps only the last value of a duplicated key, so every schema rule downstream
reads an already-merged document and stays silent; the compiler rejects the file at deploy.
The rule reads the composed node graph, where the duplicates are still visible.

The rule needs no Element data, so the tests live in their own module (test_rules is skipped
whole in a data-less checkout) and run in the public CI.
"""

from xbsl import engine


def _lint(content: str):
    return engine.run_sources(
        [engine.load_text("О.yaml", content)], select={"yaml/duplicate-key"},
    )


def test_duplicate_key_repeat_is_flagged_at_its_position():
    # The battle case: a lost list-item dash merges two components, and the second node's
    # properties land in the first - its repeated key is the earliest visible symptom.
    d = _lint(
        "ВидЭлемента: Страница\n"
        "Ид: 11111111-1111-1111-1111-111111111111\n"
        "Имя: Форма\n"
        "Содержимое:\n"
        "    - Тип: Надпись\n"
        "      Имя: Заголовок\n"
        "      Заголовок: Текст\n"
        "      Имя: Подпись\n"
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (8, 7)
    assert d[0].rule_id == "yaml/duplicate-key"
    assert "'Имя'" in d[0].message and "6" in d[0].message


def test_duplicate_key_every_repeat_after_the_first_is_flagged():
    # Three occurrences: the first sets the key, the two repeats are two findings,
    # both pointing back at the first line.
    d = _lint("А: 1\nБ: 2\nА: 3\nА: 4\n")
    assert [(x.line, x.col) for x in d] == [(3, 1), (4, 1)], [x.message for x in d]
    assert all("'А'" in x.message and "1" in x.message for x in d)


def test_duplicate_key_same_keys_in_distinct_nodes_are_silent():
    # Two columns each carrying their own name key share nothing: the mapping is the unit.
    d = _lint(
        "Колонки:\n"
        "    - Имя: Автор\n"
        "      Заголовок: Автор\n"
        "    - Имя: Дата\n"
        "      Заголовок: Дата\n"
    )
    assert d == [], [x.message for x in d]


def test_duplicate_key_found_deep_in_a_component_tree():
    # The depth does not shelter the repeat: every mapping of the graph is walked.
    d = _lint(
        "Содержимое:\n"
        "    - Тип: Группа\n"
        "      Содержимое:\n"
        "          - Тип: Группа\n"
        "            Содержимое:\n"
        "                - Тип: Кнопка\n"
        "                  Имя: Открыть\n"
        "                  Имя: Закрыть\n"
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (8, 19)


def test_duplicate_key_anchor_and_alias_do_not_double_report():
    # An anchored mapping aliased into a second place is one node of the graph: its own
    # duplicate is reported once, and the clean sibling stays clean.
    d = _lint(
        "Первый: &node\n"
        "    Имя: А\n"
        "    Имя: Б\n"
        "Второй: *node\n"
        "Третий:\n"
        "    Имя: В\n"
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (3, 5)


def test_duplicate_key_block_scalar_text_is_not_read_as_keys():
    # Key-looking lines inside a block scalar are text, not mapping entries.
    d = _lint(
        "Текст: |\n"
        "    Имя: раз\n"
        "    Имя: два\n"
        "Имя: Форма\n"
    )
    assert d == [], [x.message for x in d]


def test_duplicate_key_merge_keys_are_exempt():
    # YAML 1.1 lets one mapping merge several others - a repeated << is not a duplicate.
    d = _lint(
        "Основа: &base\n"
        "    Ширина: 1\n"
        "Добавка: &extra\n"
        "    Высота: 2\n"
        "Узел:\n"
        "    <<: *base\n"
        "    <<: *extra\n"
        "    Имя: В\n"
    )
    assert d == [], [x.message for x in d]


def test_duplicate_key_flow_mapping_is_judged_too():
    # A flow mapping is the same MappingNode: the repeat inside braces is found as well.
    d = _lint("Шрифт: {Тип: АбсолютныйШрифт, Размер: 12, Размер: 14}\n")
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (1, 43)


def test_duplicate_key_different_tags_share_the_text_without_a_finding():
    # A plain 1 is an int key and a quoted 1 is a str key: different entries to the loader.
    d = _lint("1: раз\n\"1\": два\n")
    assert d == [], [x.message for x in d]


def test_duplicate_key_broken_yaml_is_left_to_yaml_valid():
    # A file that does not compose has no graph to walk - yaml/valid owns that file,
    # and even a textual duplicate above the breakage is not judged.
    d = _lint("Имя: А\nИмя: Б\nСписок: [1, 2\n")
    assert d == [], [x.message for x in d]
