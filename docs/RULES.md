---
title: "XBSL linter rules"
description: "The full list of linter checks, with severities and scope."
sidebar:
  label: Rules
  order: 5
---

<!-- severity icons -->
<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true"><symbol id="sev-error" viewBox="0 -960 960 960"><path fill="#e5484d" d="M508.5-291.5Q520-303 520-320t-11.5-28.5Q497-360 480-360t-28.5 11.5Q440-337 440-320t11.5 28.5Q463-280 480-280t28.5-11.5Zm0-160Q520-463 520-480v-160q0-17-11.5-28.5T480-680q-17 0-28.5 11.5T440-640v160q0 17 11.5 28.5T480-440q17 0 28.5-11.5ZM480-80q-83 0-158-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-158T197-763q54-54 127-85.5T480-880q83 0 158 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 158T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></symbol><symbol id="sev-warning" viewBox="0 -960 960 960"><path fill="#d0a215" d="M109-120q-11 0-20-5.5T75-140q-5-9-5.5-19.5T75-180l370-640q6-10 15.5-15t19.5-5q10 0 19.5 5t15.5 15l370 640q6 10 5.5 20.5T885-140q-5 9-14 14.5t-20 5.5H109Zm69-80h604L480-720 178-200Zm330.5-51.5Q520-263 520-280t-11.5-28.5Q497-320 480-320t-28.5 11.5Q440-297 440-280t11.5 28.5Q463-240 480-240t28.5-11.5Zm0-120Q520-383 520-400v-120q0-17-11.5-28.5T480-560q-17 0-28.5 11.5T440-520v120q0 17 11.5 28.5T480-360q17 0 28.5-11.5ZM480-460Z"/></symbol><symbol id="sev-info" viewBox="0 -960 960 960"><path fill="#3b82f6" d="M508.5-291.5Q520-303 520-320v-160q0-17-11.5-28.5T480-520q-17 0-28.5 11.5T440-480v160q0 17 11.5 28.5T480-280q17 0 28.5-11.5Zm0-320Q520-623 520-640t-11.5-28.5Q497-680 480-680t-28.5 11.5Q440-657 440-640t11.5 28.5Q463-600 480-600t28.5-11.5ZM480-80q-83 0-158-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-158T197-763q54-54 127-85.5T480-880q83 0 158 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 158T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></symbol></svg>


The full list of linter checks. This file is extended as rules are added; the live list at
runtime is `xbsl --list-rules` (or the MCP `list_rules`). Currently there are 168 rules.

