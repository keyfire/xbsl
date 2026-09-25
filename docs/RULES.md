---
title: "XBSL linter rules"
description: "The full list of linter checks, with severities and scope."
sidebar:
  label: Rules
  order: 5
---

<!-- severity icons -->
<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true"><symbol id="sev-error" viewBox="0 -960 960 960"><path fill="#e5484d" d="M508.5-291.5Q520-303 520-320t-11.5-28.5Q497-360 480-360t-28.5 11.5Q440-337 440-320t11.5 28.5Q463-280 480-280t28.5-11.5Zm0-160Q520-463 520-480v-160q0-17-11.5-28.5T480-680q-17 0-28.5 11.5T440-640v160q0 17 11.5 28.5T480-440q17 0 28.5-11.5ZM480-80q-83 0-158-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-158T197-763q54-54 127-85.5T480-880q83 0 158 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 158T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></symbol><symbol id="sev-warning" viewBox="0 -960 960 960"><path fill="#d0a215" d="M109-120q-11 0-20-5.5T75-140q-5-9-5.5-19.5T75-180l370-640q6-10 15.5-15t19.5-5q10 0 19.5 5t15.5 15l370 640q6 10 5.5 20.5T885-140q-5 9-14 14.5t-20 5.5H109Zm69-80h604L480-720 178-200Zm330.5-51.5Q520-263 520-280t-11.5-28.5Q497-320 480-320t-28.5 11.5Q440-297 440-280t11.5 28.5Q463-240 480-240t28.5-11.5Zm0-120Q520-383 520-400v-120q0-17-11.5-28.5T480-560q-17 0-28.5 11.5T440-520v120q0 17 11.5 28.5T480-360q17 0 28.5-11.5ZM480-460Z"/></symbol><symbol id="sev-info" viewBox="0 -960 960 960"><path fill="#3b82f6" d="M508.5-291.5Q520-303 520-320v-160q0-17-11.5-28.5T480-520q-17 0-28.5 11.5T440-480v160q0 17 11.5 28.5T480-280q17 0 28.5-11.5Zm0-320Q520-623 520-640t-11.5-28.5Q497-680 480-680t-28.5 11.5Q440-657 440-640t11.5 28.5Q463-600 480-600t28.5-11.5ZM480-80q-83 0-158-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-158T197-763q54-54 127-85.5T480-880q83 0 158 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 158T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></symbol></svg>


The full list of linter checks. This file is extended as rules are added, and the live list comes
from `xbsl --list-rules` or the MCP `list_rules`. Currently there are 251 rules.

