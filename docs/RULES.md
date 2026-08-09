---
title: "XBSL linter rules"
description: "The full list of linter checks, with severities and scope."
sidebar:
  label: Rules
  order: 4
---

The full list of linter checks. This file is extended as rules are added; the live list at
runtime is `xbsl --list-rules` (or the MCP `list_rules`). Currently there are 139 rules.

## Boundary: the linter complements the compiler, it does not replace it

The linter works over text, the AST and the project model. Its rules know types at the first
hop: the declared nominal type of a variable and its members, the project objects and the
types they generate, enumeration values, the global types of the linked libraries (from the
`.xlib` archive) - but they do not infer the type of an expression. The engine does infer
chain types, only that feeds hover and completion in the editor, not the checks.

Some of the findings the compiler would catch as well: an unknown type, an argument count, a
non-exception in `catch`, a return not matching the signature. The linter's value there is
not that it sees more, but that it sees them **earlier** - in seconds on your own machine,
before the build and the deploy, pointing at the exact spot. The rest the compiler never
checks at all: code-writing conventions, typography, project structure (duplicate `Id`,
file pairing), unused variables, secrets in the sources.

What the linter does not do is anything that needs full inference of expression types: a
redundant cast, a leaked resource in the general case, whether the TYPE of a returned value
matches the signature. Two of those are worth separating. A structural return mismatch (a
value in a void method, a bare `return` in a typed one) is caught by `code/return-mismatch`,
while a `return` of a string from a method declared `: Number` slips through - telling that
apart needs the expression's type. And a resource is judged only in the one shape where the
declaration itself says everything: `code/unclosed-resource` follows a closeable from its
declaration to the loop over it in the same method; a resource that travels through calls or
collections stays out of reach.

Code correctness is verified by the server-side compilation on deploy; the linter runs before
it and removes common mistakes early.

## How to read the table

- **Rule** – the `group/name` identifier. The group (the part before `/`) lets you enable and
  disable rules in bulk.
- **Severity** – `error` (a build/CI should fail), `warning` (a convention is broken),
  `info` (a hint, usually off).
- **Default** – whether the rule is in the default set (`on`) or is enabled explicitly (`off`).
- **Scope** – `file` (the rule sees one file) or `project` (needs the whole-project index:
  duplicate Ids, unknown types, cross-module calls).
- **Docs** – a link to the platform documentation section behind the rule. In VS Code the code
  of such a rule in the Problems panel opens that section right in the editor.

## Tiers

Rules are split into tiers A-D by what they rely on. A tier is also a quick filter for
`--select`/`--ignore` (alongside the group and the identifier): `--select A,B` runs only
structure and text, `--ignore D` drops the semantics over stdlib.

### Tier A - structure and YAML

The file exists, parses, the object has a unique UUID, the name matches the file.

