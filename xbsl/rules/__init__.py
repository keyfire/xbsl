"""The linter's rule package.

On import, each rule module registers its checks via the
xbsl.engine.register_file_rule / register_project_rule decorators. Listed here are the
modules that need to be imported (and thereby activated).
"""

# Tier A – structure and YAML:
from . import component_props, project, structure, yaml_schema  # noqa: F401

# Tier B – text and conventions:
from . import security, typography, whitespace  # noqa: F401

# Tier C – code structure, basic syntax and local variables:
from . import (  # noqa: F401
    call_arity,
    code_structure,
    code_syntax,
    locals_usage,
    ref_fields,
    resources,
    return_mismatch,
    statement_no_effect,
    static_context,
    syntax_parse,
    undefined_names,
)

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
    bound_properties,
    catch_exceptions,
    choice_list,
    component_since,
    component_values,
    dynlist_fields,
    enum_nullable,
    enum_values,
    environment,
    event_log,
    handlers,
    local_visibility,
    naming,
    ns_objects,
    queries,
    reserved_names,
    row_fields,
    semantics,
    size_stretch,
    tabular_members,
    type_defaults,
    unknown_members,
    unused_methods,
    access_control,
    yaml_deletion,
    localization,
    yaml_imports,
    yaml_render,
    yaml_properties,
    yaml_types,
)
