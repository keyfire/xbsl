"""The linter's rule package.

On import, each rule module registers its checks via the
xbsl.engine.register_file_rule / register_project_rule decorators. Listed here are the
modules that need to be imported (and thereby activated).
"""

# Tier A - structure and YAML:
from . import (  # noqa: F401
    component_props,
    duplicate_subtree,
    list_navigation,
    project,
    structure,
    unused_components,
    yaml_schema,
)

# Tier B - text and conventions:
from . import (  # noqa: F401
    comment_conditions,
    comment_doc_marker,
    comment_prose,
    security,
    translation_values,
    typography,
    whitespace,
)

# Tier C - code structure, basic syntax and local variables:
from . import (  # noqa: F401
    annotations_dup,
    assignments,
    call_arity,
    code_structure,
    code_syntax,
    code_ternary,
    control_flow,
    duplicate_imports,
    initializers,
    interpolation,
    lambda_capture,
    locals_usage,
    module_level,
    readonly_targets,
    ref_fields,
    repetitions,
    resources,
    return_mismatch,
    statement_no_effect,
    static_context,
    syntax_parse,
    undefined_names,
)

# Tiers B/C - platform code-writing conventions:
from . import (  # noqa: F401
    style_conditions,
    style_layout,
    style_literals,
    style_naming,
    style_scopes,
    style_strings,
    style_ternary,
    style_types,
    style_unions,
    style_variables,
)

# Tier D - semantics over stdlib, forms and the metamodel:
from . import (  # noqa: F401
    access_key_handler_flavour,
    binding_types,
    bound_properties,
    form_components,
    catch_exceptions,
    choice_list,
    closeable,
    comment_names,
    component_render,
    component_since,
    component_values,
    deprecated_api,
    dynlist_decl,
    dynlist_fields,
    enum_defaults,
    enum_nullable,
    enum_values,
    environment,
    event_log,
    full_names,
    handlers,
    image_binding,
    resource_cache,
    load_object,
    local_visibility,
    name_shadowing,
    naming,
    ns_objects,
    popup_markup,
    queries,
    redundant_checks,
    skip_undefined,
    reserved_names,
    row_fields,
    semantics,
    size_stretch,
    slot_shape,
    structure_fields,
    tabular_members,
    type_casts,
    type_defaults,
    duplicate_bodies,
    unknown_members,
    unused_imports,
    unused_methods,
    unused_constants,
    url_params,
    access_control,
    yaml_deletion,
    yaml_doc_comments,
    localization,
    translation_gaps,
    yaml_imports,
    yaml_render,
    yaml_properties,
    yaml_types,
)

from . import ambiguous_types  # noqa: F401

from . import unused_return_value  # noqa: F401

from . import captured_local_write  # noqa: F401

from . import missing_return  # noqa: F401

from . import platform_translation_shadow  # noqa: F401

from . import procedure_value  # noqa: F401

from . import contract_parameters  # noqa: F401

from . import deprecated_project  # noqa: F401
