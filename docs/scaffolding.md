---
title: "Metadata scaffolding"
description: "Creating objects, attributes, routes and forms through the engine instead of hand-writing yaml – and the code templates."
sidebar:
  label: Scaffolding
  order: 6
---

Writing yaml by hand means remembering a UUID, the property names of a kind and where a form is registered. The engine does that part; the same operations are available from the CLI, an editor and an agent.

## Metadata scaffolding

The toolkit takes over the metadata mechanics: UUIDs, indentation, precise yaml insertions,
duplicate checks and section/kind compatibility. The same operations are exposed through the
CLI (subcommands, JSON output), MCP (the `meta_*` tools for agents) and LSP (the `xbsl/meta*`
custom requests that power the VS Code metadata tree).

33 kinds of project element are creatable – from `Catalog` and `Document` to `VirtualTable`
(paired with its mandatory `.xbql` query), `ScheduledJob`, contracts, rights and
commands. Each kind carries what the docs make mandatory: the platform's own default scope
(`InSubsystem` – widen it deliberately with `--scope`), a module stub for the handler the
kind cannot live without, and a note for whatever the generator must not invent for you. Kinds
whose content is drawn in the designer (`ReportPanel`, `IntegrationProcess`) are
deliberately absent.

![The VS Code tree, AI agents and the terminal call the same scaffolding core; it writes created and point-edited yaml/xbsl files, the linter checks what was written, and the response carries files, notes and the lint report; the LSP surface returns full texts for the editor to apply](https://raw.githubusercontent.com/keyfire/xbsl/main/images/scaffolding.png)

```sh
xbsl new-project . vendor App                          # descriptor + module + a subsystem
xbsl new-object <subsystem-dir> <kind> <name>          # kind: Catalog, Document, Enum, ... (--help spells them)
xbsl add-field <object>.yaml <section> <field> --type <type>
xbsl add-form . --name <object>                        # object + list forms, registered
xbsl add-form . --name <object> --forms list-cards     # list form as a card grid
xbsl new-object <subsystem-dir> <http-service-kind> <name> --routes "GET /, POST /, GET /{id}"
xbsl add-route  <service>.yaml "DELETE /{id}"          # url template + handler stub
xbsl add-method <module>.xbsl <method> --annotations <annotation> --after <existing-method>
xbsl add-subsystem vendor/App <name>
xbsl add-dependency . acme CurrencyConverter 2.0       # attach a library to the project
xbsl rename-object . <old-name> <new-name>             # rename files + update references
xbsl delete-object . --name <object>                   # the plan; --apply deletes and lists leftovers
xbsl set-access . --name <object> --default <access-method>
xbsl object-info . --name <object>                     # fields, tabulars, forms, namespace
xbsl project-info .                                    # projects, subsystems, objects by kind
```

The kind, the section, the annotations, the access methods and every identifier reach the CLI in
the spelling the platform uses for the project's development language; the prose of this page
names them by their English equivalents (`Catalog`, `Attributes`, `OnServer`,
`PermitAuthenticated`), which is why the examples above use placeholders.
`xbsl new-object --help` lists the kinds a project can hold, spelled the way the command wants
them.

The sources themselves may be written in either language, and the scaffolding reads both: an
object whose file spells its kind and its sections in English - `ElementKind: Catalog`,
`Attributes:` - is found, described and edited exactly like one spelled the other way (see
`demo-en/`). What the tool writes follows the file it writes into: a new attribute of an English
object gets `Name:` and `Type:`, a missing section is created as `Attributes:`, a subsystem and a
library entry are spelled like the project around them. The pairs come from the platform data -
the metamodel's own English name of every property - so a name that the platform spells
differently depending on the class (the enumeration values section is `Items` there and
`Elements` elsewhere) keeps the original spelling in both reading and writing instead of being
guessed at. Values (types, access methods) are yours and are written as given.

Forms are generated with real content: input fields per attribute (including the standard
`Name` / `Number` / `Date` fields and hierarchy support), `DynamicList` columns, `TabularParts`
tables, a report form with parameters; the form is registered in the `Interface` section of its
owner. `--dry-run` prints the changes (with full file texts) without writing – this is how
the VS Code extension applies them through its own undo-friendly edits.

`--forms list-cards` builds the list form as a card grid instead of a table: a `CustomList`
whose `RowsContainer` is a `MatrixGroup`, plus a generated `ListRow<Name>` row component named
after the object. The card takes a `Title`, a photo (an attribute of type `BinaryObject.Reference`
switches the card to `CustomCard`, with the image above the caption) and up to three more
fields, dates formatted; notes report what landed on the card and what did not.
`--card-min-width` sets the grid column width (default 400, 250 with a photo) and
`--card-placeholder` the image shown when the photo is empty.

`add-dependency` attaches a library – it writes the `Libraries` section of the project descriptor
(`Name`, `Vendor`, `Version`). The version is the library's **release** version: a release is issued
in the control panel, and a build version with a suffix (`1.0-42`) is rejected. Different
versions of one library within a project are not allowed, so attaching an already attached
library updates the version of the existing entry. What is attached now – `project-info`
(`projects[].libraries`). The vendor, name, version and the qualified type names of a library
come from parsing its archive: `elemctl inspect <file.xlib>`.

`set-access` edits `AccessControl.Permissions` of an object in place, aware of what each kind
allows: `--default` sets the `Default` right, `--permission Read=PermitEveryone` an individual
one (custom rights of a `PrivilegeOnElement` included), `--calc-by` fills `ComputePermissionsBy` –
mandatory for `PermissionsComputedForEachObject`.
Wrong methods, rights a kind does not have, and per-object rights on a `ConstantsSet` are
rejected; the computed-permission handlers stay yours to write (notes say which). `object-info`
reports the current permissions and the kind's rights, `project-info` the `Default` of every
object – no section there means the platform falls back to `PermitAdmins`.

`rename-object` renames the object's files (including its forms and the generated `ListRow<Name>`
component of a card list) and rewrites references context-aware across the whole project: the
reference-bearing yaml keys (`Type` / `Table` / `DataSource` / `Form` / `FormType`), `=` bindings
and .xbsl code. Attributes, components or dynamic-list
fields that merely share the old name are left alone, and so are string literals (UI text);
`--new-presentation`/`--old-presentation` update the `Title` / `Presentation` of the
object and its forms. The object's `Id` is untouched, so the platform keeps the stored
data.