The table describes the toolkit as it ships. An installed plugin may add rules of its own and
override severities and default states (see [Extending](/servers#extending-your-own-rules-data-and-severities)),
so the live list can differ from this one. `xbsl --list-rules` shows what your environment
actually runs, and `XBSL_NO_PLUGINS=1` shows the set below.

## Boundary: the linter complements the compiler, it does not replace it

The linter works over text, the AST and the project model. Its rules know types at the first
hop: the declared nominal type of a variable and its members, the project objects and the
types they generate, enumeration values, the global types of the linked libraries (from the
`.xlib` archive).

The engine does infer the type of an expression. `xbsl.typeinfer` answers for a receiver, a
member, a constructor, a cast and a non-null operator, and the inference of chains and locals
feeds hover and completion in the editor. Over a whole project it answers with a set of types that
keeps a union, the empty value and the `Null` of a query column, and it knows the project's own
names: the rows of `Query{...}` are typed by the select list, the attributes by the yaml, the
structures and methods by the modules. Five rules judge an inferred type and repeat warnings of the
platform IDE: `code/redundant-cast`, `code/cast-to-non-null`, `code/redundant-undefined-guard` and
`code/redundant-type-check`, plus `code/deprecated-api` for overload selection. They say nothing about an expression whose type the inference cannot
name. The other rules judge by the declared types.

Some of the findings the compiler would catch as well: an unknown type, an argument count, a
non-exception in `catch`, a return not matching the signature. The linter's value there is
timing. It shows them **earlier**, in seconds on your own machine, before the build and the
deploy, and it points at the exact spot. The rest the compiler never checks at all: code-writing
conventions, typography, project structure (duplicate `Id`, file pairing), secrets in the sources.
Unused variables and imports get only a warning in the platform IDE, and a build goes through
with them.

What the linter does not do is anything that needs full inference of expression types: a leaked
resource in the general case, whether the type of a returned value matches the signature. Those
two are worth separating. A structural return mismatch - a value in a void method, a bare `return`
in a typed one - is caught by `code/return-mismatch`. A `return` of a string from a method declared
`: Number` slips through, because telling that apart needs the expression's type. A resource is
judged only in the one shape where the declaration itself says everything: `code/unclosed-resource`
follows a closeable from its declaration to the loop over it in the same method. A resource that
travels through calls or collections stays out of reach.

Code correctness is verified by the server-side compilation on deploy. The linter runs before it
and removes common mistakes early.

## How to read the table

- **Rule** – the `group/name` identifier. The group (the part before `/`) lets you enable and
  disable rules in bulk.
- **Level** – <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> `error` (a build and CI should fail), <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> `warning` (a convention is broken),
  <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> `info` (a hint, usually off).
- **Default** – ✓ the rule is in the default set, – it is enabled explicitly.
- **Scope** – `file` (the rule sees one file) or `project` (needs the whole-project index:
  duplicate Ids, unknown types, cross-module calls).
- **What it checks** – a sentence or two about the finding. A "details" link leads below the
  tier table, where the exceptions, the examples and the answer of the platform live.
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
| `yaml/duplicate-key` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A scalar key set twice in one YAML mapping: the loader silently keeps the last value, and the compiler rejects the file on deploy [details](#a-yaml-duplicate-key) |
| `yaml/duplicate-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A namespace repeated in the `Import` section of an element: the second entry adds nothing [details](#a-yaml-duplicate-import) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/id-uuid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Id is not a UUID |
| `yaml/id-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | The object has no Id |
| `yaml/name-matches-file` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Name does not match the file name |
| `yaml/id-unique` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | Duplicate Id in the project |
| `yaml/standard-field-length` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A standard field longer than the platform limit (`Name` over 400 characters, `Code` over 50) - apply rejects the field and it drops out of the object [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/ref-needs-nullable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A reference type in a type position without `?`: a reference has no default value, so the compilation fails [details](#a-yaml-ref-needs-nullable) [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `yaml/no-expression-in-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | An `=...` expression inside a literal-typed node (`Font: {Type: AbsoluteFont, Size: =...}`) - the platform accepts only a literal there, compute the whole object instead [docs](https://1cmycloud.com/docs/help/topics/label-component/) |
| `yaml/localization-key-unique` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A key declared twice in a `LocalizedStrings` dictionary: the apply rejects the whole project [details](#a-yaml-localization-key-unique) [docs](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `yaml/unused-component` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | An interface component placed nowhere and created nowhere: neither as a `Type` value in markup nor by `new` in code. Dead markup ships with the build and the translation [details](#a-yaml-unused-component) |
| `yaml/duplicate-subtree` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A markup subtree repeats the shape of a subtree in another file: a new form was started by copying the neighbouring one, and a change now goes into both [details](#a-yaml-duplicate-subtree) |
| `project/identifier` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Project name or vendor is not an identifier [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/presentation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Project presentation is empty [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/version` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Project version is not A.B.C [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `structure/xbsl-pair` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Module .xbsl without a paired .yaml |
| `project/path-matches-descriptor` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The `{{vendor}}/{{name}}` path diverged from the descriptor – a build refuses the project before compiling [docs](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `yaml/unknown-component-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A markup key the component does not declare while another component of the ui schema does: the apply rejects the node as an unknown property [details](#a-yaml-unknown-component-property) [docs](https://1cmycloud.com/docs/help/topics/system-and-interface-components/) |
| `yaml/inline-command-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A `Name` on a command declared inline in the markup: the apply refuses the node and rolls the project back [details](#a-yaml-inline-command-name) [docs](https://1cmycloud.com/docs/help/topics/command-interface-fragment/) |
| `yaml/list-scroll-without-loading` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A vertically scrolled list with `Navigation: None`: the rows come in a single portion, and the tail of the data is out of reach of the scrolling [details](#a-yaml-list-scroll-without-loading) [docs](https://1cmycloud.com/docs/help/topics/custom-list-component/) |
| `yaml/plain-comment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | file | A `#` comment in an element description: the visual editor writes the file out again from the model and keeps only a `##` documentation comment at the head of a documentable node (the element, a component, a declared property, a tabular section and the like). The fix respells a block that already stands in such a place and steps a block standing before the `-` of an item inside it; anything else is reported with the nearest node that holds a comment |
| `yaml/doc-comment-misplaced` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | file | A `##` block that stands where the environment does not read it - before the `-` of an item, above a single property, on a node without a documentation comment (a standard attribute such as `Code` or `Name`, a command, a dynamic list field). It is lost the same way a `#` comment is. A separate case is an instance of a project or a library component in a list: with a `##` block on such a node the server does not apply the project, and the rule names this reason |

#### Tier A rules in detail

<a id="a-yaml-duplicate-key"></a>**`yaml/duplicate-key`.** The schema checks read the already
merged document, so the lost value surfaces nowhere else. The second occurrence is flagged and
every one after it, with the line of the first. The `<<` merge key and non-scalar keys are left
alone, and keys are told apart the way the loader tells them apart: by tag and by text.

<a id="a-yaml-duplicate-import"></a>**`yaml/duplicate-import`.** The short and the full name of
the own project are one namespace, so a pair of them counts as a repeat too. The platform IDE does
not check the `Import` section. The fix removes the extra entry.

<a id="a-yaml-ref-needs-nullable"></a>**`yaml/ref-needs-nullable`.** Both a field of its own and a
type argument of a component are written this way: `Goods.Reference`, `Edit<Goods.Reference>`. The
compilation answers `Default value initialization is not supported`.

<a id="a-yaml-localization-key-unique"></a>**`yaml/localization-key-unique`.** `Strings` and
`Templates` share one namespace, and a translation file is judged alongside the dictionary. The
apply answers "Name is not unique" and rolls the project back.

<a id="a-yaml-unused-component"></a>**`yaml/unused-component`.** `code/unused-method` cannot see
such a component: its methods are called by its own yaml. A use is a yaml value or any word of a
module, and a name standing as a key of a localization dictionary does not count. A yaml file that
does not parse counts with all its words, and the translation dictionary does not count at all. An
entry point and `VisibilityScope: Global` are never judged: that is the public surface of a
library. Without a project descriptor among the linted files the rule stays silent, or a component
placed outside the linted subset would look dead.

<a id="a-yaml-duplicate-subtree"></a>**`yaml/duplicate-subtree`.** Names, ids and texts are left
out of the shape of a subtree. The 40-node threshold is measured: below it the rule catches
layout, not copies. A repeat inside one file, the data source of a list and a localized-strings
dictionary are never judged, and only maximal groups are named. Off by default: how much sameness
is too much is a decision of the project.

<a id="a-yaml-unknown-component-property"></a>**`yaml/unknown-component-property`.** An example:
`PlaceholderText` on a `Checkbox`, which is a property of `Edit`. A name no component declares is
left alone: the documentation does not list the yaml keys in full.

<a id="a-yaml-inline-command-name"></a>**`yaml/inline-command-name`.** Both an inline
command-interface fragment and a single-command property look like this. The apply answers: "a
command name is allowed only in command-interface-fragment project elements". Reach the command
through the handler parameter, and give it a name only by moving the fragment into a project
element of its own.

<a id="a-yaml-list-scroll-without-loading"></a>**`yaml/list-scroll-without-loading`.** `PageSize`
sets the portion and the scrolling moves through that portion alone: the list search still finds a
row the scrolling never shows. `Navigation: LoadingOnScroll` cures it. A list that promises no
scroll and an expression in `Navigation` are left alone.

### Tier B - text and conventions

Encoding, newlines, whitespace, typography (dashes, quotes, ellipsis, characters off the keyboard),
the wording of comments, the English of the translation dictionary, line length, secrets
in the sources.

Typography reads the resource files of the project as well - the `.css`, `.js`, `.svg` and
`.html` that lie under `Resources`. A subsystem ships them to the browser as they are, so the
prose in them reaches the reader the same way the prose of a module does. Judged there are
the comments of all four formats and the text a user reads on the screen: `<title>`, `<desc>`
and `<text>` of an SVG, the text nodes of an HTML page. Code is left alone - selectors,
identifiers, tag and attribute names, attribute values, the string literals of a script or a
stylesheet. The `comment/` group reads the comments of those files as well. The other rules of the
tier keep to the module and the element description; `translation/english-shape`,
`comment/first-person` and `comment/emphasis-caps` also read the files of the translation dictionary.

| Rule | | | Scope | What it checks |
|---|---|---|---|---|
| `security/hardcoded-secret` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A key or a password as a literal |
| `typography/em-dash` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | Em dash in a comment - of a module or of a resource file - and in the text of a page; the en dash is the one to write |
| `typography/ellipsis` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | The ellipsis character where three dots belong: a comment, and the text of an SVG or of an HTML page |
| `typography/curly-quotes` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Curly quotes wherever they turn up: a comment, a string literal of a module, the text of a page |
| `typography/guillemets-comment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | Guillemets in a comment, in a resource file too; in the text on the screen they are the right quotes and are left alone |
| `typography/yo-in-text` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | The letter "ё" in the text a user reads: a label, an entry of the dictionary of localized strings, the text of an SVG or of an HTML page |
| `typography/non-keyboard` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A character that is not on the keyboard in a comment: an arrow, a comparison or a multiplication sign; the fix writes `->`, `>=`, `<>`, `x` and the like, a currency sign is data and is left alone |
| `typography/en-dash-comment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | The en dash in a comment, for a project that writes a hyphen in its code comments; the fix writes the hyphen |
| `comment/doc-marker` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | file | A `//` block right above a declaration (a method, a structure, a field, an enumeration item, a module constant): the development environment reads a documentation comment by its `///` marker alone and puts only that text into the hover, the signature help and the completion. The fix respells the block; a `/* ... */` block in that place is reported without one A slash frame `////` in the attached block is also reported: only three slashes are removed by the documentation reader; no automatic choice between a header and documentation is made. |
| `comment/subjunctive` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | file | The subjunctive particle (would) in a comment; the finding asks for a word of condition, because dropping the particle turns a hypothesis into a statement. Concessive turns are left alone |
| `comment/first-person` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | file | The author speaking as "we" in a comment: a pronoun or a first-person plural verb, and "we", "our" or "I" in the English line of a comment kept by the translation dictionary; a comment is impersonal |
| `comment/emphasis-caps` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | file | A word in capitals for emphasis in a comment: "not", "only", a negation glued on. Emphasis is a matter of wording, not of case [details](#b-comment-emphasis-caps) |
| `comment/dash-condition` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | file | A condition in a comment written with a dash ("the store is not set - the main one is taken") instead of a word of condition [details](#b-comment-dash-condition) |
| `translation/english-shape` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A trace of a mechanical replacement in an English value of the translation dictionary: an ending glued onto a word that takes none (`onlies`) [details](#b-translation-english-shape) |
| `whitespace/trailing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Trailing whitespace |
| `whitespace/mixed-newline` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Mixed newlines |
| `encoding/utf8` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | File is not UTF-8 |
| `style/tab-indent` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Tab in the indentation [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/line-length` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Line longer than 120 characters [docs](https://1cmycloud.com/docs/help/topics/general-design/) |

#### Tier B rules in detail

<a id="b-comment-emphasis-caps"></a>**`comment/emphasis-caps`.** The rule judges a function word,
any other word the same file also writes in small letters, a one-letter word inside a sentence, a
negation glued on, and the capitals of the English line of a comment in the translation
dictionary. Abbreviations, date masks and a cited query are left alone. The fix restores the case.

<a id="b-comment-dash-condition"></a>**`comment/dash-condition`.** The finding suggests the
wording with a word of condition. The legend of a value is left alone: nothing is named there
before the state, or no verb follows the dash.

<a id="b-translation-english-shape"></a>**`translation/english-shape`.** The rule also catches a
passive followed straight by a noun phrase ("is shadowed the parameter") and capitals the Russian
key does not have. Only the `xbsl-translation` files are judged.

### Tier C - code structure, basic syntax and code-writing conventions

Block and bracket balance, loop and method headers, local variables and the `style/` group -
conventions from the documentation section "Code-writing recommendations". Every `style/` rule
is on by default, at `warning`.

| Rule | | | Scope | What it checks |
|---|---|---|---|---|
| `code/parse-error` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Syntax error (a full parse against the platform grammar) [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/statement-no-effect` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Expression statement other than a method call or `throw`: a build error even when the discarded expression contains a call |
| `code/return-mismatch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Return does not match the method signature (a value in a void method, a bare `return` in a typed one) - the compiler rejects such code [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/self-assignment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A value assigned back to where it is read from: `X = X`, `this.Field = this.Field`, `X -= X`. The compiler rejects it and the build rolls back [details](#c-code-self-assignment) |
| `code/assign-target` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The left side of an assignment cannot receive a value - a method call, a cast, `this` itself, or a chain through the safe access `?.` - the compiler rejects the assignment [docs](https://1cmycloud.com/docs/help/topics/assignment-statement/) |
| `code/assign-readonly` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | An assignment to a read-only name: a `val` or `use` local, a loop or `catch` variable, a module constant. The compiler rejects it [details](#c-code-assign-readonly) [docs](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/unreachable-statement` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Code the execution never reaches: after `return`, `throw`, `break` or `continue`. The compiler rejects it [details](#c-code-unreachable-statement) |
| `code/misplaced-jump` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | `break` or `continue` outside a loop, and `return`, `break` or `continue` inside a `finally` section - the compiler rejects the jump [docs](https://1cmycloud.com/docs/help/topics/exceptions/) |
| `code/call-arity` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A local call does not match its resolved signature: argument count, unknown or repeated named arguments, positional arguments after named ones, or a missing required parameter [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/brackets` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Unbalanced brackets () [] {} |
| `code/blocks` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Unbalanced blocks and ';' [docs](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/ternary-and-or` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A ternary right after `is Type` on the right of `and` or `or`: the ternary belongs to the type check, so the line compiles differently from how it reads [details](#c-code-ternary-and-or) [docs](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| `code/query-in-loop` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A query inside a loop |
| `code/param-type-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Parameter without a type and without a default value [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/duplicate-annotation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A duplicate annotation on a declaration, an exact argument-free repeat of the name: the compiler rejects such a module [details](#c-code-duplicate-annotation) [docs](https://1cmycloud.com/docs/help/topics/annotations/) |
| `code/duplicate-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A module imports a namespace a second time: the repeated line adds nothing [details](#c-code-duplicate-import) [docs](https://1cmycloud.com/docs/help/topics/import-statement/) |
| `code/module-var-not-const` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A `var` / `val` / `use` declaration at module level - only a constant lives there, an expression outside a method body is refused by the compiler and the apply rolls the project back [docs](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/param-redeclared` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A `val`, `var` or `use` in a method body with the name of the method's own parameter: a method is one scope with its parameters, and the apply rolls the project back [details](#c-code-param-redeclared) [docs](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `code/lambda-changes-outer-local` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A lambda body assigns to a local or a method parameter it captured: the compiler refuses the whole project [details](#c-code-lambda-changes-outer-local) [docs](https://1cmycloud.com/docs/help/topics/lambda-expression/) |
| `code/loop-header` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Malformed 'for' loop header [docs](https://1cmycloud.com/docs/help/topics/for-in-loop/) |
| `code/invalid-string-escape` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Invalid escape sequence in a string literal (`\'`, regex-style `\d`) - the compiler rejects such a literal; valid are `\н \в \т \\ \" \% \$ \ю<code>` and the Latin spellings [docs](https://1cmycloud.com/docs/help/topics/escape-sequence/) |
| `code/dead-interpolation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A doubled interpolation sign before a brace: the platform reads the pair as an escaped sign, and the expression is never evaluated [details](#c-code-dead-interpolation) [docs](https://1cmycloud.com/docs/help/topics/string-interpolation/) |
| `code/unused-local` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A `val`, `var` or `use` variable the method never reads or only assigns: the name takes up room and misleads a reader [details](#c-code-unused-local) |
| `code/unused-loop-var` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | The variable of a `for X in` loop that the body never reads; the counter of `for X = A to B` is not reported, as in the platform IDE |
| `code/ref-field-needs-req` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Structure reference field without 'req' [docs](https://1cmycloud.com/docs/help/topics/structure/) |
| `style/boolean-compare` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Comparing a boolean value with True/False [docs](https://1cmycloud.com/docs/help/topics/check-logical-values/) |
| `style/boolean-ternary` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A ternary with `True` and `False` branches: it equals its condition or the negation of it, and the platform IDE warns about it [details](#c-style-boolean-ternary) [docs](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
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
| `style/constructor-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A constructor of a type that has a literal, called with constant arguments only: the platform IDE warns about it [details](#c-style-constructor-literal) [docs](https://1cmycloud.com/docs/help/topics/literals/) |
| `style/redundant-tostring` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | An explicit `ToString()` call in a concatenation [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/interpolation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Concatenation instead of interpolation [docs](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/type-colon-space` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Spaces around the type colon [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/union-spaces` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Spaces around '\|' in a union type [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/nullable-shorthand` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Undefined in a type without the '?' shorthand [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/redundant-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Redundant type annotation on initialization [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/redundant-scope` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A `scope` that is the only statement of its block ends where the block ends and limits nothing [details](#c-style-redundant-scope) [docs](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `style/optional-params-last` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Optional parameter before a required one [docs](https://1cmycloud.com/docs/help/topics/method-declarations/) |
| `code/resource-bare-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | `Resource{Resources/<file>.svg}` - the key is a path relative to the Resources folder; spelling that folder out breaks the lookup [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| `query/named-parameter` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A named parameter `&Name` inside a query literal - the literal takes its values by interpolation (`%Name`) [docs](https://1cmycloud.com/docs/help/topics/query-literal/) |
| `code/this-in-static-method` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The keyword `this` inside the body of a static method - a static method is common to the whole type and has no object context, the compiler rejects the project [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/instance-call-from-static` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A bare call of an instance method of the same owner from a static method - the docs forbid it outright; call the method on a value or make it static [docs](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/close-in-before-close` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | `Close()` inside `BeforeClose` – the platform ignores the call and nothing closes the form afterwards |
| `query/no-isnull` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | `ISNULL(` inside a query literal – the query language has no such function |
| `style/abstract-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | An abstract variable name (`Data`, `Item`, `Value`) says nothing about the variable [details](#c-style-abstract-name) [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/single-letter-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A single-letter name of a variable, parameter or loop variable - per the names standard one-letter names belong only to short lambda parameters (`(A, B) -> A + B`) [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/negated-boolean-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A boolean variable named from the negation (`NotConnected`, `NoErrors`): the name comes from the affirmative [details](#c-style-negated-boolean-name) [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/type-in-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A variable name starting with a container type name (the Russian spellings of array, structure and map) - the type is visible from the declaration and the editor, keep it out of the name [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/numeral-in-const-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A spelled-out numeral in a constant name (`TIMEOUT_ONE_MINUTE`) describes the value - name the constant abstractly (`TIMEOUT`) so a value change does not break the name [docs](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `code/required-field-default` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A structure or exception field marked `req` also has a default value, which the compiler rejects. The fix removes the initializer only when an explicit type remains. |
| `code/declaration-needs-init` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A union-typed local or optional field without an empty alternative has no initializer; a module constant (`const`) or a `use` variable has no value. |
| `code/return-use-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A `return` hands out a `use` resource that closes when its scope ends, including casts, null coalescing and conditional expressions. |
| `code/duplicate-when` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A `when` branch of `case` repeats a literal, a local enumeration item or an explicitly named type handled earlier. |
| `code/duplicate-catch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | An exception type occurs more than once in the `catch` sections of one `try` statement. |
| `code/duplicate-declaration` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A name is declared twice where names are case insensitive, or an enumeration has more than one `default` item; exact method overloads and sibling local scopes remain legal. |
| `code/captured-local-write` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A mutable local or parameter of a named method is assigned after a lambda captured it: the lambda sees a value other than the one at capture [details](#c-code-captured-local-write) [docs](https://1cmycloud.com/docs/help/topics/lambda-expression/) |

#### Tier C rules in detail

<a id="c-code-self-assignment"></a>**`code/self-assignment`.** A compound form is judged only when
the file tells the operand type: a string joined with itself compiles. A plain one is removed by
the fix.

<a id="c-code-assign-readonly"></a>**`code/assign-readonly`.** The rule also judges a `val` field
of a structure, including one reached through a parameter or a local whose structure or exception
type is declared in the same file. For a local the fix turns `val` into `var`.

<a id="c-code-unreachable-statement"></a>**`code/unreachable-statement`.** An exit is also a call
of a `never` method of the file and a branching where every branch ends. A `case` over every item
of an enumeration of the file counts too.

<a id="c-code-ternary-and-or"></a>**`code/ternary-and-or`.** `A and X is String ? 1 : 0` reads as
`A and (X is String ? 1 : 0)` and does not compile unless both branches are boolean. The plain `A
and B ? 1 : 0` takes the whole condition and is not reported. The fix puts the condition in
parentheses.

<a id="c-code-duplicate-annotation"></a>**`code/duplicate-annotation`.** Annotations pile up until
the nearest declaration, and a comment between them does not separate them.

<a id="c-code-duplicate-import"></a>**`code/duplicate-import`.** The short and the full name of
the own project are one namespace, and the letter case tells names apart. The platform IDE warns
about every repeat after the first. The fix removes the repeated line.

<a id="c-code-param-redeclared"></a>**`code/param-redeclared`.** Nested blocks belong to the same
scope: a loop, a branch, a `try`. The compiler answers "a variable named X is already defined".
Loop and catch variables, lambda parameters and full-form lambda bodies are not judged.

<a id="c-code-lambda-changes-outer-local"></a>**`code/lambda-changes-outer-local`.** Judged are a
`var` variable or a parameter of the method or of an outer lambda, the operators `=`, `+=`, `-=`,
`*=` and `/=`, a short or a full lambda at any depth. A member or an element of the captured value
may change. A `val`, `use`, loop or catch variable is read-only and gets another compiler error.

<a id="c-code-dead-interpolation"></a>**`code/dead-interpolation`.** `%%{...}` and `$${...}` look
like this, and the value carries the text of the expression. Escape the first sign (`\%%{...}`) or
build the string by concatenation.

<a id="c-code-unused-local"></a>**`code/unused-local`.** Names are resolved by block scope, as in
the platform IDE. The fix drops the name of an unused `use` variable, and the resource is still
closed at the end of the scope.

<a id="c-style-boolean-ternary"></a>**`style/boolean-ternary`.** The rule judges a module, a
string interpolation and a yaml binding. The fix writes the condition or its negation the way the
platform binds `not`.

<a id="c-style-constructor-literal"></a>**`style/constructor-literal`.** An example: `new
Date("9999-12-31")`. `FindType` with a constant name is judged the same way. The fix writes the
literal where it holds the same value.

<a id="c-style-redundant-scope"></a>**`style/redundant-scope`.** The platform IDE warns about it.
The fix removes the scope and moves its body one indent left.

<a id="c-style-abstract-name"></a>**`style/abstract-name`.** An exact name is judged and so is a
name with a digit tail (`Data1`). The list: `Data`, `Item`, `Object`, `String`, `Value`,
`Document`, in either spelling. A stem inside a longer name (`ClientData`) and structure fields
are left alone: a structure field is a serialization contract.

<a id="c-style-negated-boolean-name"></a>**`style/negated-boolean-name`.** `Connected` and
`HasErrors` are the names to write. Judged only where the boolean type is proven: a type
annotation or a boolean literal initializer.


<a id="c-code-captured-local-write"></a>**`code/captured-local-write`.** A write before the
capture in a loop reusing the same binding is judged too. Earlier writes, a fresh local on each
iteration and mutation of members or elements stay allowed. There is no automatic rewrite.
### Tier D - semantics over stdlib, forms and the metamodel

Needs the project index and platform data: unknown types and objects, enumeration values,
the execution model (client/server), form handlers, properties and queries.

| Rule | | | Scope | What it checks |
|---|---|---|---|---|
| `yaml/choice-needs-static-list` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | ValueChoice without a static `ChoiceList` [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru/) |
| `yaml/slot-needs-list` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A slot the ui schema types as `Array<...>` holding a single component instead of a list: the apply refuses such markup, and the lint used to keep silent [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/Groups/Group_ru/) |
| `yaml/value-choice-title` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A `ValueChoice` with an explicit `SwitcherDisplayKind: Switcher` sets a `Title`: the platform does not draw it and the field stays unlabeled [details](#d-yaml-value-choice-title) |
| `code/unknown-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown type |
| `code/catch-non-exception` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The type in `catch` is not an exception (a stdlib non-exception or a local `structure`) - the compiler rejects such code [docs](https://1cmycloud.com/docs/help/topics/exceptions/) |
| `code/unknown-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A member access on a variable of a known stdlib type - plain or a generic, whose arguments type the members and do not name them - that the type does not have (first hop, typos get a hint) |
| `code/member-kind-mismatch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A stdlib method read as a property (or the other way round) [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/unknown-static-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A member reached through a type name that the type does not have (`DateTime.Minimal()`): such a call will not compile [details](#d-code-unknown-static-member) |
| `yaml/foreign-not-public` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A yaml reference to an element of another subsystem whose `VisibilityScope` is neither `InProject` nor `Global`: it is unreachable from outside its own subsystem, and no import helps [details](#d-yaml-foreign-not-public) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/foreign-not-public` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A module or a query names an element of another subsystem whose `VisibilityScope` is neither `InProject` nor `Global`: the compiler rejects the reference at that line [details](#d-code-foreign-not-public) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/call-arity-cross` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A module call does not match its resolved signature: argument count or named-argument binding; ambiguous overloads and shadowed module names remain unjudged [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/missing-return` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A typed method has a known path that reaches its end without `return`: along that path the method returns nothing [details](#d-code-missing-return) [docs](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/unused-return-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A standalone call discards the result of a platform method marked `CheckValueUsage`: the work of the method is thrown away [details](#d-code-unused-return-value) [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Annotations/Checks/CheckValueUsage_ru/) |
| `code/ambiguous-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A short type name in code refers to more than one visible project namespace [details](#d-code-ambiguous-type) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/ambiguous-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A short type name in YAML refers to multiple visible project namespaces. Root and package names have equal priority; qualify the type with its namespace [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/undefined-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | Undefined name in an expression (a typo in a name) and in a short string interpolation (`"?$format=json"` substitutes the name `format`, `\$` is needed) - the compiler rejects such code |
| `code/unknown-object-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown project-object type |
| `yaml/unknown-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown type in yaml |
| `yaml/dynlist-missing-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Missing dynamic-list field [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/dynlist-row-editing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | An `OnRowEdit` handler on a list over a flat dynamic source: the platform never calls it at all [details](#d-yaml-dynlist-row-editing) [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/Lists/List_ru/) |
| `yaml/dynlist-joined-table-param` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A parameter (`&Name`) or a binding (`=...`) in the arguments or the filter of a joined table of a dynamic list: it is never evaluated and the list fails at runtime [details](#d-yaml-dynlist-joined-table-param) [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/dynlist-filter-disabled` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A dynamic-list filter declared with `Use: False` while the paired module enables it by assignment: the first frame shows the whole table [details](#d-yaml-dynlist-filter-disabled) [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/list-form-needs-dynlist` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A form inherits `ListForm` while the table in its content comes from an `ArrayDataSource`: the navigation item silently disappears [details](#d-yaml-list-form-needs-dynlist) [docs](https://1cmycloud.com/docs/help/topics/list-form-component/) |
| `yaml/ref-input-auto-commands` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A reference `Edit` with no `Commands` of its own: the platform draws its own button next to it, opening the value in a separate window [details](#d-yaml-ref-input-auto-commands) [docs](https://1cmycloud.com/docs/help/topics/edit-component/) |
| `yaml/toggle-command-pair` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Two adjacent `UsualCommand` nodes with mirrored `Visible` (`=X` against `=not X`) emulate one command with two states, which the platform already has [details](#d-yaml-toggle-command-pair) [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/Commands/SwitchableCommand_ru/) |
| `yaml/dynlist-column-sort-lost` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A column of a table over a dynamic list whose value is a call: the platform sorts by the field of the source, so that header will not sort [details](#d-yaml-dynlist-column-sort-lost) [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/badge-column-image` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A `StandardTableColumn` with `Kind: Badge` also sets `Image`: the platform does not show the picture [details](#d-yaml-badge-column-image) [docs](https://1cmycloud.com/docs/help/topics/standard-table-column-component/) |
| `code/unknown-enum-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Unknown enumeration value [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/enum-needs-nullable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | An enumeration in a type position without `?`: it has no default value, so the server-side compilation fails [details](#d-yaml-enum-needs-nullable) [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/enum-default-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | The `DefaultValue` of an enumeration-typed field must be the bare name of a declared value: the type-prefixed spelling (`LabelVisibility.Invisible`) or an unknown name is rejected by the build [docs](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/unknown-enum-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A component property value outside the enumeration of the ui schema (`ContentVerticalAlign: End` - the vertical axis has `Top`, `Center`, `Bottom`, `Baseline` and no `End`) |
| `yaml/bare-object-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A bare word on a property that accepts `Object` - the platform expects a quoted literal, an `=` binding or a `$` localized-string reference [docs](https://1cmycloud.com/docs/help/topics/label-component/) |
| `code/unknown-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `Resource{...}` reference is unknown, hidden or ambiguous at the winning namespace priority [docs](https://1cmycloud.com/docs/help/topics/image-library/) |
| `form/unknown-handler` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Form handler not found in the module [docs](https://1cmycloud.com/docs/help/topics/form-component/) |
| `form/handler-signature` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Handler signature does not match the event [docs](https://1cmycloud.com/docs/help/topics/form-component/) |
| `code/unknown-form-component` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | Access to a component the form markup does not declare [docs](https://1cmycloud.com/docs/help/topics/form-component/) |
| `code/server-call-from-handler` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Server method is unavailable to a client handler [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/image-binding-server-call` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | ✓ | project | A platform component's `Image` property reaches the server directly or through client methods [details](#d-code-image-binding-server-call) [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/computed-property-server-call` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | project | Computed properties reach a client-available server method without the standard result cache [details](/linting#server-calls-in-computed-properties) [docs](https://1cmycloud.com/docs/help/topics/calculated-property-values-for-ui-components/) |
| `code/resource-read-without-cache` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | ✓ | project | A method available from the client runs on the server and only returns the text of a resource, read without the standard result cache [details](/linting#resource-text-read-without-the-result-cache) [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Annotations/Environments/AvailableFromClient_ru/) |
| `code/client-annotation-in-server-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | Client annotation in a server common module [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-module-in-http-service` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | Client common module in a server environment [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/server-annotation-in-client-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | Server annotation in a client common module [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/query-needs-server` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `Query{...}` block in a method of a client-side module with no `@OnServer`: the type does not exist on the client and the compiler rejects the build [details](#d-code-query-needs-server) [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
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
| `code/reserved-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A reserved name: the type keyword in either language as a structure field or a parameter. The server apply refuses all three spellings [details](#d-code-reserved-name) |
| `yaml/builtin-property-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | Built-in property name clash |
| `yaml/property-shadows-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A component property named after a common module: the name hides the module across the component, `Module.Method()` reads as a member of the property value, and the apply fails [details](#d-yaml-property-shadows-module) [docs](https://1cmycloud.com/docs/help/topics/addressing-module/) |
| `yaml/size-needs-no-stretch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A size without disabling the stretch [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/col-width-needs-no-stretch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A `Width` on a table column - a number or a binding - without `HorizontalStretch`: while the column stretches the number acts as a share of the free space rather than pixels [details](#d-yaml-col-width-needs-no-stretch) [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/matrix-group-max-width` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A numeric `MaxWidth` on a group that lays out as a matrix: a phone draws the page at desktop width and the content runs off the right edge [details](#d-yaml-matrix-group-max-width) [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/card-literal-stretch-weight` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A literal `StretchWeight` on a card or on a group inside one: in the mobile layout Safari collapses the card and Chrome shows nothing [details](#d-yaml-card-literal-stretch-weight) [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `code/unused-method` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A method declared in the project and used nowhere else – not by a call in code, a yaml binding or a name in a string. A comment is not a use [details](#d-code-unused-method) |
| `code/unused-constant` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A module constant referenced nowhere else in the project: the declaration is left with no work [details](#d-code-unused-constant) |
| `code/duplicate-method-body` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A method body of at least five lines repeated word for word in another file: the normalized body is compared, and a change goes into both copies [details](#d-code-duplicate-method-body) |
| `yaml/missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A yaml reference to a public element of another subsystem whose namespace the `Import` section does not list: the short name does not resolve [details](#d-yaml-missing-import) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/unused-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A module imports a subsystem or one of its packages, and the compiler never looks up a type in that namespace [details](#d-code-unused-import) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A module names a public element of another subsystem without an import line for its namespace: the project fails to compile at that line [details](#d-code-missing-import) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/wrong-namespace` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A qualified name of this project in a yaml value leads to a namespace where no element of that name lies: the compiler answers "Unknown type" [details](#d-yaml-wrong-namespace) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/wrong-namespace` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | The same in a module or a query: a name of this project leads to a namespace where its element does not lie, and the compiler answers "Unknown type" [details](#d-code-wrong-namespace) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/package-resources-missing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | `ResourcesPackage.Current()` in a module of a package or at the root of a subsystem that has no `Resources` folder of its own: no file is found, and that breaks only at run time [details](#d-code-package-resources-missing) [docs](https://1cmycloud.com/docs/help/topics/resource-in-project/) |
| `code/resource-replace-absent` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A replacement of a string that the text of its resource file does not have outside comments: the replacement changes nothing, the label was renamed in the file or the code [details](#d-code-resource-replace-absent) |
| `code/resource-label-unfilled` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A label of a resource file that the complete chain of replacements leaves in place: the page gets the label instead of a value [details](#d-code-resource-label-unfilled) |
| `yaml/missing-subsystem-usage` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Elements and modules of a subsystem import another subsystem while the description of their own does not list it under `Using`: the project fails to apply [details](#d-yaml-missing-subsystem-usage) [docs](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/computed-binding-assigned` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Every instance of a component binds a property with a computed expression while the component assigns that property in its own module: the platform crashes on the assignment [details](#d-yaml-computed-binding-assigned) |
| `yaml/localization-missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | An unqualified `$Dictionary.Key` whose dictionary lies in a namespace this yaml does not import: the apply refuses the node [details](#d-yaml-localization-missing-import) [docs](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `yaml/presentation-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The presentation field of an object [docs](https://1cmycloud.com/docs/help/topics/element-view/) |
| `yaml/unexpected-type-argument` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A type argument on a property the ui schema declares without one: that is another type, and the build apply rejects it [details](#d-yaml-unexpected-type-argument) [docs](https://1cmycloud.com/docs/help/topics/command-interface/) |
| `yaml/property-since-compat` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A component property newer than the project's `CompatibilityMode` (the ui schema records the version it appeared in) - apply rejects it as an unknown property [docs](https://1cmycloud.com/docs/help/topics/update-server/) |
| `query/deletion-mark-immediate` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A deletion-mark condition in a query on an object whose `DeletionMode` is `Immediately` - such an object has no mark and the query fails on apply [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `code/load-object-unwrap` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A force-unwrapped `LoadObject()` result on a reference from another record or a tabular-section row: the record may have been deleted physically, and the unwrap fails the whole pass [details](#d-code-load-object-unwrap) [docs](https://1cmycloud.com/docs/help/topics/data-deletion/) |
| `yaml/item-id-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A metadata collection item (an attribute, a tabular section, an enumeration item, an access-key parameter) without the `Id` its class declares - apply answers `ID required` |
| `code/unknown-row-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A field addressed on a dynamic list row (`DynamicListRow<Form.Type>`) that the list's `Fields` do not declare [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/row-field-null` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A row field that may be `Null` goes where the declared type refuses it: a dynamic list field taken through a reference (`Owner.Number`) into a typed structure field, or a `Query{...}` column read through a reference or from the joined side of an outer join into a structure field, a parameter, a variable or a method result (a `?` type refuses it too). The compiler answers `Null cannot be assigned` [docs](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/unknown-attribute-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A key an attribute's own metamodel class does not declare (`Length` on a regular attribute - the built-in `Code` declares it, a Number attribute has `IntegerPartLength`) - apply rejects the object |
| `yaml/empty-group-sized` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | An empty `Group` with `Height`/`Width` (a literal – always; an `=...` binding – only without a `Name`) – the renderer drops the node and there is no gap |
| `yaml/insert-row-needs-align` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A horizontal group with no `ContentVerticalAlign` lines its children up on the baseline, and an `HtmlContainer` insert, a button and a picture break that line [details](#d-yaml-insert-row-needs-align) [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/component-row-needs-align` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | The same button and picture, when a project component draws a neighbour: the two stand at different heights [details](#d-yaml-component-row-needs-align) [docs](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/hint-too-long` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A `Tooltip` longer than the render limit – the tail is not shown at all |
| `yaml/popup-in-markup` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A `PopupComponent` placed in the yaml markup: the content is drawn right in the form flow before the window ever opens [details](#d-yaml-popup-in-markup) [docs](https://1cmycloud.com/docs/help/topics/popup-component/) |
| `yaml/date-input-needs-plain-date` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | `Edit<Date?>` – the renderer silently drops a date input that allows the empty value; make the type plain and express "not set" with the empty date [docs](https://1cmycloud.com/docs/help/topics/edit-component/) |
| `yaml/binding-needs-auto` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A binding of a plain component property calls a method declared nullable - the client registers an "unexpected Undefined value" error on every recomputation; "not set" is the Auto value |
| `yaml/double-quoted-binding` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A binding of a nonstring component property in double quotes - the server rejects a quoted value there; a bare value or single quotes compile |
| `code/client-available-needs-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | `@AvailableFromClient` on a method of an interface component module that is neither static nor `@Contextual` – the component type is not a singleton, so the apply rejects the modifier [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-available-unused` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A method declared `@AvailableFromClient` with no client place in the project naming it: the annotation opens a surface to the client that nobody uses [details](#d-code-client-available-unused) [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/server-module-in-client-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `Module.Member(...)` access to a common module with `Environment: Server` from a method that runs on the client: the type does not exist on the client [details](#d-code-server-module-in-client-context) [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/component-in-server-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `Component.Member(...)` access to an interface component from code compiled for the server: the component's type lives on the client [details](#d-code-component-in-server-context) [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `yaml/delete-current-needs-immediate` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | `OnReferencedObjectDeletion: DeleteCurrent` on an attribute of an element that only marks a deletion: the compilation rejects that pair [details](#d-yaml-delete-current-needs-immediate) [docs](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `code/access-context-read-noop` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Extending the access context with the read privilege for a type whose yaml says `Read: PermitEveryone`: there is nothing to grant, and the call only looks like a guard [details](#d-code-access-context-read-noop) [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/per-object-permissions-need-common` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | An object calculates its permissions per object, but its module declares no `ComputeAccessPermissions` handler – the common calculation is required even then, if only to return an empty array [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-field-not-declared` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Inside `ComputeAccessPermissionsForObjects` a field outside `ComputePermissionsBy` is read, or a declared field is reached through `Entity` instead of the record [docs](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-handlers-need-recalc` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A module declares a permission handler while nothing calls `RecomputeAccessPermissions` for that entity: the platform never calls the handler, so a permission edit silently does nothing [details](#d-code-permission-handlers-need-recalc) [docs](https://1cmycloud.com/docs/help/topics/recalculate-access-permissions-and-keys/) |
| `code/access-key-handler-flavour` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A computed access key requires the `CheckHasAccessKeys` handler in its manager module; a key with `ManualGrant: True` cannot declare it [docs](https://1cmycloud.com/docs/help/topics/manage-access-control/) |
| `code/permission-right-not-computable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `ComputeAccessPermissions` handler grants a permission the entity's yaml does not declare computable: the build applies, and the permission recomputation fails at runtime [details](#d-code-permission-right-not-computable) [docs](https://1cmycloud.com/docs/help/topics/manage-access-control/) |
| `yaml/placeholder-key-in-strings` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A key carrying the placeholder `$0` in the `Strings` section of a `LocalizedStrings` dictionary: the section compiles to a method without parameters [details](#d-yaml-placeholder-key-in-strings) [docs](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `yaml/localization-ref-to-template` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A `$Dictionary.Key` reference pointing at a key of the `Templates` section: a reference resolves against `Strings` alone, and the apply fails [details](#d-yaml-localization-ref-to-template) [docs](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `code/compare-with-localized` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A localized value (`Dictionary.Key()`, `Presentation()`) compared against a literal or against a second localized value – in another language the branch simply never runs [docs](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `code/url-params-partial-encoding` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | file | A call of the Url method `WithRequestParameters`: it encodes a parameter value only partially, and a value that is itself an address arrives cut at its first "&" [details](#d-code-url-params-partial-encoding) [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Http/Url_ru/) |
| `code/url-data-scheme` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A `data:` address passed as a literal to the Url constructor: the constructor parses it as a path, and a picture fed the result draws nothing [details](#d-code-url-data-scheme) [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Http/Url_ru/) |
| `code/bound-property-assign` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A property computed by an expression in the paired markup is assigned from code: the platform refuses such an assignment [details](#d-code-bound-property-assign) |
| `yaml/event-needs-importance` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | An `EventLogEvent` description that does not set `Importance`: its default demands the value in every constructor, and one omission fails the apply [details](#d-yaml-event-needs-importance) [docs](https://1cmycloud.com/docs/help/topics/event-properties/) |
| `yaml/event-property-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | An `EventLogEvent` property type outside the platform's closed list: the refusal comes only from the server-side compilation and costs the deploy [details](#d-yaml-event-property-type) [docs](https://1cmycloud.com/docs/help/topics/event-properties/) |
| `code/collection-field-needs-req` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | A structure field has a known platform type without a default value and no `req`, nullable marker or initializer [details](#d-code-collection-field-needs-req) [docs](https://1cmycloud.com/docs/help/topics/structure/) |
| `code/var-needs-init` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A variable declared by type alone where the type has no constructor and no default value (`var Response: HttpResponse`) [details](#d-code-var-needs-init) [docs](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/unknown-tabular-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A member access on a tabular section's row collection that the array type does not have: the collection is `Array<Entity.Section>` [details](#d-code-unknown-tabular-member) |
| `code/global-unavailable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A call of a global name outside its environment: `Message` in a server module, the dynamic evaluation globals in a client method without `@OnServer` [details](#d-code-global-unavailable) [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/type-unavailable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A standard type used where its documentation says it does not exist: a server-only type such as `Encodings` in a client method, and the reverse [docs](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `style/shadow-project-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A variable, parameter or method named like a project element: the declaration shadows the element for that scope [details](#d-style-shadow-project-name) [docs](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `style/shadow-own-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A `val`, `var` or `use` variable named like a property of the object its method works on: the name resolves to the variable, so neither a read nor an assignment reaches the property [details](#d-style-shadow-own-property) [docs](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `style/redundant-union-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A member of a union type that another member already covers: a repeat, a second empty value, or a member under a wider neighbour [details](#d-style-redundant-union-member) [docs](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `code/unclosed-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A closeable resource abandoned by an early exit from the loop over it: a `return` or a `break` in the middle leaves it open [details](#d-code-unclosed-resource) [docs](https://1cmycloud.com/docs/help/topics/closeable-type/) |
| `code/use-needs-closeable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | file | The `use` modifier over a type the catalog describes and that does not inherit `Closeable` - the modifier exists for the automatic `Close()`, and the compiler refuses the declaration [docs](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `conventions/untranslated-visible-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | Visible text left as a Cyrillic literal where the project already references the same property into a localization dictionary [details](#d-conventions-untranslated-visible-literal) |
| `conventions/untranslated-code-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | Visible text left as a Cyrillic literal in a module: judged by the sink it reaches [details](#d-conventions-untranslated-code-literal) |
| `conventions/missing-translation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | project | A project token or a Cyrillic comment line the project's translation dictionary does not cover yet [details](#d-conventions-missing-translation) |
| `code/procedure-as-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A resolved procedure call is used as a value [details](#d-code-procedure-as-value) |
| `code/contract-parameter-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | An implementation parameter name differs from its project contract [details](#d-code-contract-parameter-name) |
| `conventions/platform-translation-shadow` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A project declaration blocks a platform translation without an explicit dictionary pair [details](#d-conventions-platform-translation-shadow) |
| `code/unknown-structure-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | project | A field access on a structure declared in the project is checked against its declaration: a renamed field turns red at its reader rather than on the server apply [details](#d-code-unknown-structure-field) |
| `code/redundant-skip-undefined` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | `SkipUndefined()` on a collection whose known element type is not nullable [details](#d-code-redundant-skip-undefined) [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Iterable_ru/) |
| `code/redundant-cast` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A cast to a type the operand already has: the platform IDE warns about such a cast [details](#d-code-redundant-cast) [docs](https://1cmycloud.com/docs/help/topics/as/) |
| `code/cast-to-non-null` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A cast that only drops `Undefined`: the operand is `T?` and the cast names `T`, where the platform IDE advises the non-null operator [details](#d-code-cast-to-non-null) [docs](https://1cmycloud.com/docs/help/topics/exclamation-mark-operation/) |
| `code/redundant-undefined-guard` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | file | A `??`, `!` or `?.` over a value whose type has no `Undefined`: the guard checks nothing and the default is never used [details](#d-code-redundant-undefined-guard) [docs](https://1cmycloud.com/docs/help/topics/undefined-type/) |
| `code/redundant-type-check` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A check `X is Type` whose result the type of `X` decides: the check always passes and `is not` never does [details](#d-code-redundant-type-check) [docs](https://1cmycloud.com/docs/help/topics/is/) |
| `comment/unknown-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | project | A name in a comment that neither the project nor the platform has: a renamed method, a replaced object, a typo [details](#d-comment-unknown-name) |
| `code/deprecated-api` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A call that binds only to a deprecated form of a platform method, as the platform IDE warns [details](#d-code-deprecated-api) [docs](https://1cmycloud.com/docs/help/topics/update-app-data/) |
| `code/deprecated-project` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | project | A use bound to a project method, property, constructor, parameter or enumeration value marked deprecated, as the platform IDE warns [docs](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Annotations/Compatibility/Deprecated_ru/) |

#### Tier D rules in detail

<a id="d-yaml-value-choice-title"></a>**`yaml/value-choice-title`.** Put the caption into a
separate `Label` next to the switcher. A node without an explicit kind and a node with an
`Array<...>` type argument, that is a checkbox group, are left alone.

<a id="d-code-unknown-static-member"></a>**`code/unknown-static-member`.** The type of such a call
carries on to the next hop of the chain. A bare name is read as a type only when the project gives
it no other meaning. The module's paired yaml counts even in a single-file check.

<a id="d-yaml-foreign-not-public"></a>**`yaml/foreign-not-public`.** A reference is a type
position, a `FormType` navigation target, the root of a binding chain `=Module.Method()`, a table
of a list (of a dynamic list or of the reference input settings of a field) and a qualified
`Subsystem[::Package]::Element` name. The qualified form resolves by the subsystem or the package
it names.

<a id="d-code-foreign-not-public"></a>**`code/foreign-not-public`.** Judged are a written type
position, the root of a `Module.Method()` chain and a table of a query: a `Query{...}` block or
the `.xbql` of a virtual table. The qualified `Subsystem[::Package]::Element` form belongs here
too. Neither an import nor an `@InProject` annotation on the method helps. The project module
belongs to no subsystem, so every non-public element is foreign to it.

<a id="d-code-missing-return"></a>**`code/missing-return`.** A complete `case` over an enumeration
and a call of a `never` method count, while a loop guarantees no return. A project-scope check
reads enumerations and signatures, and unresolved cases are left unjudged.

<a id="d-code-unused-return-value"></a>**`code/unused-return-value`.** The receiver type tells an
immutable operation from a mutable namesake, and a short expression lambda is not a statement.
Freshly extracted metadata is needed. There is no automatic rewrite.

<a id="d-code-ambiguous-type"></a>**`code/ambiguous-type`.** The subsystem root has no priority
over its packages, so the namespace is written out. Explicit qualifiers and file-local type
declarations are respected.

<a id="d-yaml-dynlist-row-editing"></a>**`yaml/dynlist-row-editing`.** The event is declared for
the node rows of a hierarchy. On a flat list a click opens the object's automatic form, so give
the object an object form of its own.

<a id="d-yaml-dynlist-joined-table-param"></a>**`yaml/dynlist-joined-table-param`.** On the main
table the same entry is legal, and on a joined one the compiler stays silent about it. Keep a
literal in the yaml and assign the live value from code: `Source.JoinedTables[i].Arguments`.

<a id="d-yaml-dynlist-filter-disabled"></a>**`yaml/dynlist-filter-disabled`.** That is the
first-render race: the platform draws the list without waiting for the code. Declare the filter
enabled, with an empty value.

<a id="d-yaml-list-form-needs-dynlist"></a>**`yaml/list-form-needs-dynlist`.** The list-form
skeleton is built around a dynamic-list table, and the content holds not a single type with
`DynamicList`. Give the table a dynamic list, or inherit a plain form (`Type: Form`).

<a id="d-yaml-ref-input-auto-commands"></a>**`yaml/ref-input-auto-commands`.** For a reference
input `Auto` unfolds into a command-interface fragment. The button is usually wanted, so the rule
is informational and off, and an empty fragment silences it.

<a id="d-yaml-toggle-command-pair"></a>**`yaml/toggle-command-pair`.** A `SwitchableCommand`
carries the representations and images of both states, the initial `Active` is a literal, and the
platform owns the state. A shared handler strengthens the case but is not required.

<a id="d-yaml-dynlist-column-sort-lost"></a>**`yaml/dynlist-column-sort-lost`.** Bind the column
to the field, or add a presentation field to the list itself. A column with `DisableSorting: True`
is not judged: it has no sorting by declaration. Off by default, because whether that column was
meant to sort is not visible from the file.

<a id="d-yaml-badge-column-image"></a>**`yaml/badge-column-image`.** The value is drawn as tag
pills, and the picture is documented only for `Kind: Picture`. Drop `Kind` and the picture stands
next to the value text, or set `Kind: Picture`.

<a id="d-yaml-enum-needs-nullable"></a>**`yaml/enum-needs-nullable`.** Both spellings are judged:
the input field is recognized as `Edit<...>`, the platform's own English. `InputField` is no
spelling of it and falls to `yaml/unknown-type`.

<a id="d-code-image-binding-server-call"></a>**`code/image-binding-server-call`.** Methods with
enabled or unknown caching and client variants are excluded. Pass the image with the data, or take
it from client data already loaded.

<a id="d-code-query-needs-server"></a>**`code/query-needs-server`.** A client-side module is a
form module and a common module whose `Environment` involves the client.

<a id="d-code-reserved-name"></a>**`code/reserved-name`.** The rule judges a structure field and a
method parameter. The capitalized spelling is confirmed by a live apply on the server.

<a id="d-yaml-property-shadows-module"></a>**`yaml/property-shadows-module`.** The apply answers
with an unknown-method error and the stand rolls back. There is one cure: rename the property.
There is no autofix, because the name is written in the markup, in the paired module and outside
the component as well. Only a common module is judged, and only one reachable by the bare name:
the component's own subsystem, its root and its packages, or a namespace its yaml imports.
`Subsystem` brings the modules at the root of that subsystem, `Subsystem::Package` those of the
package. A namesake catalog or component is a live idiom.

<a id="d-yaml-col-width-needs-no-stretch"></a>**`yaml/col-width-needs-no-stretch`.** All three
column kinds are judged, and a width given by a binding too: it yields a number at run time. The
column comes out wider than asked and the content drifts away from its neighbour. A pixel width needs `HorizontalStretch: False`, and a share with a guaranteed
minimum needs `MinWidth`. Off by default: width-as-a-share is a legitimate technique, statically
indistinguishable from the trap.

<a id="d-yaml-matrix-group-max-width"></a>**`yaml/matrix-group-max-width`.** The maximum doubles
as the available width, so the automatic columns are laid out by it rather than by the window. The
answer is `Auto`. Off by default: a desktop-only page lives with a maximum fine.

<a id="d-yaml-card-literal-stretch-weight"></a>**`yaml/card-literal-stretch-weight`.** The weight
is a flex with a zero basis, and in a vertical column, that is in the mobile layout, the basis
applies to the height. Safari clips the card with the rounding. On a phone drop the weight through
a binding. Off by default: a card living only in a wide row keeps it legitimately.

<a id="d-code-unused-method"></a>**`code/unused-method`.** A name inside a string literal counts as a
use: an HTML insert calls the method by name, and such a call is invisible to static reading. A comment
counts nowhere – not in the module that declares the method, not in the yaml paired with it, not in any
other element; when a comment is the only place the name turns up, the finding says so. Never judged: the
platform's own events, an object module, a module paired with an HTTP service, and a method whose
annotation names a caller outside the project code (`@Handler`, `@Subscription`, `@Implementation` and the
rest) – that annotation is the answer for a method the platform or a contract calls itself. For a call that
stays invisible anyway – a name assembled at run time, a client entry point kept on purpose – freeze the
finding in the baseline with its reason (`--write-baseline`, then `--baseline`). Off by default: over a
subset of the files a method used outside it would look dead.

<a id="d-code-unused-constant"></a>**`code/unused-constant`.** Words in code, yaml, strings and
comments count as uses, and the translation dictionary does not. Global constants and constants
with unknown annotations are skipped. Enable the rule for a whole-project check.

<a id="d-code-duplicate-method-body"></a>**`code/duplicate-method-body`.** Normalization drops
comments, blank lines and indentation. A platform hook is told apart by its `@Handler` annotation
rather than by a list of names: the same hook body in every object is normal. Copies inside one
file are not judged. Off by default: whether two copies should become one method is a design
decision.

<a id="d-yaml-missing-import"></a>**`yaml/missing-import`.** A reference is a type position, a
`FormType` navigation target and the root of a binding chain `=ForeignModule.Method()`. What is
needed is `Subsystem` for an element at the subsystem root and `Subsystem::Package` for one in a
package: importing the subsystem does not bring its packages. An import in the paired module does
not cover the markup. A binding root is judged after subtracting everything that explains the name
on its own: the declarations of this yaml, of the paired module and the implicit platform names.
The tables of the paired query of a virtual table resolve against the same section and are
reported on it: the `.xbql` and every item of its `FROM` lists, the one after a join condition
included. Qualified and temporary tables are not judged. So do the tables of a dynamic list, that
is the `Table` of its `MainTable` and of each of its `JoinedTables`, and the `JoinedTables` of the
reference input settings of a field; the finding sits at the value of the table, and a qualified
table needs no import.

<a id="d-code-unused-import"></a>**`code/unused-import`.** The platform IDE reports such imports.
What counts is what the compiler resolves: a written type; a name that is neither a local nor
declared by the module or the paired yaml; the root of a chain `Root.member`, even when the root
is a property of the paired yaml; a qualified name; a table of a query; an enumeration value in a
`when` branch; a bare `Resource{...}` key whose file only that namespace holds. The types that
values bring along count as well: the properties of the paired yaml the code names, the results
and fields of other elements reached through a chain, the fields of those structures, and a query
column that passes a field on. The import line itself, a member after a dot and a local named like
an element are not uses, so `import Subsystem` next to `import Subsystem::Package` is reported
when the module reaches only the package. A reference from the paired yaml is not a use either,
since the yaml has an import section of its own. An import of the module's own namespace is judged
the same way. The fix removes the line.

<a id="d-code-missing-import"></a>**`code/missing-import`.** What is needed is `import Subsystem`
for an element at the subsystem root and `import Subsystem::Package` for one in a package:
importing the subsystem does not bring its packages. Judged are the written type positions (a
parameter, a variable, a return, `new`, `as`, `is`, a `Type<...>` literal, generic arguments), the
root of a `Module.Method()` chain and the tables of the `Query{...}` blocks, every item of a
`FROM` list included. For a root everything that explains the name on its own is subtracted first:
the declarations of the method and the module, the implicit names of the platform and the sections
of the paired yaml. The project module belongs to no subsystem and needs the import for every
element it names, at the root of a subsystem as in a package.

<a id="d-yaml-wrong-namespace"></a>**`yaml/wrong-namespace`.** Judged are the full
`Vendor::Project::Subsystem[::Package]::Name` and the partial `Subsystem[::Package]::Name`, while
the project declares the element elsewhere. The usual cause is a move of the element between the
root of a subsystem and a package: a generated list form keeps its row type spelled by the old
place. Every string value of an element and of a descriptor is read, the namespace lists
(`Import`, `Using`) and resource references aside. A name of another project, a type declared in a
module and a chain that spells a namespace whole are not judged. A partial name is judged when its
first segment is a subsystem of the project that no declared library names as well. When the
element lies in one place, the finding carries the fix: the namespace is replaced by the placement
of the element. An element in several places is reported with its places and no fix.

<a id="d-code-wrong-namespace"></a>**`code/wrong-namespace`.** The name comes full or partial, and
it may stand in a type position, in a call or as a table of a query. For a table the compiler
answers that the table is not found. The import line and the key of a `Resource{...}` literal are
not read. The fix replaces the namespace when the element lies in one place.

<a id="d-code-resource-replace-absent"></a>**`code/resource-replace-absent`.** It looks
like `Resource{card.css}.OpenReadableStream().ReadAsString().Replace("{{SIZE}}", Size)` when the
file has no `{{SIZE}}`. The rule follows the text of one resource file through the chain of
`Replace` calls: across locals, wrappers over the read (by a path, a path inside a folder or a
parameter of type `Resource`), text helpers, and maps filled from a literal list of paths, client
parameters included. Each step is applied to the file with its comments blanked. The message says
when the string is only in a comment of the file, or when an earlier step of the chain has
already replaced it. A helper that serves several files is not blamed for one of them. A computed
path or search string and a choice between two files are not judged.

<a id="d-code-resource-label-unfilled"></a>**`code/resource-label-unfilled`.** A label is a word
between the delimiters the chain uses for its own strings: `{{A}}` and `{{B}}` give `{{NAME}}`. The
label is judged when the chain is complete, that is when nothing replaces further in a caller, in
a callee or through a variable. A part of the file (`Substring`, a wrapper that keeps the inner
part) and a value that another branch fills from elsewhere are not judged. The finding sits where
the text leaves the chain. When the same chain also replaces a string the file lacks, both
messages say it: that is what a renamed label looks like.

<a id="d-code-package-resources-missing"></a>**`code/package-resources-missing`.** The method
returns the resources of its own namespace alone, so for a package not even the files of its
subsystem are found, and for the root not the files of its packages. The answer is one:
`ResourceNotFoundException`, `GetAll()` included. In a package a `Resource{...}` literal does find
the files of the subsystem. The folder is looked up on disk, and the project module is not judged.

<a id="d-yaml-missing-subsystem-usage"></a>**`yaml/missing-subsystem-usage`.**
`Subsystem::Package` counts as an import of that subsystem, and all of it is learnt at deploy
time. An import gives the short names, but it is `Using` that permits the subsystem, its packages
included. A subsystem without a description has nowhere to declare the usage and is not judged.
The diagnostic sits on the subsystem description, where the fix goes.

<a id="d-yaml-computed-binding-assigned"></a>**`yaml/computed-binding-assigned`.** The platform
answers with an IllegalStateException. A named argument is not an assignment, and a code-built
instance, a bare-path binding, a literal or an unbound instance make the assignment legal: the
rule fires only when every instance is bound computed.

<a id="d-yaml-localization-missing-import"></a>**`yaml/localization-missing-import`.** What is
needed is `Subsystem` for a dictionary at the subsystem root and `Subsystem::Package` for one in a
package: importing the subsystem does not bring its packages. The apply refuses the node as a
not-imported namespace. A dictionary of the yaml's own subsystem, at its root or in a package,
needs no import, an import in the paired module does not cover the markup, and the qualified
`$Subsystem::Dictionary.Key` form needs no import.

<a id="d-yaml-unexpected-type-argument"></a>**`yaml/unexpected-type-argument`.** An example: a
form's `AdditionalCommands` takes `CommandInterfaceFragment`, not
`CommandInterfaceFragment<UsualCommand>`. An English tree is judged the same way: the key, the
component, the property and the type head are canonized, and the argument is compared with the
default name by name in either spelling.

<a id="d-code-load-object-unwrap"></a>**`code/load-object-unwrap`.** The shape looks like
`Row.Service!.LoadObject()!`. A physical deletion comes from `DeletionMode: Immediately` and from
the deleted-items form. Check the result for Undefined. The query row's own `.Reference` is not
judged.

<a id="d-yaml-insert-row-needs-align"></a>**`yaml/insert-row-needs-align`.** An `HtmlContainer`
insert carries a baseline of its own, so the element holding it slides down: 50 px on a live row.
The nearest horizontal ancestor answers, and a row whose inner strip is already aligned stays
silent. A `Button` keeps the baseline on its caption and a `Picture` on its bottom edge, so a
captioned button next to a picture sinks by 19 px. `ContentVerticalAlign: Center` cures it. A
layout binding counts in its statically horizontal branches. The pair is judged when one of the
two is shown unconditionally or both are shown under the same conditions. Two neighbours with
different conditions of their own, and a child that sets its own vertical alignment, are left
alone.

<a id="d-yaml-component-row-needs-align"></a>**`yaml/component-row-needs-align`.** The component
shows a native `Button` or `Picture` unconditionally, or picks between them by its own property:
the instance sets the property to a literal, and the condition compares it directly or through a
method that only returns that comparison. The button sank 19 px on a live row. Set
`ContentVerticalAlign: Center` on the row. Visibility is read as in `yaml/insert-row-needs-align`.
A component the rule cannot read statically takes no part, and a row the file rule judges alone is
left to `yaml/insert-row-needs-align`.

<a id="d-yaml-popup-in-markup"></a>**`yaml/popup-in-markup`.** A project component transitively
inheriting `PopupComponent` is judged the same way. The platform has no property restricting the
drawing to the window, and hiding it through `Visible` breaks the window itself. Build the window
in code on every opening: a new `PopupComponent(...)`, then `OpenInPopupWindow()`.

<a id="d-code-client-available-unused"></a>**`code/client-available-unused`.** A client place is a
module of the client environment, a client method of a server module, a yaml and a string literal.
Off by default, like `code/unused-method`: a client call is not always visible statically.

<a id="d-code-server-module-in-client-context"></a>**`code/server-module-in-client-context`.**
Such a place is an interface component, a command and a client common module.

<a id="d-code-component-in-server-context"></a>**`code/component-in-server-context`.** Server code
is an `@OnServer` method anywhere and an unannotated method of a server or client-and-server
module. The server compilation refuses with "Variable X is not defined".

<a id="d-yaml-delete-current-needs-immediate"></a>**`yaml/delete-current-needs-immediate`.**
Marking is `DeletionMode: DeletionMark`, which is also the default. Not every kind carries the
property: a register has none, and the rule leaves a register alone. The line `Action
DeleteCurrent cannot apply to object with a "DeletionMark"` comes from the compiler, not from
the documentation.

<a id="d-code-access-context-read-noop"></a>**`code/access-context-read-noop`.** Everyone may read
such a type already. With that privilege alone the whole line goes; among others, only it does.

<a id="d-code-permission-handlers-need-recalc"></a>**`code/permission-handlers-need-recalc`.** The
handlers are `ComputeAccessPermissions` and kin. A recompute with a non-entity receiver, the
documented loop form, stands the rule down. Kinds with no recompute method, that is rights
elements, are not judged.

<a id="d-code-permission-right-not-computable"></a>**`code/permission-right-not-computable`.**
`...ForObjects` is judged too. Computability is declared by `PermissionsComputed` and
`PermissionsComputedForEachObject`, explicitly or through `Default`. The recomputation answers
that the permission is not marked as computed. Permissions are collected only from `new
AccessPermission(...)` constructors in both namespaces, `Entity.Privilege.*` and
`HttpServicePrivilege.*`, transitively over project calls: delegation into a shared rights module
is followed, and the finding is bound to the entity. `AccessContext.Append` does not count,
under-granting is legal, and kinds without access control are not judged.

<a id="d-yaml-placeholder-key-in-strings"></a>**`yaml/placeholder-key-in-strings`.** A call with
an argument fails the apply with an "unknown method" answer.

<a id="d-yaml-localization-ref-to-template"></a>**`yaml/localization-ref-to-template`.** The apply
answers that the localized string was not found, and the stand rolls back. A template key nobody
references is left alone: code calls it legitimately.

<a id="d-code-url-params-partial-encoding"></a>**`code/url-params-partial-encoding`.** The "&" and
"=" inside the value stay separators. Build the string with the parameters object and glue it to
the base address. Off by default: whether a value can carry "&" is not statically visible.

<a id="d-code-url-data-scheme"></a>**`code/url-data-scheme`.** The constructor puts a slash
after the scheme and encodes ";" and "," as path characters, the browser refuses the address
with ERR_INVALID_URL, and the `Image` property takes no string. Serve the image from an HTTP
service of the project or as a resource. A data address kept in a variable is not traced.

<a id="d-code-bound-property-assign"></a>**`code/bound-property-assign`.** It looks like `Height:
=Common.IsNarrowScreen()?820:528`. Inside a try/catch the refusal is invisible. A data binding,
that is a bare path, is left alone: it is two-way by design.

<a id="d-yaml-event-needs-importance"></a>**`yaml/event-needs-importance`.** The default is
`FromConstructor`. One write that omits the value fails the apply on the constructor line. An
explicit `Importance: FromConstructor` states the choice and silences the rule.

<a id="d-yaml-event-property-type"></a>**`yaml/event-property-type`.** A project enumeration
cannot go there. The list is read from the metamodel (`EventLogEventProperty.Type`), and `?` and a
`Std::` qualification are tolerated. Variant values are written as string codes, with the allowed
codes listed in the property's `Description`.

<a id="d-code-collection-field-needs-req"></a>**`code/collection-field-needs-req`.**
`TextPosition` and `ReadableArray<String>` look like that. Scalar default values, unknown types
and locally shadowed platform names are left alone.

<a id="d-code-var-needs-init"></a>**`code/var-needs-init`.** The compilation answers that the type
has neither a constructor nor a default value. An enumeration, an annotation, a singleton and a
name shadowed by a project type are skipped.

<a id="d-code-unknown-tabular-member"></a>**`code/unknown-tabular-member`.** Judged are
`Object.Section.Member` in an object form module, the bare section name and `this.Section` in the
entity's modules. The other platform's habitual `Count()` is called `Size()` here. A module named
after the section shadows it, and attributes are not judged.

<a id="d-code-global-unavailable"></a>**`code/global-unavailable`.** The apply answers that the
method is unavailable in the current environment. `Message` is client-only and the dynamic
evaluation is server-only. `@OnClient` and `@OnServer` override the module's environment, and the
availability comes from the per-member availability lines of the global context packages.

<a id="d-style-shadow-project-name"></a>**`style/shadow-project-name`.** An example: a
`Warehouses` variable next to the `Warehouses` catalog. Platform handler parameter names never
collide with project names.

<a id="d-style-shadow-own-property"></a>**`style/shadow-own-property`.** The platform IDE warns
about such a variable. The properties are those of the method's owner. For a component they are
its declared properties and events, those of the platform type it inherits, and `Components`. In
the object module of a catalog, a document or a processing element they are the attributes,
tabular sections, reference, version stamp and deletion mark. For a record set it is the filter,
for a scheduled job the parameters and properties of the job, for a structure its fields. Static
methods, parameters, loop and catch variables are not judged, and a server method of a component
sees only the properties marked `Contextual`.

<a id="d-style-redundant-union-member"></a>**`style/redundant-union-member`.** `String|String`,
`String|Undefined|?` and `Array<String>|ReadableArray<String>` look like that, a member under
`Object` or under a base type of the catalog with the same arguments. The platform IDE warns about
it, and a function type is not judged. The fix writes the union without those members.
With freshly extracted generic metadata, a contract with a covariant parameter covers wider
arguments, a read-only one and a mutable one alike (`MutableArray<Object>` covers
`Array<String>`), and nested base formulas are substituted. The concrete `Array`, `Map`, `Set`
and `Collection` keep their parameters invariant; missing metadata keeps the previous
exact-argument behavior.

<a id="d-code-unclosed-resource"></a>**`code/unclosed-resource`.** It looks like `val Selection =
Query{...}.Execute()`. The platform closes a full pass by itself, and it logs an unclosed-resource
event. Declaring the variable with `use` closes the resource on every exit path. A resource that
arrived as a parameter, one the method closes by hand and one it returns to its caller are left to
the author.

<a id="d-conventions-untranslated-visible-literal"></a>**`conventions/untranslated-visible-literal`.**
The intent is counted per element kind, so a same-named property of another kind is not judged. On
a project whose descriptor lists fewer than two localization languages the rule stays silent.

<a id="d-conventions-untranslated-code-literal"></a>**`conventions/untranslated-code-literal`.** A
sink is an argument of the platform message call, a property of an event-log event, or either of
them one step away through a method that forwards its parameter. Markup, pure interpolation and
single words are skipped. On a project whose descriptor lists fewer than two localization
languages the rule stays silent.

<a id="d-conventions-missing-translation"></a>**`conventions/missing-translation`.** One finding
is reported, at the first occurrence in the file. The rule stays silent unless an
`xbsl-translation` dictionary lives next to the project or above it (see `xbsl translate`).

<a id="d-code-unknown-structure-field"></a>**`code/unknown-structure-field`.** The type comes from
the variable's declaration (`Module.Structure`, a bare name for the declaring module), from a
`new` constructor and from the element type of a `for X in List` loop. A name declared with
anything else in the method, a namesake of a stdlib type, the second hop of a chain and Latin
member spellings are not judged.

<a id="d-code-redundant-skip-undefined"></a>**`code/redundant-skip-undefined`.** For an iterable
the fix uses `ToArray()`, preserving the array materialization. A sequence receives a warning
without a fix.

<a id="d-code-redundant-cast"></a>**`code/redundant-cast`.** `Found!.Reference as Goods.Reference`
over a query that reads the reference of that very catalog looks like that, and so does a union of
references cast to the entity contract both of them implement. When the two types are the same,
the fix removes the cast together with the parentheses around a single operand. A cast to a wider
type is reported without a fix, since a declaration or an overload may need that type.

<a id="d-code-cast-to-non-null"></a>**`code/cast-to-non-null`.** Typically the operand is a
nullable attribute a query reads, the result of `Map.GetOrUndefined(...)` or the result of a
method declared `T?`. The fix puts `!` in place of the cast. The operand is typed by its
declarations, and a query column by the select list and the yaml of its table. A condition checked
before the cast narrows nothing, and an operand the inference cannot name is not judged.

<a id="d-code-redundant-undefined-guard"></a>**`code/redundant-undefined-guard`.** The platform
IDE warns about it. The type comes from a declaration, from a component of the paired markup such
as `Edit<Number>`, or from the argument of a generic type, as in `OnChangeEvent<String>.NewValue`.
The fix removes `!`, and removes `?? ...` when the default does not widen the type.

<a id="d-code-redundant-type-check"></a>**`code/redundant-type-check`.** Every type of the
expression is one of the checked types or assignable to one: a base the catalog states
(`Array<String>` fits `ReadableArray<String>`) and an entity contract a project element
implements. The platform IDE warns about such a check. A column of a query row is typed by the
SELECT list the way the cast rules read it: a field, a choice, arithmetic, a count. A field
through a reference or of a left-joined table may be `Null`, and `.ReplaceNull(...)` takes the
`Null` out.

<a id="d-comment-unknown-name"></a>**`comment/unknown-name`.** A case form of a known name,
commented-out code and a chain naming another system are left alone. So is a name with another
system named within two words of it: `1C:Enterprise`, `SSL`, `BTS` or their Russian names, or a
system the project declares with `--other-system`. The message says how to name the system
when it is not there.

<a id="d-code-deprecated-api"></a>**`code/deprecated-api`.** `ObjectStorage.UploadFromBytes(...)`
and `ObjectStorage.Upload(Stream, Size)` next to the current `Upload("file", Bytes)` look like
that. The overloads are picked by the compatibility mode of the project, the arguments and their
known types. The message names the replacement when the documentation does.

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
For a Russian name this is morphology rather than a guess by the ending, so a singular noun the
standard allows is told apart from a plural that reads as a genitive singular without the case.
This needs the `[morph]` extra (`pip install "xbsl[morph]"`); without it Russian names stay
silent. An English name in a translated tree is judged by its last word, with suffix heuristics
and the irregular plurals listed, and needs no extra. Mass nouns and ambiguous tails are left
undecided.

The rest: the letter yo and underscores in names, an abbreviation written in mixed case instead
of all caps, an English term transliterated rather than kept as the original (`Xml`, not its
Cyrillic spelling), an enumeration named with the word for type where the standard asks for the
word for kind, the element kind repeated inside its own name, filler words such as the ones for
management or manager, an environment suffix on a common module name (the environment is a
property, not a name), a boolean attribute named by a negation instead of the positive form, an
empty `Presentation`, and the prefixes required for certain kinds - access key, right and
navigation.

### Code style conventions (the `style/` rules)

Thirty-two rules that follow the platform documentation ("Code style conventions", "Language
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

Five rules of the group go past tokens: they read the parsed module and repeat warnings of the
platform IDE. `style/constructor-literal` reports a constructor that a literal of the type replaces,
`style/boolean-ternary` a ternary with `True` and `False` branches, `style/redundant-scope` a scope
that is the only statement of its block, and `style/redundant-union-member` a union member another one
covers. `style/shadow-own-property` also reads the paired yaml and the platform type catalog, so a
variable named like a property the component inherits, such as `Title` of a `Group`, is found as
surely as one named like a declared property.

All thirty-two rules are on by default, at `warning`: clean code already satisfies them, and
they guard against regressions. The flags that choose rules take the group as a whole:

```sh
xbsl path/to/sources --select style     # ONLY these rules (replaces the default set)
xbsl path/to/sources --enable style     # the default set PLUS these
xbsl path/to/sources --ignore style     # the default set minus these
```

`--select`, `--enable` and `--ignore` accept a rule id, a group (the part before `/`) or a tier
letter, repeated or comma-separated. `--select` narrows to exactly the given rules, while
`--enable` switches on off-by-default rules on top of the defaults.

`Query{ ... }` blocks, which are a DSL of their own, and string literals with HTML, CSS or SVG
for web views are excluded from these checks. Not covered, and left to the author and review:
indentation being a multiple of four, collection idioms, `Rows.Join()` for bulk concatenation, the
`?.` and `??` idioms, and `case` instead of an `else if` chain.

### Code semantics (the `code/` rules)

The largest group: ninety-eight rules, sixty of them errors. These cover what the compiler
rejects, and what the platform does differently from how the code reads. An unknown name or
member. The arity of a call. The environment, meaning client code in a server method and the other
way round. An instance reached through its type. A caught non-exception. An unclosed resource. A
walk over a collection while it is being changed. And the platform traps whose only sign is the
shape of the code. The group also repeats warnings of the platform IDE: an unused variable or
import, a redundant cast, a guard against `Undefined` or an `is` check whose outcome the types
already decide. Some of the rules are project-scoped, and `--stdin` does not run those: they need
the paired yaml and the names of the objects.

### Element descriptions (the `yaml/` rules)

Sixty-four rules over the descriptions (`.yaml`): required and unique ids, known keys and types,
references to components, handlers and localized strings, what the platform requires of field
types (a reference and an enumeration admit an empty value), the settings of dynamic lists and
forms, and the layout traps that apply without an error yet draw differently from the intent. Six
rules are `info` and off, because they say "this is how the platform works" rather than "this is a
mistake".

### Project conventions (the `conventions/` rules)

Rules about what the project agreed on rather than what the platform demands. The base set
carries the bilingual-project family. `conventions/untranslated-visible-literal`, on by default,
reports visible text left as a Cyrillic literal where the project already routes the same property
through the localization dictionary. `conventions/untranslated-code-literal` and
`conventions/missing-translation`, both off, extend that to module literals and to the translation
dictionary. Whether every human-readable string must come from the dictionary is a per-project
decision, so the base set does not impose it.

The group is also the extension point by design. A project plugin registers its own house rules
under `conventions/` - a ban on task numbers in comments, internal references and the like - and
decides their severity and defaults for that project; see
[Extending](/servers#extending-your-own-rules-data-and-severities). What actually runs is what
`xbsl --list-rules` prints; the table above lists the base set only.

### The small groups

- `typography/` - typographic characters in prose and comments: em dash, the ellipsis character,
  curly quotes, guillemets in comments, a character that is not on the keyboard (an arrow, a
  comparison sign) and, for a project that writes a hyphen in its code comments, the en dash of a
  comment; plus the letter "ё" in the text a user reads. The group reads the resource files of the
  project too (`.css`, `.js`, `.svg`, `.html`);
- `comment/` - the wording of a comment: the subjunctive particle, the first person, a function word
  in capitals for emphasis and a condition written with a dash; `comment/unknown-name` checks the
  names a comment mentions against the project. The group reads the comments of modules, element
  descriptions and resource files (the name rule reads modules and element descriptions), and the
  first person and the capitals of emphasis are read in the English lines of the translation
  dictionary too; the group is off
  by default; a project that keeps its comments impersonal turns it on with `--enable comment`;
- `translation/` - the English of the translation dictionary: `translation/english-shape` reads the
  values of the `xbsl-translation` files, whose text `xbsl translate --strict` never judges;
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

<a id="d-code-procedure-as-value"></a>**`code/procedure-as-value`.**

Checks local and cross-module project calls in value expressions. Unknown targets, ambiguous overloads and standalone procedure calls are left alone. No automatic fix is offered.

<a id="d-code-contract-parameter-name"></a>**`code/contract-parameter-name`.**

Compares parameter names only for an unambiguous project service contract and matching signatures. Reports an error in compatibility mode 8.0 or later, a warning in earlier modes, and skips an unknown compatibility mode. No automatic fix is offered.

<a id="d-conventions-platform-translation-shadow"></a>**`conventions/platform-translation-shadow`.**

Runs only in projects with a translation dictionary. Reports a Cyrillic declaration collected by the translator when it suppresses a known platform mapping and has no applicable explicit token pair. Local variables and parameters are excluded. Add a dictionary pair; renaming is optional and is never applied automatically. ASCII declarations are excluded by the translator's contract, so a fully translated English tree has no findings from this rule.
