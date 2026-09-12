---
title: "Metadata scaffolding"
description: "Creating objects, attributes, routes and forms through the engine instead of hand-writing yaml – and the code templates."
sidebar:
  label: Scaffolding
  order: 6
---

Writing yaml by hand means remembering a UUID, the property names of a kind and where a form is registered. The engine does that part, and the same operations are available from the CLI, an editor and an agent.

## Metadata scaffolding

The toolkit takes over the metadata mechanics: UUIDs, indentation, precise yaml insertions,
duplicate checks and the compatibility of a section with a kind. The same operations show up in
three places. In the CLI they are subcommands with JSON output. In MCP they are the `meta_*`
tools for agents. In LSP they are the custom `xbsl/meta*` requests behind the VS Code metadata
tree.

33 kinds of project element can be created: from `Catalog` and `Document` to `VirtualTable`
paired with its mandatory `.xbql` query, `ScheduledJob`, contracts, rights and commands. Each
kind carries what the docs make mandatory. That means the platform's own default scope,
`InSubsystem` - widen it deliberately with `--scope`. It also means a module stub for the handler
the kind cannot live without, and a note about whatever the generator must not invent for you.
Kinds whose content is drawn in the designer, `ReportPanel` and `IntegrationProcess`, are
deliberately absent.

