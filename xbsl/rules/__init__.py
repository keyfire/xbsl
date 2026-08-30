"""The linter's rule package.

On import, each rule module registers its checks via the
xbsl.engine.register_file_rule / register_project_rule decorators. Listed here are the
modules that need to be imported (and thereby activated).
"""

# Tier A – structure and YAML:
from . import (  # noqa: F401
    component_props,
    duplicate_subtree,
    project,
    structure,
    unused_components,
    yaml_schema,
)

# Tier B – text and conventions:
from . import security, typography, whitespace  # noqa: F401

# Tier C – code structure, basic syntax and local variables:
from . import (  # noqa: F401
    call_arity,
    code_structure,
    code_syntax,
    locals_usage,
    module_level,
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
    style_variables,
)

# Tier D – semantics over stdlib, forms and the metamodel:
from . import (  # noqa: F401
    binding_types,
    bound_properties,
    catch_exceptions,
    choice_list,
    closeable,
    component_since,
    component_values,
    dynlist_fields,
    enum_defaults,
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
    structure_fields,
    tabular_members,
    type_defaults,
    duplicate_bodies,
    unknown_members,
    unused_methods,
    url_params,
    access_control,
    yaml_deletion,
    localization,
    translation_gaps,
    yaml_imports,
    yaml_render,
    yaml_properties,
    yaml_types,
)
