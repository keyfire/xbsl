---
title: "XBSL linter rules"
description: "The full list of linter checks, with severities and scope."
sidebar:
  label: Rules
  order: 4
---

The full list of linter checks. This file is extended as rules are added; the live list at
runtime is `xbsl --list-rules` (or the MCP `list_rules`). Currently there are 117 rules.

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
redundant cast, an unclosed resource, whether the TYPE of a returned value matches the
signature. That last one is worth separating: a structural mismatch (a value in a void
method, a bare `return` in a typed one) is caught by `code/return-mismatch`, while a
`return` of a string from a method declared `: Number` slips through - telling that apart
needs the expression's type.

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

### Tier B - text and conventions

Encoding, newlines, whitespace, typography (dashes, quotes, ellipsis), line length, secrets
in the sources.

| # | Rule | Severity | Default | Scope | What it checks | Docs |
|---|---|---|---|---|---|---|
| 14 | `security/hardcoded-secret` | error | on | file | A key or a password as a literal | – |
| 15 | `typography/em-dash` | info | off | file | Em dash in a comment | – |
| 16 | `typography/ellipsis` | warning | on | file | Ellipsis character in a comment | – |
| 17 | `typography/curly-quotes` | warning | on | file | Curly quotes | – |
| 18 | `typography/guillemets-comment` | info | off | file | Guillemets in a comment | – |
| 19 | `whitespace/trailing` | warning | on | file | Trailing whitespace | – |
| 20 | `whitespace/mixed-newline` | warning | on | file | Mixed newlines | – |
| 21 | `encoding/utf8` | error | on | file | File is not UTF-8 | – |
| 22 | `style/tab-indent` | warning | on | file | Tab in the indentation | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| 23 | `style/line-length` | info | off | file | Line longer than 120 characters | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |

### Tier C - code structure, basic syntax and code-writing conventions

Block and bracket balance, loop and method headers, local variables and the `style/` group -
conventions from the documentation section "Code-writing recommendations". Some `style/` rules
are off by default (accumulated debt, `info`): enable them with `--select style` to measure.

