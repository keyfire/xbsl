"""The linter's rule package.

On import, each rule module registers its checks via the
xbsllint.engine.register_file_rule / register_project_rule decorators. Listed here are the
modules that need to be imported (and thereby activated).
"""

# Tier A – structure and YAML:
from . import structure, yaml_schema  # noqa: F401

# Tier B – text and conventions:
from . import typography, whitespace  # noqa: F401

# Tier C – code structure and local variables:
from . import code_structure, locals_usage, ref_fields  # noqa: F401

# Tiers B/C – platform code-writing conventions:
from . import (  # noqa: F401
    style_conditions,
    style_layout,
    style_naming,
    style_strings,
    style_types,
)

# Tier D – semantics over stdlib, forms and the metamodel:
from . import (  # noqa: F401
    choice_list,
    dynlist_fields,
    enum_nullable,
    enum_values,
    environment,
    handlers,
    local_visibility,
    naming,
    ns_objects,
    queries,
    reserved_names,
    semantics,
    size_stretch,
    unused_methods,
    yaml_imports,
    yaml_properties,
    yaml_types,
)
