---
title: "XBSL linter rules"
description: "The full list of linter checks, with severities and scope."
sidebar:
  label: Rules
  order: 5
---

The full list of linter checks. This file is extended as rules are added; the live list at
runtime is `xbsl --list-rules` (or the MCP `list_rules`). Currently there are 139 rules.

The table describes the toolkit as it ships. An installed plugin may add rules of its own and
override severities and default states (see [Extending](/servers#extending-your-own-rules-data-and-severities)),
so the runtime list can differ from this one – `xbsl --list-rules` shows what your environment
actually runs, and `XBSL_NO_PLUGINS=1` shows the set below.

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
- **Level** – <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> `error` (a build and CI should fail), <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> `warning` (a convention is broken),
  <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> `info` (a hint, usually off).
- **Default** – ✓ the rule is in the default set, – it is enabled explicitly.
- **Scope** – `file` (the rule sees one file) or `project` (needs the whole-project index:
  duplicate Ids, unknown types, cross-module calls).
- **Docs** – a link to the platform documentation section behind the rule. In VS Code the code
  of such a rule in the Problems panel opens that section right in the editor.

## Tiers

Rules are split into tiers A-D by what they rely on. A tier is also a quick filter for
`--select`/`--ignore` (alongside the group and the identifier): `--select A,B` runs only
structure and text, `--ignore D` drops the semantics over stdlib.

**Reading the columns:** <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> error · <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> warning · <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> info; ✓ – in the default set, – turned on explicitly; the scope is one file or the whole project.

### Tier A - structure and YAML

The file exists, parses, the object has a unique UUID, the name matches the file.

| Rule | | | Scope | What it checks | Docs |
|---|---|---|---|---|---|
| `yaml/valid` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | YAML does not parse | – |
| `yaml/id-uuid` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Id is not a UUID | – |
| `yaml/id-required` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | The object has no Id | – |
| `yaml/name-matches-file` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Name does not match the file name | – |
| `yaml/id-unique` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | Duplicate Id in the project | – |
| `yaml/standard-field-length` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A standard field longer than the platform limit (`Name` over 400 characters, `Code` over 50) - apply rejects the field and it drops out of the object | [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/ref-needs-nullable` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A reference type in a type position without `?` (`Goods.Reference`, `Edit<Goods.Reference>`) - a reference has no default value, the compilation fails with `Default value initialization is not supported` | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `yaml/no-expression-in-literal` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | An `=...` expression inside a literal-typed node (`Font: {Type: AbsoluteFont, Size: =...}`) - the platform accepts only a literal there, compute the whole object instead | [docs](https://1cmycloud.com/docs/help/topics/label-component/) |
| `project/identifier` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Project name or vendor is not an identifier | [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/presentation` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Project presentation is empty | [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/version` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Project version is not A.B.C | [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `structure/xbsl-pair` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Module .xbsl without a paired .yaml | – |
| `project/path-matches-descriptor` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | The `{{vendor}}/{{name}}` path diverged from the descriptor – a build refuses the project before compiling | [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `yaml/unknown-component-property` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A markup key the component does not declare while ANOTHER component of the ui schema does (`Checkbox` + `PlaceholderText`, a property of `Edit`) - apply rejects the markup node as an unknown property; a name no component declares is left alone, the documentation does not list the yaml keys in full | [docs](https://1cmycloud.com/docs/help/topics/system-and-interface-components/) |

### Tier B - text and conventions

Encoding, newlines, whitespace, typography (dashes, quotes, ellipsis), line length, secrets
in the sources.

| Rule | | | Scope | What it checks | Docs |
|---|---|---|---|---|---|
| `security/hardcoded-secret` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A key or a password as a literal | – |
| `typography/em-dash` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> | – | file | Em dash in a comment | – |
| `typography/ellipsis` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Ellipsis character in a comment | – |
| `typography/curly-quotes` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Curly quotes | – |
| `typography/guillemets-comment` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> | – | file | Guillemets in a comment | – |
| `whitespace/trailing` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Trailing whitespace | – |
| `whitespace/mixed-newline` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Mixed newlines | – |
| `encoding/utf8` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | File is not UTF-8 | – |
| `style/tab-indent` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Tab in the indentation | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/line-length` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Line longer than 120 characters | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |

### Tier C - code structure, basic syntax and code-writing conventions

Block and bracket balance, loop and method headers, local variables and the `style/` group -
conventions from the documentation section "Code-writing recommendations". Some `style/` rules
are off by default (accumulated debt, `info`): enable them with `--select style` to measure.

| Rule | | | Scope | What it checks | Docs |
|---|---|---|---|---|---|
| `code/parse-error` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Syntax error (a full parse against the platform grammar) | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/statement-no-effect` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Expression statement with no effect: the value is dropped (often a keyword typo, `retun 5` for `return 5`) | – |
| `code/return-mismatch` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Return does not match the method signature (a value in a void method, a bare `return` in a typed one) - the compiler rejects such code | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/call-arity` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Argument count of a local call outside the method's [required, total] range | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/brackets` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Unbalanced brackets () [] {} | – |
| `code/blocks` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Unbalanced blocks and ';' | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/ternary-and-or` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Compound ternary condition without parentheses | [docs](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| `code/param-type-required` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Parameter without a type and without a default value | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/loop-header` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Malformed 'for' loop header | [docs](https://1cmycloud.com/docs/help/topics/for-in-loop/) |
| `code/invalid-string-escape` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Invalid escape sequence in a string literal (`\'`, regex-style `\d`) - the compiler rejects such a literal; valid are `\н \в \т \\ \" \% \$ \ю<code>` and the Latin spellings | [docs](https://1cmycloud.com/docs/help/topics/escape-sequence/) |
| `code/unused-local` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Unused local variable | – |
| `code/unused-loop-var` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Unused loop variable | – |
| `code/ref-field-needs-req` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | Structure reference field without 'req' | [docs](https://1cmycloud.com/docs/help/topics/structure/) |
| `style/boolean-compare` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Comparing a boolean value with True/False | [docs](https://1cmycloud.com/docs/help/topics/check-logical-values/) |
| `style/undefined-is` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Checking Undefined with the 'is' operator | [docs](https://1cmycloud.com/docs/help/topics/check-if-undefined/) |
| `style/negated-is` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Negating the 'is' operator on the outside | [docs](https://1cmycloud.com/docs/help/topics/is-operator/) |
| `style/semicolon-line` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | ';' not on its own line | [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/wrap-operator` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Operator at the end of a wrapped line | [docs](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/wrap-comma` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Comma at the start of a wrapped line | [docs](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/camel-case` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Name is not in UpperCamelCase | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/const-case` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Constant is not in ALL_CAPS | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/exception-prefix` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Exception name without the exception prefix | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/abbreviation-case` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | All-caps abbreviation in a name | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/enum-name-vid` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Enumeration name starts with "Type" | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/collection-literal` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Manual collection fill instead of a literal | [docs](https://1cmycloud.com/docs/help/topics/collection-literals-usage/) |
| `style/redundant-tostring` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | An explicit `ToString()` call in a concatenation | [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/interpolation` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Concatenation instead of interpolation | [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/type-colon-space` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Spaces around the type colon | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/union-spaces` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Spaces around '\|' in a union type | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/nullable-shorthand` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Undefined in a type without the '?' shorthand | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/redundant-type` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Redundant type annotation on initialization | [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/optional-params-last` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Optional parameter before a required one | [docs](https://1cmycloud.com/docs/help/topics/method-declarations/) |
| `code/resource-bare-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | `Resource{Resources/<file>.svg}` - the key is a path RELATIVE to the Resources folder; spelling that folder out breaks the lookup | [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| `query/named-parameter` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A named parameter `&Name` inside a query literal - the literal takes its values by interpolation (`%Name`) | [docs](https://1cmycloud.com/docs/help/topics/query-literal/) |
| `code/this-in-static-method` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | The keyword `this` inside the body of a static method - a static method is common to the whole type and has no object context, the compiler rejects the project | [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/instance-call-from-static` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A bare call of an instance method of the same owner from a static method - the docs forbid it outright; call the method on a value or make it static | [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/close-in-before-close` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | `Close()` inside `BeforeClose` – the platform ignores the call and nothing closes the form afterwards | – |
| `query/no-isnull` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | `ISNULL(` inside a query literal – the query language has no such function | – |
| `style/abstract-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | An abstract variable name (`Data`, `Item`, `Object`, `String`, `Value`, `Document` in either spelling - exact or with a digit tail like `Data1`) says nothing about the variable; a stem inside a longer name (`ClientData`) and structure fields (a serialization contract) are left alone | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/single-letter-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | A single-letter name of a variable, parameter or loop variable - per the names standard one-letter names belong only to short lambda parameters (`(A, B) -> A + B`) | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/negated-boolean-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | A boolean variable named from the negation (`NotConnected`, `NoErrors`) - the name comes from the affirmative (`Connected`, `HasErrors`); judged only where the boolean type is proven: a type annotation or a boolean literal initializer | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/type-in-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | A variable name starting with a container type name (the Russian spellings of array, structure and map) - the type is visible from the declaration and the editor, keep it out of the name | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/numeral-in-const-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | A spelled-out numeral in a constant name (`TIMEOUT_ONE_MINUTE`) describes the value - name the constant abstractly (`TIMEOUT`) so a value change does not break the name | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |

### Tier D - semantics over stdlib, forms and the metamodel

Needs the project index and platform data: unknown types and objects, enumeration values,
the execution model (client/server), form handlers, properties and queries.

| Rule | | | Scope | What it checks | Docs |
|---|---|---|---|---|---|
| `yaml/choice-needs-static-list` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | ValueChoice without a static `ChoiceList` | [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru/) |
| `code/unknown-type` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Unknown type | – |
| `code/catch-non-exception` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | The type in `catch` is not an exception (a stdlib non-exception or a local `structure`) - the compiler rejects such code | [docs](https://1cmycloud.com/docs/help/topics/exceptions/) |
| `code/unknown-member` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A member access on a variable of a known stdlib type - plain or a generic, whose arguments type the members and do not name them - that the type does not have (first hop, typos get a hint) | – |
| `code/unknown-static-member` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A member reached through a type name (`DateTime.Minimal()`) that the type does not have; the type of such a call carries on to the next hop. A bare name is read as a type only when the project gives it no other meaning; the module's paired yaml counts even in a single-file check | – |
| `yaml/foreign-not-public` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A yaml reference (a type position or a `FormType` navigation target) to an element of another subsystem whose `VisibilityScope` is not `InProject`/`Global` - unreachable from outside its subsystem, and no import helps | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/call-arity-cross` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | Argument count of a `<Module>.<Method>(...)` call outside the target module's signature range | [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/undefined-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | Undefined name in an expression (a typo in a name) and in a short string interpolation (`"?$format=json"` substitutes the name `format`, `\$` is needed) - the compiler rejects such code | – |
| `code/unknown-object-type` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Unknown project-object type | – |
| `yaml/unknown-type` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Unknown type in yaml | – |
| `yaml/dynlist-missing-field` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Missing dynamic-list field | [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/unknown-enum-value` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Unknown enumeration value | [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/enum-needs-nullable` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Enumeration without nullable | [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/unknown-enum-value` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A component property value outside the enumeration of the ui schema (`ContentVerticalAlign: End` - the vertical axis has `Top`, `Center`, `Bottom`, `Baseline` and no `End`) | – |
| `yaml/bare-object-value` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A bare word on a property that accepts `Object` - the platform expects a quoted literal, an `=` binding or a `$` localized-string reference | [docs](https://1cmycloud.com/docs/help/topics/label-component/) |
| `code/unknown-resource` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | The name in `Resource{...}` is neither in the project's `Resources` folders nor in the platform's image library | [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| `form/unknown-handler` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Form handler not found in the module | [docs](https://1cmycloud.com/docs/help/topics/form-component/) |
| `code/server-call-from-handler` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Server method is unavailable to a client handler | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-annotation-in-server-module` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Client annotation in a server common module | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-module-in-http-service` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Client common module in an HTTP service | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/query-needs-server` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A `Query{...}` block in a method of a client-side module (a form, or a common module whose `Environment` involves the client) that carries no `@OnServer` - the type does not exist on the client and the compiler rejects the build | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/local-method-cross-component` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Cross-component call of a local method | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/local-method-cross-module` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | Cross-module call of a local method | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `naming/yo` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | The letter yo in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/underscore` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Underscore in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/abbreviation` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | All-caps abbreviation in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/latin-term` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | English term spelled in Cyrillic | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/enum-vid` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Enumeration name with the word "Type" | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/kind-in-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Element kind inside its name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/filler-word` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Filler word in a name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/module-suffix` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Environment suffix in a common module name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/number` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Wrong number for the element kind | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/boolean-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Boolean attribute name | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/presentation` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Element presentation | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/prefix-by-kind` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Kind-specific name without its prefix | [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `code/unknown-ns-object` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Unknown object in a kind namespace | – |
| `query/unknown-table` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Unknown table in a query | [docs](https://1cmycloud.com/docs/help/topics/select-from/) |
| `query/in-subquery-composite` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | 'IN' with a subquery over a composite type | [docs](https://1cmycloud.com/docs/help/topics/in-expression/) |
| `yaml/unknown-property` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Unknown object property | – |
| `code/reserved-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Reserved name | – |
| `yaml/builtin-property-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | Built-in property name clash | – |
| `yaml/size-needs-no-stretch` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> | – | file | A size without disabling the stretch | [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `code/unused-method` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | – | project | Method is never referenced | – |
| `yaml/missing-import` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | A yaml reference (a type position or a `FormType` navigation target) to a public element of another subsystem that the `Import` section does not list | [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/presentation-field` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | The presentation field of an object | [docs](https://1cmycloud.com/docs/help/topics/element-view/) |
| `yaml/unexpected-type-argument` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A type argument on a property the ui schema declares without one - another type, rejected when the build is applied (a form's `AdditionalCommands` takes `CommandInterfaceFragment`, not `CommandInterfaceFragment<UsualCommand>`) | [docs](https://1cmycloud.com/docs/help/topics/command-interface/) |
| `yaml/property-since-compat` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A component property newer than the project's `CompatibilityMode` (the ui schema records the version it appeared in) - apply rejects it as an unknown property | [docs](https://1cmycloud.com/docs/help/topics/update-server/) |
| `query/deletion-mark-immediate` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A deletion-mark condition in a query on an object whose `DeletionMode` is `Immediately` - such an object has no mark and the query fails on apply | [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/item-id-required` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A metadata collection item (an attribute, a tabular section, an enumeration item, an access-key parameter) without the `Id` its class declares - apply answers `ID required` | – |
| `code/unknown-row-field` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A field addressed on a dynamic list row (`DynamicListRow<Form.Type>`) that the list's `Fields` do not declare | [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/row-field-null` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A dynamic list field taken through a reference (`Owner.Number`) is `<type>|Null` and cannot fill a typed structure field - the compiler answers `Null cannot be assigned` | [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/unknown-attribute-property` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A key an attribute's own metamodel class does not declare (`Length` on a regular attribute - the built-in `Code` declares it, a Number attribute has `IntegerPartLength`) - apply rejects the object | – |
| `yaml/empty-group-sized` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | An empty `Group` with `Height`/`Width` – the renderer drops the node and there is no gap | – |
| `yaml/hint-too-long` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | A `Tooltip` longer than the render limit – the tail is not shown at all | – |
| `code/client-available-needs-context` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | `@AvailableFromClient` on a method of an interface component module that is neither static nor `@Contextual` – the component type is not a singleton, so the apply rejects the modifier | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/server-module-in-client-context` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A `Module.Member(...)` access to a common module with `Environment: Server` from a method that runs on the client (an interface component, a command, a client common module) – the type does not exist on the client | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `yaml/delete-current-needs-immediate` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | `OnReferencedObjectDeletion: DeleteCurrent` on an attribute whose owner has a `DeletionMode` that only marks (`DeletionMark` is also the default) – the apply answers `Action DeleteCurrent cannot apply to object with a DeletionMark` | [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `code/per-object-permissions-need-common` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | An object calculates its permissions per object, but its module declares no `ComputeAccessPermissions` handler – the common calculation is required even then, if only to return an empty array | [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-field-not-declared` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Inside `ComputeAccessPermissionsForObjects` a field outside `ComputePermissionsBy` is read, or a declared field is reached through `Entity` instead of the record | [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `yaml/placeholder-key-in-strings` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A key carrying the placeholder `$0` in the `Strings` section of a `LocalizedStrings` dictionary: the section compiles to a method WITHOUT parameters, so a call with an argument fails the apply with an "unknown method" answer | [docs](https://1cmycloud.com/docs/help/topics/localization/) |
| `code/compare-with-localized` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | A localized value (`Dictionary.Key()`, `Presentation()`) compared against a literal or against a second localized value – in another language the branch simply never runs | [docs](https://1cmycloud.com/docs/help/topics/localization/) |
| `code/bound-property-assign` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | A property COMPUTED by an expression in the paired markup (`Height: =Common.IsMobile()?820:528`) is assigned from code - the platform refuses such an assignment, and inside a try/catch the refusal is invisible; a data binding (a bare path) is left alone, it is two-way by design | – |
| `yaml/event-needs-importance` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | An `EventLogEvent` description that does not set `Importance`: its default is `FromConstructor`, so the platform then demands the value in EVERY constructor, and one write that omits it fails the apply on the constructor line; an explicit `Importance: FromConstructor` states the choice and silences the rule | [docs](https://1cmycloud.com/docs/help/topics/event-properties/) |
| `code/collection-field-needs-req` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | file | A structure field whose generic type has no argument-less constructor (`ReadableArray<String>`) and no `req`, `?` or initializer - the apply answers "cannot be initialized with a default value"; `Array<String>` and the like are constructible empty and are left alone | [docs](https://1cmycloud.com/docs/help/topics/structure/) |
| `code/var-needs-init` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | A variable declared by type alone where the type has no constructor and no default value (`var Response: HttpResponse`) - the compilation answers "has neither a constructor nor a default value"; an enumeration, an annotation, a singleton and a name shadowed by a project type are skipped | [docs](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/unknown-tabular-member` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A member access on a tabular section's row collection that the array type does not have (`Object.Section.Member` in an object form module, the bare section name or `this.Section` in the entity's modules) - the collection is `Array<Entity.Section>`, and the other platform's habitual `Count()` is called `Size()` here; a module named after the section shadows it, attributes are not judged | – |
| `code/global-unavailable` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A call of a global name outside its environment: `Message` (client-only) in a server module - the apply answers "the method is unavailable in the current environment", the dynamic evaluation globals (server-only) in a client method without `@OnServer`; `@OnClient`/`@OnServer` override the module's environment, the availability comes from the per-member availability lines of the global context packages | [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `style/shadow-project-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | A variable, parameter or method named like a project element (a `Subscribers` variable next to the `Subscribers` catalog) - the declaration shadows the element for that scope; platform handler parameter names never collide with project names | [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `code/unclosed-resource` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | file | A closeable resource (`val Selection = Query{...}.Execute()`) abandoned by an early exit from the loop over it: the platform closes a full pass by itself, while a `return` or a `break` in the middle leaves the resource open and the platform logs an unclosed-resource event; declaring the variable with `use` closes it on every exit path. A resource that arrived as a parameter, one the method closes by hand and one it returns to its caller are left to the author | [docs](https://1cmycloud.com/docs/help/topics/closeable-type/) |
| `conventions/untranslated-visible-literal` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | project | Visible text left as a Cyrillic literal where the project already references the same property into a localization dictionary - the intent is counted per element kind, so a same-named property of another kind is not judged; silent on a project whose descriptor lists fewer than two localization languages | – |
| `conventions/untranslated-code-literal` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | – | project | Visible text left as a Cyrillic literal in a MODULE - judged by the SINK it reaches (an argument of the platform message call, a property of an event-log event, or either of them one step away through a method that forwards its parameter); markup, pure interpolation and single words are skipped, and the rule is silent on a project whose descriptor lists fewer than two localization languages | – |
| `code/unknown-structure-field` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | project | A field access on a structure declared IN THE PROJECT is checked against its declaration: rename a field and its reader in another module turns red here rather than on the server apply. The type comes from the variable's declaration (`Module.Structure`, a bare name for the declaring module), from a `new` constructor and from the element type of a `for X in List` loop; a name declared with anything else in the method, a namesake of a stdlib type, the second hop of a chain and Latin member spellings are not judged | – |

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
