"""Пакет правил линтера.

Каждый модуль правил при импорте регистрирует свои проверки через декораторы
xbsllint.engine.register_file_rule / register_project_rule. Здесь перечисляются
модули, которые нужно импортировать (и тем самым активировать).
"""

# Тир A – структура и YAML:
from . import structure, yaml_schema  # noqa: F401

# Тир B – текст и конвенции:
from . import conventions, typography, whitespace  # noqa: F401

# Тир C – структура кода и локальные переменные:
from . import code_structure, locals_usage  # noqa: F401

# Тир D – семантика по stdlib, формам и метамодели:
from . import handlers, semantics, yaml_properties  # noqa: F401