`delete-object` deletes an object whole: the yaml+module pair, its forms and the generated
`ListRow<Name>` row component (with their pairs). A subsystem is the folder the files live in,
so the membership goes away with them. Every remaining mention of the name across the project is
listed by file and line - string literals and comments included, because a router opening a form
by a name in a string or seeding data is exactly the leftover that otherwise surfaces as a
runtime error - and deliberately not edited: which mention is dead code is the author's call.
Deletion is irreversible, so without `--apply` the command prints the plan (the MCP tool
`meta_delete_object` defaults to `dry_run=true` the same way).

A rename that only changes letter case (`Goods` into `goods`) is applied in two steps through a
temporary name: a case-insensitive filesystem (Windows, macOS) addresses the old and the new name
as one file, and a single-step rename between them is not guaranteed. A failure of the second step
undoes the first and leaves no temporary name on disk; on a case-sensitive filesystem the name is
free and the rename runs in a single step. The tool renames the files itself, but check the
version control system: git on a case-insensitive filesystem folds ASCII letters only, so a Latin
rename goes unnoticed - record it explicitly (`git mv <old> <new>`) - while a Cyrillic one is
recorded as a delete plus an add, and then every other clone on such a filesystem stops at
"untracked working tree files would be overwritten by merge", where the file under the old name
has to be deleted before pulling.

## Code templates

A template is a short trigger plus a construct: type the first letters of `if`, press Ctrl+Space,
pick the template and get the whole statement with edit points to tab through. The mechanism
mirrors the one in 1C:EDT (the code-templates preference page), the file format included.

Templates are offered **ahead of the other completions** – the construct you are typing out ranks
above a name that merely starts the same. They need no Element data, only the LSP server
(`xbsl.lsp.enabled`, on by default): the CLI-index mode of the extension does not offer them.

The builtin set is 51 templates (`xbsl/templates_builtin.py`): the control statements, the
declarations (methods with their annotations, structures, enumerations, exception types), queries
and the applied idioms – walking a `Catalog`, register movements, an `HttpService` handler,
per-object access permissions, object events, form handlers. Every pattern is parsed by the same
parser the linter runs (`tests/test_templates.py`), so a template cannot insert code that does
not compile.

A pattern holds edit points and choices. The variables use the `${...}` syntax of 1C:EDT
templates; unlike the metadata vocabulary the platform gives them no English spelling, so the
table describes them instead of spelling them out:

| Variable | Expands to |
|---|---|
| edit point | an edit point; its argument is the pre-selected prompt text |
| choice | a dropdown of the fixed variants listed in its arguments |
| metadata name | a dropdown of **this project's** objects of the given kind (`Catalog`, `Enum`, ...), from the index |
| qualified metadata name | the same, inserted as `<Kind>.<Name>` |

Your own templates live in `.xbsl-templates.json` at the workspace root (`--file` / the
`xbsl.templates.file` setting): the file extends the builtin set, and a template with the same
name replaces the builtin one. Only what differs from the builtin set is stored, so the next
release still reaches you.

```sh
xbsl templates list                        # the whole set: builtin plus your own (* marks yours)
xbsl templates export --output my.json     # a dump (to carry your templates to another machine)
xbsl templates import dump.json            # merge a dump into your file
```

In VS Code the same thing is a panel – **XBSL: code templates** – laid out like the EDT dialog:
the list with the call context, the description and the pattern, and buttons to add, edit, delete,
import, export and restore the defaults. Saving re-reads the set in the running server, so the
next Ctrl+Space already offers the edited template.