The table describes the toolkit as it ships. An installed plugin may add rules of its own and
override severities and default states (see [Extending](/servers#extending-your-own-rules-data-and-severities)),
so the runtime list can differ from this one – `xbsl --list-rules` shows what your environment
actually runs, and `XBSL_NO_PLUGINS=1` shows the set below.

## Boundary: the linter complements the compiler, it does not replace it

The linter works over text, the AST and the project model. Its rules know types at the first
hop: the declared nominal type of a variable and its members, the project objects and the
types they generate, enumeration values, the global types of the linked libraries (from the
`.xlib` archive).

The engine DOES infer the type of an expression - `xbsl.typeinfer` answers for a receiver, a
member, a constructor, a cast and a non-null operator, and the inference of chains and locals
feeds hover and completion in the editor. The checks do not rest on it: the rules judge by the
declared types - see below on what the linter does not do.

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
- **Level** – <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> `error` (a build and CI should fail), <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> `warning` (a convention is broken),
  <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> `info` (a hint, usually off).
- **Default** – ✓ the rule is in the default set, – it is enabled explicitly.
- **Scope** – `file` (the rule sees one file) or `project` (needs the whole-project index:
  duplicate Ids, unknown types, cross-module calls).
- **The link at the end of a description** – the platform documentation section behind the rule.
  In VS Code the code of such a rule in the Problems panel opens that section right in the editor.

## Tiers

Rules are split into tiers A-D by what they rely on. A tier is also a quick filter for
`--select`/`--ignore` (alongside the group and the identifier): `--select A,B` runs only
structure and text, `--ignore D` drops the semantics over stdlib.

**Reading the columns:** <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> error · <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> warning · <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> info; ✓ – in the default set, – turned on explicitly; the scope is one file or the whole project.

### Tier A - structure and YAML

The file exists, parses, the object has a unique UUID, the name matches the file.

| Rule | | | Scope | What it checks |
|---|---|---|---|---|
| `yaml/valid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | YAML does not parse |
| `yaml/id-uuid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Id is not a UUID |
| `yaml/id-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | The object has no Id |
| `yaml/name-matches-file` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Name does not match the file name |
| `yaml/id-unique` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | Duplicate Id in the project |
| `yaml/standard-field-length` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A standard field longer than the platform limit (`Name` over 400 characters, `Code` over 50) - apply rejects the field and it drops out of the object [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/ref-needs-nullable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A reference type in a type position without `?` (`Goods.Reference`, `Edit<Goods.Reference>`) - a reference has no default value, the compilation fails with `Default value initialization is not supported` [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `yaml/no-expression-in-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | An `=...` expression inside a literal-typed node (`Font: {Type: AbsoluteFont, Size: =...}`) - the platform accepts only a literal there, compute the whole object instead [docs](https://1cmycloud.com/docs/help/topics/label-component/) |
| `yaml/localization-key-unique` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A key a `LocalizedStrings` dictionary declares twice - `Strings` and `Templates` share one namespace, and a translation file is judged too; the apply answers "Name is not unique" and rolls the project back [docs](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `yaml/unused-component` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | An interface component placed nowhere and created nowhere - neither as a `Type` value in the markup of another component nor by `new` in code. `code/unused-method` cannot see such a component in principle: its methods are called by its own yaml. In a yaml only a VALUE counts as a use (a name written as the KEY of a localization or translation dictionary does not), in a module any word of the text does, a comment and a string included. Never judged: an entry point (it inherits a client application, and the address reaches it) and a component with `VisibilityScope: Global` - the public surface of a library. The run has to cover a project: without the descriptor file (`Vendor` + `Version`) among the linted files the rule stays silent - on a subset a component placed outside it would look dead |
| `yaml/duplicate-subtree` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A markup subtree repeating, node for node, the shape of a subtree in ANOTHER file: names, ids and texts are left out of the shape - a new form is started by copying the neighbouring one, and the copy is renamed. The threshold is 40 nodes, and it is measured (at four nodes a live project answers with 294 groups, at forty with the two real copies, and a foreign corpus with none). A repeat inside ONE file is not judged - mirrored branches of a form are a layout, not a copy; the data source of a list is skipped (the query and the field set of two lists of one kind coincide by construction) and so is a localized-strings dictionary (its per-language twin repeats its shape by definition). Only MAXIMAL groups are named. Off by default: how much sameness is too much is a decision of the project |
| `project/identifier` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Project name or vendor is not an identifier [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/presentation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Project presentation is empty [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/version` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Project version is not A.B.C [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `structure/xbsl-pair` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Module .xbsl without a paired .yaml |
| `project/path-matches-descriptor` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The `{{vendor}}/{{name}}` path diverged from the descriptor – a build refuses the project before compiling [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `yaml/unknown-component-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A markup key the component does not declare while ANOTHER component of the ui schema does (`Checkbox` + `PlaceholderText`, a property of `Edit`) - apply rejects the markup node as an unknown property; a name no component declares is left alone, the documentation does not list the yaml keys in full [docs](https://1cmycloud.com/docs/help/topics/system-and-interface-components/) |

### Tier B - text and conventions

Encoding, newlines, whitespace, typography (dashes, quotes, ellipsis), line length, secrets
in the sources.

| Rule | | | Scope | What it checks |
|---|---|---|---|---|
| `security/hardcoded-secret` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A key or a password as a literal |
| `typography/em-dash` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | Em dash in a comment |
| `typography/ellipsis` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Ellipsis character in a comment |
| `typography/curly-quotes` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Curly quotes |
| `typography/guillemets-comment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | Guillemets in a comment |
| `typography/yo-in-text` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | Letter "ё" in interface text |
| `whitespace/trailing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Trailing whitespace |
| `whitespace/mixed-newline` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Mixed newlines |
| `encoding/utf8` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | File is not UTF-8 |
| `style/tab-indent` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Tab in the indentation [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/line-length` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Line longer than 120 characters [docs](https://1cmycloud.com/docs/help/topics/general-design/) |

### Tier C - code structure, basic syntax and code-writing conventions

Block and bracket balance, loop and method headers, local variables and the `style/` group -
conventions from the documentation section "Code-writing recommendations". Some `style/` rules
are off by default (accumulated debt, `info`): enable them with `--select style` to measure.

| Rule | | | Scope | What it checks |
|---|---|---|---|---|
| `code/parse-error` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Syntax error (a full parse against the platform grammar) [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/statement-no-effect` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Expression statement with no effect: the value is dropped (often a keyword typo, `retun 5` for `return 5`) |
| `code/return-mismatch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Return does not match the method signature (a value in a void method, a bare `return` in a typed one) - the compiler rejects such code [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/call-arity` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Argument count of a local call outside the method's [required, total] range [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/brackets` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Unbalanced brackets () [] {} |
| `code/blocks` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Unbalanced blocks and ';' [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/ternary-and-or` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Compound ternary condition without parentheses [docs](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| `code/query-in-loop` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A query inside a loop |
| `code/param-type-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Parameter without a type and without a default value [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/module-var-not-const` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A `var` / `val` / `use` declaration at MODULE level - only a constant lives there, an expression outside a method body is refused by the compiler and the apply rolls the project back [docs](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/loop-header` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Malformed 'for' loop header [docs](https://1cmycloud.com/docs/help/topics/for-in-loop/) |
| `code/invalid-string-escape` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Invalid escape sequence in a string literal (`\'`, regex-style `\d`) - the compiler rejects such a literal; valid are `\н \в \т \\ \" \% \$ \ю<code>` and the Latin spellings [docs](https://1cmycloud.com/docs/help/topics/escape-sequence/) |
| `code/unused-local` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Unused local variable |
| `code/unused-loop-var` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Unused loop variable |
| `code/ref-field-needs-req` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Structure reference field without 'req' [docs](https://1cmycloud.com/docs/help/topics/structure/) |
| `style/boolean-compare` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Comparing a boolean value with True/False [docs](https://1cmycloud.com/docs/help/topics/check-logical-values/) |
| `style/undefined-is` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Checking Undefined with the 'is' operator [docs](https://1cmycloud.com/docs/help/topics/check-if-undefined/) |
| `style/negated-is` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Negating the 'is' operator on the outside [docs](https://1cmycloud.com/docs/help/topics/is-operator/) |
| `style/semicolon-line` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | ';' not on its own line [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/wrap-operator` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Operator at the end of a wrapped line [docs](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/wrap-comma` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Comma at the start of a wrapped line [docs](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/camel-case` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Name is not in UpperCamelCase [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/const-case` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Constant is not in ALL_CAPS [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/exception-prefix` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Exception name without the exception marker - a prefix on a Russian name, the `Exception` suffix on a Latin one [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/abbreviation-case` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | All-caps abbreviation in a name [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/enum-name-vid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Enumeration name starts with "Type" [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/collection-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Manual collection fill instead of a literal [docs](https://1cmycloud.com/docs/help/topics/collection-literals-usage/) |
| `style/redundant-tostring` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | An explicit `ToString()` call in a concatenation [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/interpolation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Concatenation instead of interpolation [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/type-colon-space` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Spaces around the type colon [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/union-spaces` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Spaces around '\|' in a union type [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/nullable-shorthand` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Undefined in a type without the '?' shorthand [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/redundant-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Redundant type annotation on initialization [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/optional-params-last` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Optional parameter before a required one [docs](https://1cmycloud.com/docs/help/topics/method-declarations/) |
| `code/resource-bare-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | `Resource{Resources/<file>.svg}` - the key is a path RELATIVE to the Resources folder; spelling that folder out breaks the lookup [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| `query/named-parameter` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A named parameter `&Name` inside a query literal - the literal takes its values by interpolation (`%Name`) [docs](https://1cmycloud.com/docs/help/topics/query-literal/) |
| `code/this-in-static-method` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The keyword `this` inside the body of a static method - a static method is common to the whole type and has no object context, the compiler rejects the project [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/instance-call-from-static` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A bare call of an instance method of the same owner from a static method - the docs forbid it outright; call the method on a value or make it static [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/close-in-before-close` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | `Close()` inside `BeforeClose` – the platform ignores the call and nothing closes the form afterwards |
| `query/no-isnull` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | `ISNULL(` inside a query literal – the query language has no such function |
| `style/abstract-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | An abstract variable name (`Data`, `Item`, `Object`, `String`, `Value`, `Document` in either spelling - exact or with a digit tail like `Data1`) says nothing about the variable; a stem inside a longer name (`ClientData`) and structure fields (a serialization contract) are left alone [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/single-letter-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A single-letter name of a variable, parameter or loop variable - per the names standard one-letter names belong only to short lambda parameters (`(A, B) -> A + B`) [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/negated-boolean-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A boolean variable named from the negation (`NotConnected`, `NoErrors`) - the name comes from the affirmative (`Connected`, `HasErrors`); judged only where the boolean type is proven: a type annotation or a boolean literal initializer [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/type-in-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A variable name starting with a container type name (the Russian spellings of array, structure and map) - the type is visible from the declaration and the editor, keep it out of the name [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/numeral-in-const-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A spelled-out numeral in a constant name (`TIMEOUT_ONE_MINUTE`) describes the value - name the constant abstractly (`TIMEOUT`) so a value change does not break the name [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |

### Tier D - semantics over stdlib, forms and the metamodel

Needs the project index and platform data: unknown types and objects, enumeration values,
the execution model (client/server), form handlers, properties and queries.

| Rule | | | Scope | What it checks |
|---|---|---|---|---|
| `yaml/choice-needs-static-list` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | ValueChoice without a static `ChoiceList` [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru/) |
| `code/unknown-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown type |
| `code/catch-non-exception` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The type in `catch` is not an exception (a stdlib non-exception or a local `structure`) - the compiler rejects such code [docs](https://1cmycloud.com/docs/help/topics/exceptions/) |
| `code/unknown-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A member access on a variable of a known stdlib type - plain or a generic, whose arguments type the members and do not name them - that the type does not have (first hop, typos get a hint) |
| `code/unknown-static-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A member reached through a type name (`DateTime.Minimal()`) that the type does not have; the type of such a call carries on to the next hop. A bare name is read as a type only when the project gives it no other meaning; the module's paired yaml counts even in a single-file check |
| `yaml/foreign-not-public` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A yaml reference (a type position or a `FormType` navigation target) to an element of another subsystem whose `VisibilityScope` is not `InProject`/`Global` - unreachable from outside its subsystem, and no import helps [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/call-arity-cross` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | Argument count of a `<Module>.<Method>(...)` call outside the target module's signature range [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/undefined-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | Undefined name in an expression (a typo in a name) and in a short string interpolation (`"?$format=json"` substitutes the name `format`, `\$` is needed) - the compiler rejects such code |
| `code/unknown-object-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown project-object type |
| `yaml/unknown-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown type in yaml |
| `yaml/dynlist-missing-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Missing dynamic-list field [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/dynlist-row-editing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | An `OnRowEdit` handler on a list over a FLAT dynamic source: the event is declared for the node rows of a hierarchy, and on a flat list the platform never calls it - a click opens the object's automatic form instead; give the object its own object form [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/Lists/List_ru/) |
| `yaml/ref-input-auto-commands` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A reference `Edit` with no `Commands` of its own: the platform draws its own button that opens the value in a separate window (for a reference input `Auto` unfolds into a command-interface fragment). The button is usually wanted, so the rule is informational and off; an empty fragment silences it [docs](https://1cmycloud.com/docs/help/topics/edit-component/) |
| `yaml/toggle-command-pair` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Two adjacent `UsualCommand` nodes with mirrored `Visible` (`=X` against `=not X`) emulate one command with two states - the platform has the real thing: a `SwitchableCommand` carries the representations and images of both states, the initial `Active` is a literal, and the platform owns the state. A shared handler strengthens the case but is not required [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/Commands/SwitchableCommand_ru/) |
| `yaml/dynlist-column-sort-lost` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A column of a table over a dynamic list whose value CALLS something: the header will not sort, because the platform sorts by the FIELD of the source rather than by the text on screen. Bind the column to the field, or add a presentation field to the list itself. A column with `DisableSorting: True` is not judged – it has no sorting by declaration. Off by default: whether that column was meant to sort is not visible from the file [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/unknown-enum-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown enumeration value [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/enum-needs-nullable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Enumeration without nullable [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/unknown-enum-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A component property value outside the enumeration of the ui schema (`ContentVerticalAlign: End` - the vertical axis has `Top`, `Center`, `Bottom`, `Baseline` and no `End`) |
| `yaml/bare-object-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A bare word on a property that accepts `Object` - the platform expects a quoted literal, an `=` binding or a `$` localized-string reference [docs](https://1cmycloud.com/docs/help/topics/label-component/) |
| `code/unknown-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | The name in `Resource{...}` is neither in the project's `Resources` folders nor in the platform's image library [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| `form/unknown-handler` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Form handler not found in the module [docs](https://1cmycloud.com/docs/help/topics/form-component/) |
| `form/handler-signature` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Handler signature does not match the event [docs](https://1cmycloud.com/docs/help/topics/form-component/) |
| `code/server-call-from-handler` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Server method is unavailable to a client handler [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-annotation-in-server-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Client annotation in a server common module [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-module-in-http-service` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Client common module in an HTTP service [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/query-needs-server` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `Query{...}` block in a method of a client-side module (a form, or a common module whose `Environment` involves the client) that carries no `@OnServer` - the type does not exist on the client and the compiler rejects the build [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/local-method-cross-component` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Cross-component call of a local method [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/local-method-cross-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | Cross-module call of a local method [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `naming/yo` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | The letter yo in a name [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/underscore` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Underscore in a name [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/abbreviation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | All-caps abbreviation in a name [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/latin-term` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | English term spelled in Cyrillic [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/enum-vid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Enumeration name with the word "Type" [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/kind-in-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Element kind inside its name [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/filler-word` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Filler word in a name [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/module-suffix` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Environment suffix in a common module name [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/number` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Wrong number for the element kind [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/boolean-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Boolean attribute name [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/presentation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Element presentation [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/prefix-by-kind` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Kind-specific name without its prefix [docs](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `code/unknown-ns-object` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown object in a kind namespace |
| `query/unknown-table` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown table in a query [docs](https://1cmycloud.com/docs/help/topics/select-from/) |
| `query/in-subquery-composite` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | 'IN' with a subquery over a composite type [docs](https://1cmycloud.com/docs/help/topics/in-expression/) |
| `yaml/unknown-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Unknown object property |
| `code/reserved-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Reserved name |
| `yaml/builtin-property-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Built-in property name clash |
| `yaml/size-needs-no-stretch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A size without disabling the stretch [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/matrix-group-max-width` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A numeric `MaxWidth` on a group that lays out as a matrix: the maximum is also the AVAILABLE width, so the automatic columns are laid out by it rather than by the window and a phone draws the page at desktop width (the content runs off the right edge). Answer `Auto` instead. Off by default: a desktop-only page lives with a maximum fine [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/card-literal-stretch-weight` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A literal `StretchWeight` on a card or on a group inside one: the weight is a flex with a ZERO basis, and in a vertical column (the mobile layout) that basis applies to the HEIGHT - Safari collapses the card and clips it with the rounding, Chrome shows nothing. Drop the weight on a phone through a binding. Off by default: a card living only in a wide row keeps it legitimately [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `code/unused-method` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | Method is never referenced |
| `code/duplicate-method-body` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A method body repeated word for word in ANOTHER file: the normalized body (comments, blank lines and indentation dropped) of at least five lines is compared. A platform hook is told apart by its `@Handler` annotation rather than by a list of names - the same hook body in every object is normal; copies inside one file are not judged. Off by default: whether two copies should become one method is a design decision |
| `yaml/missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A yaml reference (a type position or a `FormType` navigation target) to a public element of another subsystem that the `Import` section does not list [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/unused-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A module imports a subsystem whose elements its CODE never mentions - the platform editor reports such imports, and they accumulate as the code that needed them is rewritten. A reference from the PAIRED yaml is not a use: the yaml has an import section of its own [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A module names the type of a public element of another subsystem without an import line for it - the project fails to compile at that line. Both WRITTEN type positions (a parameter, a variable, a return, `new`, `as`, `is`, generic arguments) and the root of a chain (`Module.Method()`) are judged; for a root everything that explains the name on its own is subtracted first: the declarations of the method and the module, the implicit names of the platform and the sections of the PAIRED yaml [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/missing-subsystem-usage` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Elements and modules of a subsystem import another subsystem while the description of their own (`Подсистема.yaml`) does not list it under `Using` - the project fails to apply, and that is learnt at deploy time. An import gives the short names, but it is `Using` that permits the subsystem; the diagnostic sits on the subsystem description, where the fix goes [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/presentation-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The presentation field of an object [docs](https://1cmycloud.com/docs/help/topics/element-view/) |
| `yaml/unexpected-type-argument` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A type argument on a property the ui schema declares without one - another type, rejected when the build is applied (a form's `AdditionalCommands` takes `CommandInterfaceFragment`, not `CommandInterfaceFragment<UsualCommand>`) [docs](https://1cmycloud.com/docs/help/topics/command-interface/) |
| `yaml/property-since-compat` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A component property newer than the project's `CompatibilityMode` (the ui schema records the version it appeared in) - apply rejects it as an unknown property [docs](https://1cmycloud.com/docs/help/topics/update-server/) |
| `query/deletion-mark-immediate` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A deletion-mark condition in a query on an object whose `DeletionMode` is `Immediately` - such an object has no mark and the query fails on apply [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/item-id-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A metadata collection item (an attribute, a tabular section, an enumeration item, an access-key parameter) without the `Id` its class declares - apply answers `ID required` |
| `code/unknown-row-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A field addressed on a dynamic list row (`DynamicListRow<Form.Type>`) that the list's `Fields` do not declare [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/row-field-null` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A dynamic list field taken through a reference (`Owner.Number`) is `<type>|Null` and cannot fill a typed structure field - the compiler answers `Null cannot be assigned` [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/unknown-attribute-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A key an attribute's own metamodel class does not declare (`Length` on a regular attribute - the built-in `Code` declares it, a Number attribute has `IntegerPartLength`) - apply rejects the object |
| `yaml/empty-group-sized` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | An empty `Group` with `Height`/`Width` – the renderer drops the node and there is no gap |
| `yaml/insert-row-needs-align` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A horizontal group holding an `HtmlContainer` insert and no `VerticalContentAlignment`: children are laid out on the BASELINE, and the insert carries one of its own, so the element holding it slides down against its neighbours (50 px on a live row). The nearest horizontal ancestor answers, so a row whose inner strip is already aligned stays silent [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/hint-too-long` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A `Tooltip` longer than the render limit – the tail is not shown at all |
| `yaml/date-input-needs-plain-date` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | `Edit<Date?>` – the renderer silently drops a date input that allows the empty value; make the type plain and express "not set" with the empty date [docs](https://1cmycloud.com/docs/help/topics/edit-component/) |
| `yaml/binding-needs-auto` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A binding of a plain component property calls a method declared nullable - the client registers an "unexpected Undefined value" error on every recomputation; "not set" is the Auto value |
| `code/client-available-needs-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | `@AvailableFromClient` on a method of an interface component module that is neither static nor `@Contextual` – the component type is not a singleton, so the apply rejects the modifier [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-available-unused` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A method declared `@AvailableFromClient` with no client place in the project naming it - neither a module of the client environment, nor a client method of a server module, nor a yaml, nor a string literal. The annotation opens a surface to the client that nobody uses. Off by default, like `code/unused-method`: a client call is not always visible statically [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/server-module-in-client-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `Module.Member(...)` access to a common module with `Environment: Server` from a method that runs on the client (an interface component, a command, a client common module) – the type does not exist on the client [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/component-in-server-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `Component.Member(...)` access to an interface component from code compiled for the server – a `@OnServer` method anywhere, or an unannotated method of a server or client-and-server module: the component's type lives on the client, and the server compilation refuses with "Variable X is not defined" [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `yaml/delete-current-needs-immediate` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | `OnReferencedObjectDeletion: DeleteCurrent` on an attribute whose owner has a `DeletionMode` that only marks (`DeletionMark` is also the default) – the apply answers `Action DeleteCurrent cannot apply to object with a DeletionMark` [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `code/access-context-read-noop` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Extending the access context with the read privilege for a type whose yaml says `Read: PermitEveryone`: everyone may read it already, so there is nothing to grant - the call only suggests the data is guarded. With that privilege alone the whole line goes; among others, only it does [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/per-object-permissions-need-common` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | An object calculates its permissions per object, but its module declares no `ComputeAccessPermissions` handler – the common calculation is required even then, if only to return an empty array [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-field-not-declared` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Inside `ComputeAccessPermissionsForObjects` a field outside `ComputePermissionsBy` is read, or a declared field is reached through `Entity` instead of the record [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-handlers-need-recalc` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A module declares a permission handler (`ComputeAccessPermissions` and kin) while the project calls `RecomputeAccessPermissions` for that entity nowhere - the platform never calls the handler by itself, so a permission edit silently does not act; a recompute with a non-entity receiver (the documented loop form) stands the rule down, kinds with no recompute method (rights elements) are not judged [docs](https://1cmycloud.com/docs/help/topics/recalculate-access-permissions-and-keys/) |
| `yaml/placeholder-key-in-strings` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A key carrying the placeholder `$0` in the `Strings` section of a `LocalizedStrings` dictionary: the section compiles to a method WITHOUT parameters, so a call with an argument fails the apply with an "unknown method" answer [docs](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `yaml/localization-ref-to-template` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `$Dictionary.Key` reference pointing at a key of the `Templates` section: a reference resolves against `Strings` alone, and the apply fails with "localized string not found" (the stand rolls back). A template key nobody references is left alone - code calls it legitimately [docs](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `code/compare-with-localized` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A localized value (`Dictionary.Key()`, `Presentation()`) compared against a literal or against a second localized value – in another language the branch simply never runs [docs](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `code/url-params-partial-encoding` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A call of the Url method `WithRequestParameters`: it encodes a parameter value only partially – "&" and "=" inside the value stay separators, and a value that is itself an address arrives cut at its first "&"; build the string with the parameters object and glue it to the base address. Off by default: whether a value can carry "&" is not statically visible [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Http/Url_ru/) |
| `code/bound-property-assign` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A property COMPUTED by an expression in the paired markup (`Height: =Common.IsNarrowScreen()?820:528`) is assigned from code - the platform refuses such an assignment, and inside a try/catch the refusal is invisible; a data binding (a bare path) is left alone, it is two-way by design |
| `yaml/event-needs-importance` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | An `EventLogEvent` description that does not set `Importance`: its default is `FromConstructor`, so the platform then demands the value in EVERY constructor, and one write that omits it fails the apply on the constructor line; an explicit `Importance: FromConstructor` states the choice and silences the rule [docs](https://1cmycloud.com/docs/help/topics/event-properties/) |
| `code/collection-field-needs-req` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A structure field whose generic type has no argument-less constructor (`ReadableArray<String>`) and no `req`, `?` or initializer - the apply answers "cannot be initialized with a default value"; `Array<String>` and the like are constructible empty and are left alone [docs](https://1cmycloud.com/docs/help/topics/structure/) |
| `code/var-needs-init` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A variable declared by type alone where the type has no constructor and no default value (`var Response: HttpResponse`) - the compilation answers "has neither a constructor nor a default value"; an enumeration, an annotation, a singleton and a name shadowed by a project type are skipped [docs](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/unknown-tabular-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A member access on a tabular section's row collection that the array type does not have (`Object.Section.Member` in an object form module, the bare section name or `this.Section` in the entity's modules) - the collection is `Array<Entity.Section>`, and the other platform's habitual `Count()` is called `Size()` here; a module named after the section shadows it, attributes are not judged |
| `code/global-unavailable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A call of a global name outside its environment: `Message` (client-only) in a server module - the apply answers "the method is unavailable in the current environment", the dynamic evaluation globals (server-only) in a client method without `@OnServer`; `@OnClient`/`@OnServer` override the module's environment, the availability comes from the per-member availability lines of the global context packages [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `style/shadow-project-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A variable, parameter or method named like a project element (a `Subscribers` variable next to the `Subscribers` catalog) - the declaration shadows the element for that scope; platform handler parameter names never collide with project names [docs](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `style/shadow-own-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A local VARIABLE named like a property of the element the module belongs to: inside the method the name resolves to the variable, so an assignment never reaches the property. Judged only where such a property is in scope - the module of an interface component and the object module; a parameter of that name is the ordinary way to pass a value in and is left alone [docs](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `code/unclosed-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A closeable resource (`val Selection = Query{...}.Execute()`) abandoned by an early exit from the loop over it: the platform closes a full pass by itself, while a `return` or a `break` in the middle leaves the resource open and the platform logs an unclosed-resource event; declaring the variable with `use` closes it on every exit path. A resource that arrived as a parameter, one the method closes by hand and one it returns to its caller are left to the author [docs](https://1cmycloud.com/docs/help/topics/closeable-type/) |
| `code/use-needs-closeable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The `use` modifier over a type the catalog describes and that does not inherit `Closeable` - the modifier exists for the automatic `Close()`, and the compiler refuses the declaration [docs](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `conventions/untranslated-visible-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Visible text left as a Cyrillic literal where the project already references the same property into a localization dictionary - the intent is counted per element kind, so a same-named property of another kind is not judged; silent on a project whose descriptor lists fewer than two localization languages |
| `conventions/untranslated-code-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | Visible text left as a Cyrillic literal in a MODULE - judged by the SINK it reaches (an argument of the platform message call, a property of an event-log event, or either of them one step away through a method that forwards its parameter); markup, pure interpolation and single words are skipped, and the rule is silent on a project whose descriptor lists fewer than two localization languages |
| `conventions/missing-translation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | project | A project token or a Cyrillic comment line the project's translation dictionary does not cover yet - one finding at its first occurrence in the file; silent unless an `xbsl-translation` dictionary lives next to (or above) the project (see `xbsl translate`) |
| `code/unknown-structure-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A field access on a structure declared IN THE PROJECT is checked against its declaration: rename a field and its reader in another module turns red here rather than on the server apply. The type comes from the variable's declaration (`Module.Structure`, a bare name for the declaring module), from a `new` constructor and from the element type of a `for X in List` loop; a name declared with anything else in the method, a namesake of a stdlib type, the second hop of a chain and Latin member spellings are not judged |

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

Four rules from the standard "Filling in the project properties": `Vendor` and `Name` are
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
For a Russian name this is morphology, not a guess by the ending: a singular noun that the
standard allows is told apart from a plural that reads as a genitive singular without the case.
Needs the `[morph]` extra (`pip install "xbsl[morph]"`); without it Russian names stay silent.
An English name (a translated tree) is judged by its last word with suffix heuristics and the
irregular plurals listed, and needs no extra; mass nouns and ambiguous tails are left undecided.

The rest: the letter yo and underscores in names, an abbreviation written in mixed case instead
of all caps, an English term transliterated rather than kept as the original (`Xml`, not its
Cyrillic spelling), an enumeration named with the word for type where the standard asks for the
word for kind, the element kind repeated inside its own name, filler words such as the ones for
management or manager, an environment suffix on a common module name (the environment is a
property, not a name), a boolean attribute named by a negation instead of the positive form, an
empty `Presentation`, and the prefixes required for certain kinds - access key, right and
navigation.

### Code style conventions (the `style/` rules)

Twenty-eight rules that follow the platform documentation ("Code style conventions", "Language
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

### Code semantics (the `code/` rules)

The largest group - fifty-three rules, thirty of them errors. This is what the compiler rejects
or what the platform does differently from how the code reads: an unknown name or member, the
arity of a call, the environment (client code in a server method and the other way round), an
instance reached through its type, a caught non-exception, an unclosed resource, a walk over a
collection while it is being changed, and the platform traps whose only sign is the shape of the
code. Some of the rules are project-scoped (`--stdin` does not run those): they need the paired
yaml and the names of the objects.

### Element descriptions (the `yaml/` rules)

Thirty-nine rules over the descriptions (`.yaml`): required and unique ids, known keys and types,
references to components, handlers and localized strings, what the platform requires of field
types (a reference and an enumeration admit an empty value), the settings of dynamic lists and
forms, and the layout traps that apply without an error yet draw differently from the intent.
Five rules are `info` and off: they say "this is how the platform works", not "this is a mistake".

### Project conventions (the `conventions/` rules)

Rules about what the PROJECT agreed on rather than what the platform demands. The base set
carries the bilingual-project family: `conventions/untranslated-visible-literal` (on by
default) reports visible text left as a Cyrillic literal where the project already routes the
same property through the localization dictionary, and `conventions/untranslated-code-literal`
with `conventions/missing-translation` (both off) extend that to module literals and to the
translation dictionary - whether every human-readable string must come from the dictionary is
a per-project decision, so the base set does not impose it.

The group is also the extension point by design: a project plugin registers its own house
rules under `conventions/` (a ban on task numbers in comments, internal references and the
like) and decides their severity and defaults for that project - see
[Extending](/servers#extending-your-own-rules-data-and-severities). Runtime truth is
`xbsl --list-rules`; the table above lists the base set only.

### The small groups

- `typography/` - typographic characters in prose and comments: em dash, the ellipsis character,
  curly quotes, guillemets in comments, plus the letter "ё" in the text a user reads;
- `whitespace/` - trailing spaces and mixed newlines;
- `encoding/` - a file that is not UTF-8;
- `structure/` - the pairing of `Name.yaml` and `Name.xbsl`;
- `security/` - a secret in the sources (a token, a password, a key);
- `form/` - a form handler the module does not have, and a handler whose signature
  contradicts the event of the component (project-scoped rules);
- `query/` - queries: an unknown table, `ISNULL`, a named parameter, an immediate deletion mark
  and the standard about `IN` with a subquery (discussed above).

## Enabling and disabling

`--select` and `--ignore` accept a rule identifier, a group (the part before `/`, e.g. `style`)
or a tier letter `A`/`B`/`C`/`D`. A plugin may override a rule's severity (the `xbsl.severity`
entry-points group); `XBSL_NO_PLUGINS=1` disables plugins and restores the built-in values from
this table.
