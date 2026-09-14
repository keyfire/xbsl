"""Only calls and throws may be used as expression statements."""

import pytest

from xbsl.diagnostics import Severity
from xbsl.engine import load_text, run_sources
from xbsl.parser import parse

pytestmark = pytest.mark.needs_data


def _check(expression):
    source = load_text('Sample.xbsl', f'метод Проверить()\n    {expression}\n;\n')
    _, errors = parse(source)
    assert not errors, errors
    return list(run_sources([source], select={'code/statement-no-effect'}, scopes=('file',)))


@pytest.mark.parametrize('expression', [
    'Функция() + 1', 'новый Массив<Число>()',
    'Флаг ? Функция() : 0', 'Пустая ?? Функция()',
    'Функция()!', 'Функция()[0]', 'Функция().Свойство',
    '"%{Функция()}"', '(42)', 'Функция() == 1',
])
def test_dropped_expression_is_a_build_error(expression):
    found = _check(expression)
    assert len(found) == 1
    assert found[0].severity == Severity.ERROR


@pytest.mark.parametrize('expression', [
    'Функция()', '(Функция())', 'Получатель?.Функция()',
    'выбросить новый Исключение("стоп")',
    'знч Результат = Функция() + 1',
    'знч Функция = Н -> Н + 1',
])
def test_calls_throws_and_consumed_expressions_are_valid(expression):
    assert _check(expression) == []