![The VS Code tree, AI agents and the terminal call the same scaffolding core; it writes created and point-edited yaml/xbsl files, the linter checks what was written, and the response carries files, notes and the lint report; the LSP surface returns full texts for the editor to apply](https://raw.githubusercontent.com/keyfire/xbsl/main/images/scaffolding.svg)

```sh
xbsl new-project . vendor App                          # descriptor + module + a subsystem
xbsl new-object <subsystem-dir> <kind> <name>          # kind: Catalog, Document, Enum, ... (--help spells them)
xbsl add-field <object>.yaml <section> <field> --type <type>
xbsl add-form . --name <object>                        # object + list forms, registered
xbsl add-form . --name <object> --forms list-cards     # list form as a card grid
xbsl new-object <subsystem-dir> <http-service-kind> <name> --routes "GET /, POST /, GET /{id}"
xbsl add-route  <service>.yaml "DELETE /{id}"          # url template + handler stub
xbsl add-method <module>.xbsl <method> --annotations <annotation> --after <existing-method>
xbsl set-localization <strings>.yaml <key> --value <language>=<text> ...  # one row, every language
xbsl add-subsystem vendor/App <name>
xbsl add-dependency . acme CurrencyConverter 2.0       # attach a library to the project
xbsl rename-object . <old-name> <new-name>             # rename files + update references
xbsl delete-object . --name <object>                   # the plan; --apply deletes and lists leftovers
xbsl set-access . --name <object> --default <access-method>
xbsl object-info . --name <object>                     # fields, tabulars, forms, namespace
xbsl project-info .                                    # projects, subsystems, objects by kind
```

The kind, the section, the annotations, the access methods and every identifier reach the CLI in
the spelling the platform uses for the project's development language. The prose of this page
names them by their English equivalents - `Catalog`, `Attributes`, `OnServer`,
`PermitAuthenticated` - which is why the examples above use placeholders.
`xbsl new-object --help` lists the kinds a project can hold, spelled the way the command wants
them.

The sources themselves may be written in either language, and the scaffolding reads both. An
object whose file spells its kind and its sections in English - `ElementKind: Catalog`,
`Attributes:` - is found, described and edited exactly like one spelled the other way; see
`demo-en/` for such a project. What the tool writes follows the file it writes into: a new
attribute of an English object gets `Name:` and `Type:`, a missing section is created as
`Attributes:`, a subsystem and a library entry are spelled like the project around them. The
pairs come from the platform data, from the metamodel's own English name of every property. So a
name the platform spells differently depending on the class keeps its original spelling in both
reading and writing, with nothing left to guess: the enumeration values section is `Items` there
and `Elements` elsewhere. Values such as types and access methods are yours and are written as
given.

`add-field` puts a new item at the end of the section of its kind, and creates that section only
when the file has none. A register keeps its data in `Dimensions` and `Resources`. So an
attribute asked of a register that holds resources and no attributes lands in a new `Attributes`
section at the end of the file. The `notes` field says so and names the kind that would have
placed the field beside the existing ones: a resource here, and the other way round for a
resource asked where only attributes exist.

Forms are generated with real content: input fields per attribute, including the standard
`Name`, `Number` and `Date` fields and hierarchy support, `DynamicList` columns, `TabularParts`
tables and a report form with parameters. The form is registered in the `Interface` section of
its owner. `--dry-run` prints the changes with full file texts and writes nothing. That is the
flag the VS Code extension uses: it applies the changes itself, through its own undo-friendly
edits.

The captions of the form and of its columns go through the project's dictionary. When the
subsystem folder holds one `LocalizedStrings` element and the descriptor declares two
localization languages, a caption is written as `$Dictionary.Name`. The keys those references
need join the dictionary, and the translations it already has, in the same operation: a reference
to a key nobody declares fails the apply. Without such a dictionary the caption stays a
literal.

`--forms list-cards` builds the list form as a card grid instead of a table: a `CustomList`
whose `RowsContainer` is a `MatrixGroup`, plus a generated `ListRow<Name>` row component named
after the object. The card takes a `Title`, a photo and up to three more fields, with dates
formatted. An attribute of type `BinaryObject.Reference` switches the card to `CustomCard`, with
the image above the caption. The `notes` field reports what landed on the card and what did not.
`--card-min-width` sets the grid column width, 400 by default and 250 with a photo, and
`--card-placeholder` sets the image shown when the photo is empty.

`set-localization` writes one localized string into every language at once. The text of the
default language goes into the `LocalizedStrings` element itself, which is where the platform
keeps it; every other language gets its own `Localization/<Code>/<Name>.yaml`. This was the
missing half of `add-localization`, which adds a language. A caption used to be typed into the
element and again into its English twin, the two files drifted apart, and nothing but a pair of
eyes could compare them. A language named without a translation file is refused: add the language
first. An existing language the call says nothing about still gets the row, with the default text
and a note, so no translation is left a key short. A key keeps the section it already lives in,
and a new one goes to `Rows` unless `--section` says `Templates`.

`add-field --kind строка` (`meta_add_field`) adds the key. It lands in the element and is echoed
into the translations that already exist, with the default-language text, so none of them is left
a key short. The note names `set-localization`, which is what writes the text of a translation. A
call on the translation file itself is refused, because that file carries neither a kind nor the
sections of an element. The refusal names the element the file belongs to and the same
`set-localization`. It used to read "the kind ? has no section for it".

`add-dependency` attaches a library: it writes the `Libraries` section of the project descriptor
with `Name`, `Vendor` and `Version`. The version here is the library's **release** version. A
release is issued in the control panel, and a build version with a suffix such as `1.0-42` is
rejected. Different versions of one library within a project are not allowed, so attaching a
library that is already attached updates the version of the existing entry. What is attached now
shows up in `project-info` under `projects[].libraries`. The vendor, name, version and the
qualified type names of a library come from parsing its archive:
`elemctl inspect <file.xlib>`.

`set-access` edits `AccessControl.Permissions` of an object in place, and it knows what each kind
allows. `--default` sets the `Default` right. `--permission Read=PermitEveryone` sets an
individual one, custom rights of a `PrivilegeOnElement` included. `--calc-by` fills
`ComputePermissionsBy`, which is mandatory for `PermissionsComputedForEachObject`. Wrong methods,
rights a kind does not have, and per-object rights on a `ConstantsSet` are all rejected. The
computed-permission handlers stay yours to write, and the `notes` field says which ones you need.
`object-info` reports the current permissions and the kind's rights, `project-info` the `Default`
of every object. No section there means the platform falls back to `PermitAdmins`.

`rename-object` renames the object's files, including its forms and the generated
`ListRow<Name>` component of a card list. References it rewrites across the whole project and
with an eye on the context: the reference-bearing yaml keys `Type`, `Table`, `DataSource`, `Form`
and `FormType`, the `=` bindings and the .xbsl code. Attributes, components or dynamic-list
fields that merely share the old name are left alone, and so are string literals with UI text.
`--new-presentation` and `--old-presentation` update the `Title` and `Presentation` of the object
and its forms. The object's `Id` is untouched, so the platform keeps the stored data.

`delete-object` deletes an object whole: the yaml and module pair, its forms and the generated
`ListRow<Name>` row component, with their pairs. A subsystem is the folder the files live in, so
the membership goes away with them. Every remaining mention of the name across the project is
listed by file and line, string literals and comments included. A router opening a form by a name
in a string, or code seeding data, is exactly the leftover that otherwise surfaces as a runtime
error. The command does not edit those mentions: which one is dead code is the author's call.
Deletion is irreversible, so without `--apply` the command prints the plan. The MCP tool
`meta_delete_object` answers with a plan too, since its `dry_run` defaults to true.

A rename that only changes letter case, `Goods` into `goods`, runs in two steps through a
temporary name. A case-insensitive filesystem, Windows or macOS, addresses the old and the new
name as one file, and a single-step rename between them is not guaranteed. A failure of the
second step undoes the first and leaves no temporary name on disk. On a case-sensitive filesystem
the name is free and the rename runs in a single step. The tool renames the files itself, but
check the version control system. Git on a case-insensitive filesystem folds ASCII letters only,
so a Latin rename goes unnoticed: record it explicitly with `git mv <old> <new>`. A Cyrillic one
is recorded as a delete plus an add, and then every other clone on such a filesystem stops at
"untracked working tree files would be overwritten by merge". There the file under the old name
has to be deleted before pulling.

## Code templates

A template is a short trigger plus a construct. Type the first letters of `if`, press
Ctrl+Space, pick the template, and the whole statement arrives with edit points to tab through.
The mechanism mirrors the one in 1C:EDT (the code-templates preference page), file format
included.

Templates are offered **ahead of the other completions**: the construct you are typing out ranks
above a name that merely starts the same. They need no Element data, only the LSP server
(`xbsl.lsp.enabled`, on by default). The CLI-index mode of the extension does not offer them.

The builtin set is 51 templates, all in `xbsl/templates_builtin.py`: the control statements, the
declarations (methods with their annotations, structures, enumerations, exception types), queries
and the applied idioms - walking a `Catalog`, register movements, an `HttpService` handler,
per-object access permissions, object events, form handlers. Every pattern is parsed by the same
parser the linter runs (`tests/test_templates.py`), so a template cannot insert code that does
not compile.

A pattern holds edit points and choices. The variables use the `${...}` syntax of 1C:EDT
templates. The platform gives them no English spelling, the way it does for the metadata
vocabulary, so the table describes them instead of spelling them out:

| Variable | Expands to |
|---|---|
| edit point | an edit point; its argument is the pre-selected prompt text |
| choice | a dropdown of the fixed variants listed in its arguments |
| metadata name | a dropdown of **this project's** objects of the given kind (`Catalog`, `Enum`, ...), from the index |
| qualified metadata name | the same, inserted as `<Kind>.<Name>` |

Your own templates live in `.xbsl-templates.json` at the workspace root; the path comes from
`--file` or from the `xbsl.templates.file` setting. The file extends the builtin set, and a
template with the same name replaces the builtin one. Only what differs from the builtin set is
stored, so the next release still reaches you.

```sh
xbsl templates list                        # the whole set: builtin plus your own (* marks yours)
xbsl templates export --output my.json     # a dump (to carry your templates to another machine)
xbsl templates import dump.json            # merge a dump into your file
```

In VS Code the same thing is the **XBSL: code templates** panel, laid out like the EDT dialog:
the list with the call context, the description and the pattern, and buttons to add, edit,
delete, import, export and restore the defaults. Saving re-reads the set in the running server,
so the next Ctrl+Space already offers the edited template.