| # | Rule | Severity | Default | Scope | What it checks | Docs |
|---|---|---|---|---|---|---|
| 24 | `code/parse-error` | error | on | file | Syntax error (a full parse against the platform grammar) | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| 25 | `code/statement-no-effect` | warning | on | file | Expression statement with no effect: the value is dropped (often a keyword typo, `retun 5` for `return 5`) | – |
| 26 | `code/return-mismatch` | error | on | file | Return does not match the method signature (a value in a void method, a bare `return` in a typed one) - the compiler rejects such code | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 27 | `code/call-arity` | error | on | file | Argument count of a local call outside the method's [required, total] range | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 28 | `code/brackets` | error | on | file | Unbalanced brackets () [] {} | – |
| 29 | `code/blocks` | error | on | file | Unbalanced blocks and ';' | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| 30 | `code/ternary-and-or` | error | on | file | Compound ternary condition without parentheses | [docs](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| 31 | `code/param-type-required` | error | on | file | Parameter without a type and without a default value | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 32 | `code/loop-header` | error | on | file | Malformed 'for' loop header | [docs](https://1cmycloud.com/docs/help/topics/for-in-loop/) |
| 33 | `code/invalid-string-escape` | error | on | file | Invalid escape sequence in a string literal (`\'`, regex-style `\d`) - the compiler rejects such a literal; valid are `\н \в \т \\ \" \% \$ \ю<code>` and the Latin spellings | [docs](https://1cmycloud.com/docs/help/topics/escape-sequence/) |
| 34 | `code/unused-local` | warning | on | file | Unused local variable | – |
| 35 | `code/unused-loop-var` | warning | on | file | Unused loop variable | – |
| 36 | `code/ref-field-needs-req` | error | on | file | Structure reference field without 'req' | [docs](https://1cmycloud.com/docs/help/topics/structure/) |
| 37 | `style/boolean-compare` | info | off | file | Comparing a boolean value with True/False | [docs](https://1cmycloud.com/docs/help/topics/check-logical-values/) |
| 38 | `style/undefined-is` | warning | on | file | Checking Undefined with the 'is' operator | [docs](https://1cmycloud.com/docs/help/topics/check-if-undefined/) |
| 39 | `style/negated-is` | warning | on | file | Negating the 'is' operator on the outside | [docs](https://1cmycloud.com/docs/help/topics/is-operator/) |
| 40 | `style/semicolon-line` | warning | on | file | ';' not on its own line | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| 41 | `style/wrap-operator` | warning | on | file | Operator at the end of a wrapped line | [docs](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| 42 | `style/wrap-comma` | warning | on | file | Comma at the start of a wrapped line | [docs](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| 43 | `style/camel-case` | info | off | file | Name is not in UpperCamelCase | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 44 | `style/const-case` | warning | on | file | Constant is not in ALL_CAPS | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 45 | `style/exception-prefix` | warning | on | file | Exception name without the exception prefix | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 46 | `style/abbreviation-case` | info | off | file | All-caps abbreviation in a name | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 47 | `style/enum-name-vid` | warning | on | file | Enumeration name starts with "Type" | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 48 | `style/collection-literal` | info | off | file | Manual collection fill instead of a literal | [docs](https://1cmycloud.com/docs/help/topics/collection-literals-usage/) |
| 49 | `style/redundant-tostring` | info | off | file | An explicit `ToString()` call in a concatenation | [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| 50 | `style/interpolation` | info | off | file | Concatenation instead of interpolation | [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| 51 | `style/type-colon-space` | warning | on | file | Spaces around the type colon | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 52 | `style/union-spaces` | warning | on | file | Spaces around '\|' in a union type | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 53 | `style/nullable-shorthand` | warning | on | file | Undefined in a type without the '?' shorthand | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 54 | `style/redundant-type` | warning | on | file | Redundant type annotation on initialization | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 55 | `style/optional-params-last` | warning | on | file | Optional parameter before a required one | [docs](https://1cmycloud.com/docs/help/topics/method-declarations/) |
| 56 | `code/resource-bare-name` | error | on | file | `Resource{Resources/<file>.svg}` - the key is a path RELATIVE to the Resources folder; spelling that folder out breaks the lookup | [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| 57 | `query/named-parameter` | error | on | file | A named parameter `&Name` inside a query literal - the literal takes its values by interpolation (`%Name`) | [docs](https://1cmycloud.com/docs/help/topics/query-literal/) |
| 58 | `code/this-in-static-method` | error | on | file | The keyword `this` inside the body of a static method - a static method is common to the whole type and has no object context, the compiler rejects the project | [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| 59 | `code/instance-call-from-static` | error | on | file | A bare call of an instance method of the same owner from a static method - the docs forbid it outright; call the method on a value or make it static | [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| 60 | `code/close-in-before-close` | warning | on | file | `Закрыть()` inside `ПередЗакрытием` – the platform ignores the call and nothing closes the form afterwards | – |
| 61 | `query/no-isnull` | error | on | file | `ЕСТЬNULL(` inside a query literal – the query language has no such function | – |

### Tier D - semantics over stdlib, forms and the metamodel

Needs the project index and platform data: unknown types and objects, enumeration values,
the execution model (client/server), form handlers, properties and queries.

| # | Rule | Severity | Default | Scope | What it checks | Docs |
|---|---|---|---|---|---|---|
| 62 | `yaml/choice-needs-static-list` | warning | on | file | ValueChoice without a static `ChoiceList` | [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru/) |
| 63 | `code/unknown-type` | warning | on | project | Unknown type | – |
| 64 | `code/catch-non-exception` | error | on | file | The type in `catch` is not an exception (a stdlib non-exception or a local `structure`) - the compiler rejects such code | [docs](https://1cmycloud.com/docs/help/topics/exceptions/) |
| 65 | `code/unknown-member` | error | on | file | A member access on a variable of a known stdlib type - plain or a generic, whose arguments type the members and do not name them - that the type does not have (first hop, typos get a hint) | – |
| 66 | `code/unknown-static-member` | error | on | project | A member reached through a type name (`DateTime.Minimal()`) that the type does not have; the type of such a call carries on to the next hop. A bare name is read as a type only when the project gives it no other meaning; the module's paired yaml counts even in a single-file check | – |
| 67 | `yaml/foreign-not-public` | error | on | project | A yaml reference (a type position or a `FormType` navigation target) to an element of another subsystem whose `VisibilityScope` is not `InProject`/`Global` - unreachable from outside its subsystem, and no import helps | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 68 | `code/call-arity-cross` | error | on | project | Argument count of a `<Module>.<Method>(...)` call outside the target module's signature range | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 69 | `code/undefined-name` | error | on | project | Undefined name in an expression (a typo in a name) and in a short string interpolation (`"?$format=json"` substitutes the name `format`, `\$` is needed) - the compiler rejects such code | – |
| 70 | `code/unknown-object-type` | warning | on | project | Unknown project-object type | – |
| 71 | `yaml/unknown-type` | warning | on | project | Unknown type in yaml | – |
| 72 | `yaml/dynlist-missing-field` | warning | on | project | Missing dynamic-list field | [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| 73 | `code/unknown-enum-value` | warning | on | project | Unknown enumeration value | [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| 74 | `yaml/enum-needs-nullable` | warning | on | project | Enumeration without nullable | [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| 75 | `yaml/unknown-enum-value` | error | on | file | A component property value outside the enumeration of the ui schema (`ContentVerticalAlign: End` - the vertical axis has `Top`, `Center`, `Bottom`, `Baseline` and no `End`) | – |
| 76 | `yaml/bare-object-value` | error | on | file | A bare word on a property that accepts `Object` - the platform expects a quoted literal, an `=` binding or a `$` localized-string reference | [docs](https://1cmycloud.com/docs/help/topics/label-component/) |
| 77 | `code/unknown-resource` | error | on | project | The name in `Resource{...}` is neither in the project's `Resources` folders nor in the platform's image library | [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| 78 | `form/unknown-handler` | warning | on | project | Form handler not found in the module | [docs](https://1cmycloud.com/docs/help/topics/form-component/) |
| 79 | `code/server-call-from-handler` | warning | on | project | Server method is unavailable to a client handler | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 80 | `code/client-annotation-in-server-module` | warning | on | project | Client annotation in a server common module | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 81 | `code/client-module-in-http-service` | warning | on | project | Client common module in an HTTP service | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 82 | `code/query-needs-server` | error | on | project | A `Query{...}` block in a method of a client-side module (a form, or a common module whose `Environment` involves the client) that carries no `@OnServer` - the type does not exist on the client and the compiler rejects the build | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 83 | `code/local-method-cross-component` | warning | on | project | Cross-component call of a local method | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 84 | `code/local-method-cross-module` | error | on | project | Cross-module call of a local method | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 85 | `naming/yo` | warning | on | file | The letter yo in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 86 | `naming/underscore` | warning | on | file | Underscore in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 87 | `naming/abbreviation` | warning | on | file | All-caps abbreviation in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 88 | `naming/latin-term` | warning | on | file | English term spelled in Cyrillic | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 89 | `naming/enum-vid` | warning | on | file | Enumeration name with the word "Type" | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 90 | `naming/kind-in-name` | warning | on | file | Element kind inside its name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 91 | `naming/filler-word` | warning | on | file | Filler word in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 92 | `naming/module-suffix` | warning | on | file | Environment suffix in a common module name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 93 | `naming/number` | warning | on | file | Wrong number for the element kind | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 94 | `naming/boolean-name` | warning | on | file | Boolean attribute name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 95 | `naming/presentation` | warning | on | file | Element presentation | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 96 | `naming/prefix-by-kind` | warning | on | file | Kind-specific name without its prefix | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 97 | `code/unknown-ns-object` | warning | on | project | Unknown object in a kind namespace | – |
| 98 | `query/unknown-table` | warning | on | project | Unknown table in a query | [docs](https://1cmycloud.com/docs/help/topics/select-from/) |
| 99 | `query/in-subquery-composite` | warning | on | project | 'IN' with a subquery over a composite type | [docs](https://1cmycloud.com/docs/help/topics/in-expression/) |
| 100 | `yaml/unknown-property` | warning | on | file | Unknown object property | – |
| 101 | `code/reserved-name` | warning | on | file | Reserved name | – |
| 102 | `yaml/builtin-property-name` | warning | on | file | Built-in property name clash | – |
| 103 | `yaml/size-needs-no-stretch` | info | off | file | A size without disabling the stretch | [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| 104 | `code/unused-method` | warning | off | project | Method is never referenced | – |
| 105 | `yaml/missing-import` | warning | on | project | A yaml reference (a type position or a `FormType` navigation target) to a public element of another subsystem that the `Import` section does not list | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 106 | `yaml/presentation-field` | error | on | file | The presentation field of an object | [docs](https://1cmycloud.com/docs/help/topics/element-view/) |
| 107 | `yaml/unexpected-type-argument` | error | on | file | A type argument on a property the ui schema declares without one - another type, rejected when the build is applied (a form's `AdditionalCommands` takes `CommandInterfaceFragment`, not `CommandInterfaceFragment<UsualCommand>`) | [docs](https://1cmycloud.com/docs/help/topics/command-interface/) |
| 108 | `yaml/property-since-compat` | error | on | project | A component property newer than the project's `CompatibilityMode` (the ui schema records the version it appeared in) - apply rejects it as an unknown property | [docs](https://1cmycloud.com/docs/help/topics/update-server/) |
| 109 | `query/deletion-mark-immediate` | error | on | project | A deletion-mark condition in a query on an object whose `DeletionMode` is `Immediately` - such an object has no mark and the query fails on apply | [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| 110 | `yaml/item-id-required` | error | on | file | A metadata collection item (an attribute, a tabular section, an enumeration item, an access-key parameter) without the `Id` its class declares - apply answers `ID required` | – |
| 111 | `code/unknown-row-field` | error | on | project | A field addressed on a dynamic list row (`СтрокаДинамическогоСписка<Форма.Тип>`) that the list's `Поля` do not declare | [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| 112 | `code/row-field-null` | error | on | project | A dynamic list field taken through a reference (`Owner.Number`) is `<type>|Null` and cannot fill a typed structure field - the compiler answers `Null cannot be assigned` | [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| 113 | `yaml/unknown-attribute-property` | error | on | file | A key an attribute's own metamodel class does not declare (`Length` on a regular attribute - the built-in `Code` declares it, a Number attribute has `IntegerPartLength`) - apply rejects the object | – |
| 114 | `yaml/empty-group-sized` | warning | on | file | An empty `Group` with `Height`/`Width` – the renderer drops the node and there is no gap | – |
| 115 | `yaml/hint-too-long` | warning | on | file | A `Tooltip` longer than the render limit – the tail is not shown at all | – |
| 116 | `code/client-available-needs-context` | error | on | project | `@AvailableFromClient` on a method of an interface component module that is neither static nor `@Contextual` – the component type is not a singleton, so the apply rejects the modifier | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 117 | `code/server-module-in-client-context` | error | on | project | A `Module.Member(...)` access to a common module with `Environment: Server` from a method that runs on the client (an interface component, a command, a client common module) – the type does not exist on the client | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |

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

Twenty-one rules that follow the platform documentation ("Code style conventions" and "Language
idioms"): layout and expression wrapping, naming, type descriptions and signatures, collection
literals, string interpolation, and checks of boolean values and `Undefined`.

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