| # | Rule | Severity | Default | Scope | What it checks | Docs |
|---|---|---|---|---|---|---|
| 1 | `yaml/valid` | error | on | file | YAML does not parse | – |
| 2 | `yaml/id-uuid` | error | on | file | Id is not a UUID | – |
| 3 | `yaml/id-required` | warning | on | file | The object has no Id | – |
| 4 | `yaml/name-matches-file` | warning | on | file | Name does not match the file name | – |
| 5 | `yaml/id-unique` | error | on | project | Duplicate Id in the project | – |
| 6 | `yaml/standard-field-length` | error | on | file | A standard field longer than the platform limit (`Name` over 400 characters, `Code` over 50) - apply rejects the field and it drops out of the object | [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| 7 | `yaml/ref-needs-nullable` | error | on | file | A reference type in a type position without `?` (`Goods.Reference`, `Edit<Goods.Reference>`) - a reference has no default value, the compilation fails with `Default value initialization is not supported` | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 8 | `yaml/no-expression-in-literal` | error | on | file | An `=...` expression inside a literal-typed node (`Font: {Type: AbsoluteFont, Size: =...}`) - the platform accepts only a literal there, compute the whole object instead | [docs](https://1cmycloud.com/docs/help/topics/label-component/) |
| 9 | `project/identifier` | warning | on | file | Project name or vendor is not an identifier | [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| 10 | `project/presentation` | warning | on | file | Project presentation is empty | [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| 11 | `project/version` | warning | on | file | Project version is not A.B.C | [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| 12 | `structure/xbsl-pair` | warning | on | file | Module .xbsl without a paired .yaml | – |
| 13 | `project/path-matches-descriptor` | error | on | file | The `{{vendor}}/{{name}}` path diverged from the descriptor – a build refuses the project before compiling | [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| 14 | `yaml/unknown-component-property` | error | on | file | A markup key the component does not declare while ANOTHER component of the ui schema does (`Checkbox` + `PlaceholderText`, a property of `Edit`) - apply rejects the markup node as an unknown property; a name no component declares is left alone, the documentation does not list the yaml keys in full | [docs](https://1cmycloud.com/docs/help/topics/system-and-interface-components/) |

### Tier B - text and conventions

Encoding, newlines, whitespace, typography (dashes, quotes, ellipsis), line length, secrets
in the sources.

| # | Rule | Severity | Default | Scope | What it checks | Docs |
|---|---|---|---|---|---|---|
| 15 | `security/hardcoded-secret` | error | on | file | A key or a password as a literal | – |
| 16 | `typography/em-dash` | info | off | file | Em dash in a comment | – |
| 17 | `typography/ellipsis` | warning | on | file | Ellipsis character in a comment | – |
| 18 | `typography/curly-quotes` | warning | on | file | Curly quotes | – |
| 19 | `typography/guillemets-comment` | info | off | file | Guillemets in a comment | – |
| 20 | `whitespace/trailing` | warning | on | file | Trailing whitespace | – |
| 21 | `whitespace/mixed-newline` | warning | on | file | Mixed newlines | – |
| 22 | `encoding/utf8` | error | on | file | File is not UTF-8 | – |
| 23 | `style/tab-indent` | warning | on | file | Tab in the indentation | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| 24 | `style/line-length` | warning | on | file | Line longer than 120 characters | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |

### Tier C - code structure, basic syntax and code-writing conventions

Block and bracket balance, loop and method headers, local variables and the `style/` group -
conventions from the documentation section "Code-writing recommendations". Some `style/` rules
are off by default (accumulated debt, `info`): enable them with `--select style` to measure.

| # | Rule | Severity | Default | Scope | What it checks | Docs |
|---|---|---|---|---|---|---|
| 25 | `code/parse-error` | error | on | file | Syntax error (a full parse against the platform grammar) | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| 26 | `code/statement-no-effect` | warning | on | file | Expression statement with no effect: the value is dropped (often a keyword typo, `retun 5` for `return 5`) | – |
| 27 | `code/return-mismatch` | error | on | file | Return does not match the method signature (a value in a void method, a bare `return` in a typed one) - the compiler rejects such code | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 28 | `code/call-arity` | error | on | file | Argument count of a local call outside the method's [required, total] range | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 29 | `code/brackets` | error | on | file | Unbalanced brackets () [] {} | – |
| 30 | `code/blocks` | error | on | file | Unbalanced blocks and ';' | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| 31 | `code/ternary-and-or` | error | on | file | Compound ternary condition without parentheses | [docs](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| 32 | `code/param-type-required` | error | on | file | Parameter without a type and without a default value | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 33 | `code/loop-header` | error | on | file | Malformed 'for' loop header | [docs](https://1cmycloud.com/docs/help/topics/for-in-loop/) |
| 34 | `code/invalid-string-escape` | error | on | file | Invalid escape sequence in a string literal (`\'`, regex-style `\d`) - the compiler rejects such a literal; valid are `\н \в \т \\ \" \% \$ \ю<code>` and the Latin spellings | [docs](https://1cmycloud.com/docs/help/topics/escape-sequence/) |
| 35 | `code/unused-local` | warning | on | file | Unused local variable | – |
| 36 | `code/unused-loop-var` | warning | on | file | Unused loop variable | – |
| 37 | `code/ref-field-needs-req` | error | on | file | Structure reference field without 'req' | [docs](https://1cmycloud.com/docs/help/topics/structure/) |
| 38 | `style/boolean-compare` | warning | on | file | Comparing a boolean value with True/False | [docs](https://1cmycloud.com/docs/help/topics/check-logical-values/) |
| 39 | `style/undefined-is` | warning | on | file | Checking Undefined with the 'is' operator | [docs](https://1cmycloud.com/docs/help/topics/check-if-undefined/) |
| 40 | `style/negated-is` | warning | on | file | Negating the 'is' operator on the outside | [docs](https://1cmycloud.com/docs/help/topics/is-operator/) |
| 41 | `style/semicolon-line` | warning | on | file | ';' not on its own line | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| 42 | `style/wrap-operator` | warning | on | file | Operator at the end of a wrapped line | [docs](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| 43 | `style/wrap-comma` | warning | on | file | Comma at the start of a wrapped line | [docs](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| 44 | `style/camel-case` | warning | on | file | Name is not in UpperCamelCase | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 45 | `style/const-case` | warning | on | file | Constant is not in ALL_CAPS | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 46 | `style/exception-prefix` | warning | on | file | Exception name without the exception prefix | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 47 | `style/abbreviation-case` | warning | on | file | All-caps abbreviation in a name | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 48 | `style/enum-name-vid` | warning | on | file | Enumeration name starts with "Type" | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 49 | `style/collection-literal` | warning | on | file | Manual collection fill instead of a literal | [docs](https://1cmycloud.com/docs/help/topics/collection-literals-usage/) |
| 50 | `style/redundant-tostring` | warning | on | file | An explicit `ToString()` call in a concatenation | [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| 51 | `style/interpolation` | warning | on | file | Concatenation instead of interpolation | [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| 52 | `style/type-colon-space` | warning | on | file | Spaces around the type colon | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 53 | `style/union-spaces` | warning | on | file | Spaces around '\|' in a union type | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 54 | `style/nullable-shorthand` | warning | on | file | Undefined in a type without the '?' shorthand | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 55 | `style/redundant-type` | warning | on | file | Redundant type annotation on initialization | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 56 | `style/optional-params-last` | warning | on | file | Optional parameter before a required one | [docs](https://1cmycloud.com/docs/help/topics/method-declarations/) |
| 57 | `code/resource-bare-name` | error | on | file | `Resource{Resources/<file>.svg}` - the key is a path RELATIVE to the Resources folder; spelling that folder out breaks the lookup | [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| 58 | `query/named-parameter` | error | on | file | A named parameter `&Name` inside a query literal - the literal takes its values by interpolation (`%Name`) | [docs](https://1cmycloud.com/docs/help/topics/query-literal/) |
| 59 | `code/this-in-static-method` | error | on | file | The keyword `this` inside the body of a static method - a static method is common to the whole type and has no object context, the compiler rejects the project | [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| 60 | `code/instance-call-from-static` | error | on | file | A bare call of an instance method of the same owner from a static method - the docs forbid it outright; call the method on a value or make it static | [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| 61 | `code/close-in-before-close` | warning | on | file | `Close()` inside `BeforeClose` – the platform ignores the call and nothing closes the form afterwards | – |
| 62 | `query/no-isnull` | error | on | file | `ISNULL(` inside a query literal – the query language has no such function | – |
| 63 | `style/abstract-name` | warning | on | file | An abstract variable name (`Data`, `Item`, `Object`, `String`, `Value`, `Document` in either spelling - exact or with a digit tail like `Data1`) says nothing about the variable; a stem inside a longer name (`ClientData`) and structure fields (a serialization contract) are left alone | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 64 | `style/single-letter-name` | warning | on | file | A single-letter name of a variable, parameter or loop variable - per the names standard one-letter names belong only to short lambda parameters (`(A, B) -> A + B`) | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 65 | `style/negated-boolean-name` | warning | on | file | A boolean variable named from the negation (`NotConnected`, `NoErrors`) - the name comes from the affirmative (`Connected`, `HasErrors`); judged only where the boolean type is proven: a type annotation or a boolean literal initializer | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 66 | `style/type-in-name` | warning | on | file | A variable name starting with a container type name (the Russian spellings of array, structure and map) - the type is visible from the declaration and the editor, keep it out of the name | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 67 | `style/numeral-in-const-name` | warning | on | file | A spelled-out numeral in a constant name (`TIMEOUT_ONE_MINUTE`) describes the value - name the constant abstractly (`TIMEOUT`) so a value change does not break the name | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |

### Tier D - semantics over stdlib, forms and the metamodel

Needs the project index and platform data: unknown types and objects, enumeration values,
the execution model (client/server), form handlers, properties and queries.

| # | Rule | Severity | Default | Scope | What it checks | Docs |
|---|---|---|---|---|---|---|
| 68 | `yaml/choice-needs-static-list` | warning | on | file | ValueChoice without a static `ChoiceList` | [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru/) |
| 69 | `code/unknown-type` | warning | on | project | Unknown type | – |
| 70 | `code/catch-non-exception` | error | on | file | The type in `catch` is not an exception (a stdlib non-exception or a local `structure`) - the compiler rejects such code | [docs](https://1cmycloud.com/docs/help/topics/exceptions/) |
| 71 | `code/unknown-member` | error | on | file | A member access on a variable of a known stdlib type - plain or a generic, whose arguments type the members and do not name them - that the type does not have (first hop, typos get a hint) | – |
| 72 | `code/unknown-static-member` | error | on | project | A member reached through a type name (`DateTime.Minimal()`) that the type does not have; the type of such a call carries on to the next hop. A bare name is read as a type only when the project gives it no other meaning; the module's paired yaml counts even in a single-file check | – |
| 73 | `yaml/foreign-not-public` | error | on | project | A yaml reference (a type position or a `FormType` navigation target) to an element of another subsystem whose `VisibilityScope` is not `InProject`/`Global` - unreachable from outside its subsystem, and no import helps | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 74 | `code/call-arity-cross` | error | on | project | Argument count of a `<Module>.<Method>(...)` call outside the target module's signature range | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 75 | `code/undefined-name` | error | on | project | Undefined name in an expression (a typo in a name) and in a short string interpolation (`"?$format=json"` substitutes the name `format`, `\$` is needed) - the compiler rejects such code | – |
| 76 | `code/unknown-object-type` | warning | on | project | Unknown project-object type | – |
| 77 | `yaml/unknown-type` | warning | on | project | Unknown type in yaml | – |
| 78 | `yaml/dynlist-missing-field` | warning | on | project | Missing dynamic-list field | [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| 79 | `code/unknown-enum-value` | warning | on | project | Unknown enumeration value | [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| 80 | `yaml/enum-needs-nullable` | warning | on | project | Enumeration without nullable | [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| 81 | `yaml/unknown-enum-value` | error | on | file | A component property value outside the enumeration of the ui schema (`ContentVerticalAlign: End` - the vertical axis has `Top`, `Center`, `Bottom`, `Baseline` and no `End`) | – |
| 82 | `yaml/bare-object-value` | error | on | file | A bare word on a property that accepts `Object` - the platform expects a quoted literal, an `=` binding or a `$` localized-string reference | [docs](https://1cmycloud.com/docs/help/topics/label-component/) |
| 83 | `code/unknown-resource` | error | on | project | The name in `Resource{...}` is neither in the project's `Resources` folders nor in the platform's image library | [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| 84 | `form/unknown-handler` | warning | on | project | Form handler not found in the module | [docs](https://1cmycloud.com/docs/help/topics/form-component/) |
| 85 | `code/server-call-from-handler` | warning | on | project | Server method is unavailable to a client handler | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 86 | `code/client-annotation-in-server-module` | warning | on | project | Client annotation in a server common module | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 87 | `code/client-module-in-http-service` | warning | on | project | Client common module in an HTTP service | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 88 | `code/query-needs-server` | error | on | project | A `Query{...}` block in a method of a client-side module (a form, or a common module whose `Environment` involves the client) that carries no `@OnServer` - the type does not exist on the client and the compiler rejects the build | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 89 | `code/local-method-cross-component` | warning | on | project | Cross-component call of a local method | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 90 | `code/local-method-cross-module` | error | on | project | Cross-module call of a local method | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 91 | `naming/yo` | warning | on | file | The letter yo in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 92 | `naming/underscore` | warning | on | file | Underscore in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 93 | `naming/abbreviation` | warning | on | file | All-caps abbreviation in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 94 | `naming/latin-term` | warning | on | file | English term spelled in Cyrillic | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 95 | `naming/enum-vid` | warning | on | file | Enumeration name with the word "Type" | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 96 | `naming/kind-in-name` | warning | on | file | Element kind inside its name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 97 | `naming/filler-word` | warning | on | file | Filler word in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 98 | `naming/module-suffix` | warning | on | file | Environment suffix in a common module name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 99 | `naming/number` | warning | on | file | Wrong number for the element kind | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 100 | `naming/boolean-name` | warning | on | file | Boolean attribute name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 101 | `naming/presentation` | warning | on | file | Element presentation | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 102 | `naming/prefix-by-kind` | warning | on | file | Kind-specific name without its prefix | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 103 | `code/unknown-ns-object` | warning | on | project | Unknown object in a kind namespace | – |
| 104 | `query/unknown-table` | warning | on | project | Unknown table in a query | [docs](https://1cmycloud.com/docs/help/topics/select-from/) |
| 105 | `query/in-subquery-composite` | warning | on | project | 'IN' with a subquery over a composite type | [docs](https://1cmycloud.com/docs/help/topics/in-expression/) |
| 106 | `yaml/unknown-property` | warning | on | file | Unknown object property | – |
| 107 | `code/reserved-name` | warning | on | file | Reserved name | – |
| 108 | `yaml/builtin-property-name` | warning | on | file | Built-in property name clash | – |
| 109 | `yaml/size-needs-no-stretch` | info | off | file | A size without disabling the stretch | [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| 110 | `code/unused-method` | warning | off | project | Method is never referenced | – |
| 111 | `yaml/missing-import` | warning | on | project | A yaml reference (a type position or a `FormType` navigation target) to a public element of another subsystem that the `Import` section does not list | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 112 | `yaml/presentation-field` | error | on | file | The presentation field of an object | [docs](https://1cmycloud.com/docs/help/topics/element-view/) |
| 113 | `yaml/unexpected-type-argument` | error | on | file | A type argument on a property the ui schema declares without one - another type, rejected when the build is applied (a form's `AdditionalCommands` takes `CommandInterfaceFragment`, not `CommandInterfaceFragment<UsualCommand>`) | [docs](https://1cmycloud.com/docs/help/topics/command-interface/) |
| 114 | `yaml/property-since-compat` | error | on | project | A component property newer than the project's `CompatibilityMode` (the ui schema records the version it appeared in) - apply rejects it as an unknown property | [docs](https://1cmycloud.com/docs/help/topics/update-server/) |
| 115 | `query/deletion-mark-immediate` | error | on | project | A deletion-mark condition in a query on an object whose `DeletionMode` is `Immediately` - such an object has no mark and the query fails on apply | [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| 116 | `yaml/item-id-required` | error | on | file | A metadata collection item (an attribute, a tabular section, an enumeration item, an access-key parameter) without the `Id` its class declares - apply answers `ID required` | – |
| 117 | `code/unknown-row-field` | error | on | project | A field addressed on a dynamic list row (`DynamicListRow<Form.Type>`) that the list's `Fields` do not declare | [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| 118 | `code/row-field-null` | error | on | project | A dynamic list field taken through a reference (`Owner.Number`) is `<type>|Null` and cannot fill a typed structure field - the compiler answers `Null cannot be assigned` | [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| 119 | `yaml/unknown-attribute-property` | error | on | file | A key an attribute's own metamodel class does not declare (`Length` on a regular attribute - the built-in `Code` declares it, a Number attribute has `IntegerPartLength`) - apply rejects the object | – |
| 120 | `yaml/empty-group-sized` | warning | on | file | An empty `Group` with `Height`/`Width` – the renderer drops the node and there is no gap | – |
| 121 | `yaml/hint-too-long` | warning | on | file | A `Tooltip` longer than the render limit – the tail is not shown at all | – |
| 122 | `code/client-available-needs-context` | error | on | project | `@AvailableFromClient` on a method of an interface component module that is neither static nor `@Contextual` – the component type is not a singleton, so the apply rejects the modifier | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 123 | `code/server-module-in-client-context` | error | on | project | A `Module.Member(...)` access to a common module with `Environment: Server` from a method that runs on the client (an interface component, a command, a client common module) – the type does not exist on the client | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 124 | `yaml/delete-current-needs-immediate` | error | on | file | `OnReferencedObjectDeletion: DeleteCurrent` on an attribute whose owner has a `DeletionMode` that only marks (`DeletionMark` is also the default) – the apply answers `Action DeleteCurrent cannot apply to object with a DeletionMark` | [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| 125 | `code/per-object-permissions-need-common` | warning | on | project | An object calculates its permissions per object, but its module declares no `ComputeAccessPermissions` handler – the common calculation is required even then, if only to return an empty array | [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| 126 | `code/permission-field-not-declared` | warning | on | project | Inside `ComputeAccessPermissionsForObjects` a field outside `ComputePermissionsBy` is read, or a declared field is reached through `Entity` instead of the record | [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| 127 | `yaml/placeholder-key-in-strings` | error | on | file | A key carrying the placeholder `$0` in the `Strings` section of a `LocalizedStrings` dictionary: the section compiles to a method WITHOUT parameters, so a call with an argument fails the apply with an "unknown method" answer | [docs](https://1cmycloud.com/docs/help/topics/localization/) |
| 128 | `code/compare-with-localized` | warning | on | project | A localized value (`Dictionary.Key()`, `Presentation()`) compared against a literal or against a second localized value – in another language the branch simply never runs | [docs](https://1cmycloud.com/docs/help/topics/localization/) |
| 129 | `code/bound-property-assign` | warning | on | file | A property COMPUTED by an expression in the paired markup (`Height: =Common.IsMobile()?820:528`) is assigned from code - the platform refuses such an assignment, and inside a try/catch the refusal is invisible; a data binding (a bare path) is left alone, it is two-way by design | – |
| 130 | `yaml/event-needs-importance` | warning | on | file | An `EventLogEvent` description that does not set `Importance`: its default is `FromConstructor`, so the platform then demands the value in EVERY constructor, and one write that omits it fails the apply on the constructor line; an explicit `Importance: FromConstructor` states the choice and silences the rule | [docs](https://1cmycloud.com/docs/help/topics/event-properties/) |
| 131 | `code/collection-field-needs-req` | error | on | file | A structure field whose generic type has no argument-less constructor (`ReadableArray<String>`) and no `req`, `?` or initializer - the apply answers "cannot be initialized with a default value"; `Array<String>` and the like are constructible empty and are left alone | [docs](https://1cmycloud.com/docs/help/topics/structure/) |
| 132 | `code/var-needs-init` | warning | on | project | A variable declared by type alone where the type has no constructor and no default value (`var Response: HttpResponse`) - the compilation answers "has neither a constructor nor a default value"; an enumeration, an annotation, a singleton and a name shadowed by a project type are skipped | [docs](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| 133 | `code/unknown-tabular-member` | error | on | project | A member access on a tabular section's row collection that the array type does not have (`Object.Section.Member` in an object form module, the bare section name or `this.Section` in the entity's modules) - the collection is `Array<Entity.Section>`, and the other platform's habitual `Count()` is called `Size()` here; a module named after the section shadows it, attributes are not judged | – |
| 134 | `code/global-unavailable` | error | on | project | A call of a global name outside its environment: `Message` (client-only) in a server module - the apply answers "the method is unavailable in the current environment", the dynamic evaluation globals (server-only) in a client method without `@OnServer`; `@OnClient`/`@OnServer` override the module's environment, the availability comes from the per-member availability lines of the global context packages | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 135 | `style/shadow-project-name` | warning | on | project | A variable, parameter or method named like a project element (a `Subscribers` variable next to the `Subscribers` catalog) - the declaration shadows the element for that scope; platform handler parameter names never collide with project names | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 136 | `code/unclosed-resource` | warning | on | file | A closeable resource (`val Selection = Query{...}.Execute()`) abandoned by an early exit from the loop over it: the platform closes a full pass by itself, while a `return` or a `break` in the middle leaves the resource open and the platform logs an unclosed-resource event; declaring the variable with `use` closes it on every exit path. A resource that arrived as a parameter, one the method closes by hand and one it returns to its caller are left to the author | [docs](https://1cmycloud.com/docs/help/topics/closeable-type/) |
| 137 | `conventions/untranslated-visible-literal` | warning | on | project | Visible text left as a Cyrillic literal where the project already references the same property into a localization dictionary - the intent is counted per element kind, so a same-named property of another kind is not judged; silent on a project whose descriptor lists fewer than two localization languages | – |
| 138 | `conventions/untranslated-code-literal` | warning | off | project | Visible text left as a Cyrillic literal in a MODULE - judged by the SINK it reaches (an argument of the platform message call, a property of an event-log event, or either of them one step away through a method that forwards its parameter); markup, pure interpolation and single words are skipped, and the rule is silent on a project whose descriptor lists fewer than two localization languages | – |
| 139 | `code/unknown-structure-field` | error | on | project | A field access on a structure declared IN THE PROJECT is checked against its declaration: rename a field and its reader in another module turns red here rather than on the server apply. The type comes from the variable's declaration (`Module.Structure`, a bare name for the declaring module), from a `new` constructor and from the element type of a `for X in List` loop; a name declared with anything else in the method, a namesake of a stdlib type, the second hop of a chain and Latin member spellings are not judged | – |

## Group details

### Queries: `IN` with a subquery over a composite type (rule `query/in-subquery-composite`)

A platform standard: `IN` with a subquery over an expression of a composite type is implemented
inefficiently on most DBMSs, so the condition is written with `EXISTS` instead. The rule is a
warning – the standard is mandatory:

```
WHERE T.Value IN (SELECT F.Value FROM Filters AS F)                    // warning
WHERE EXISTS (SELECT 1 FROM Filters AS F WHERE F.Value = T.Value)      // this way
```

A type counts as composite when the yaml spells two or more alternatives (`String|Number|?`): the
`?` is not a type but the admissibility of `Undefined`, and `Array<String|Number>` is not
composite either. Only a field whose type is known for sure is questioned: `Alias.Field` or
`Table.Field`, where the alias is unambiguous within the block and the field is found in the
table's yaml; a list of values (`IN (1, 2, &Codes)`) is not what the standard is about. Both
spellings of the query language are understood - the English `IN`, `NOT`, `SELECT` and their
Russian equivalents.

### Project properties (the `project/` rules)

Three rules from the standard "Filling in the project properties": `Vendor` and `Name` are
identifiers built from the presentations, every word capitalized; `Presentation` and
`VendorPresentation` are filled in - the
official name of the project and of the company that developed it; `Version` is three numbers
`A.B.C` (semantic versioning), not `1.0`.

### Names of project elements (the `naming/` rules)

Twelve rules from the platform standard "Names of project elements" – it is mandatory in new code,
so all of them are warnings. They read the descriptions (`.yaml`): the name of the element itself
and the names in its `Attributes`, `Dimensions`, `Resources`, `TabularParts` and enumeration
values.

The number of a name is checked against the kind: catalogs, documents, registers and tabular
sections are named in the plural, enumerations and structures in the singular (`naming/number`).
This is morphology, not a guess by the ending: a singular noun that the standard allows is told
apart from a plural that reads as a genitive singular without the case. Needs the `[morph]`
extra (`pip install "xbsl[morph]"`); without it the rule stays silent.

The rest: the letter yo and underscores in names, an abbreviation written in mixed case instead
of all caps, an English term transliterated rather than kept as the original (`Xml`, not its
Cyrillic spelling), an enumeration named with the word for type where the standard asks for the
word for kind, the element kind repeated inside its own name, filler words such as the ones for
management or manager, an environment suffix on a common module name (the environment is a
property, not a name), a boolean attribute named by a negation instead of the positive form, an
empty `Presentation`, and the prefixes required for certain kinds - access key, right and
navigation.

### Code style conventions (the `style/` rules)

Twenty-seven rules that follow the platform documentation ("Code style conventions", "Language
idioms") and the "Variable and constant names" development standard: layout and expression
wrapping, naming, type descriptions and signatures, collection literals, string interpolation,
and checks of boolean values and `Undefined`.

Of the variable-names standard the token-provable part is checked: abstract names,
single-letter names outside lambdas, Cyrillic and Latin abbreviations not written as one word,
boolean names built from the negation, a container type inside a name, numerals inside constant
names, and the shadowing of project element names. Left to the author and review: redundant
words in a name, abbreviations beyond the capitalization law, digits in place of a qualifier
over a meaningful stem (`Stage1` and `Data1` differ only in meaning), and the abstractness of
a constant name beyond numerals (the role of `INITIAL_STAGE` against the value of
`STAGE_QUESTIONNAIRE` is invisible to tokens).

Rules that clean code already satisfies are enabled by default (`warning`) – they guard against
regressions. Rules that typically fire on accumulated legacy debt are `info` and disabled; enable
them to measure the debt and pay it down:

```sh
xbsl path/to/sources --select style     # ONLY these rules (replaces the default set)
xbsl path/to/sources --enable style     # the default set PLUS these
xbsl path/to/sources --ignore style     # the default set minus these
```

`--select`, `--enable` and `--ignore` accept a rule id, a group (the part before `/`) or a tier
letter, repeated or comma-separated. `--select` narrows to exactly the given rules; `--enable`
switches on off-by-default rules on top of the defaults.

`Query{ ... }` blocks (the query DSL) and string literals (HTML/CSS/SVG in web views) are
excluded from these checks. Not covered, and left to the author and review: indentation being a
multiple of four, collection idioms, `Rows.Join()` for bulk concatenation, the `?.` / `??`
idioms, and `case` instead of an `else if` chain.

## Enabling and disabling

`--select` and `--ignore` accept a rule identifier, a group (the part before `/`, e.g. `style`)
or a tier letter `A`/`B`/`C`/`D`. A plugin may override a rule's severity (the `xbsl.severity`
entry-points group); `XBSL_NO_PLUGINS=1` disables plugins and restores the built-in values from
this table.
