# Demo project · English metadata spellings

The twin of [`demo/`](../demo): the same tiny 1C:Element application, written with the ENGLISH
spellings of the metadata vocabulary (`ElementKind: Catalog`, `Name`, `Attributes`, `Content`,
`Type`). The platform reads a project either way, and this folder is what keeps the toolkit
honest about it: the rules must judge it exactly as they judge the Russian twin, and
`TaskCard.xbsl` carries the same deliberate findings (an unused local, trailing whitespace, an
em dash, an ellipsis, an unknown type).

The descriptors are English inside too - `Id`, `Vendor`, `Version`, `CompatibilityMode`,
`Interface`, `IncludeInAutoInterface`. Exactly such a project compiles: only the FILE NAMES
(`Проект.yaml`, `Подсистема.yaml`) are fixed by the platform.
Note that `elemctl` does not read those keys yet and refuses to build this project - the
descriptors are here for the linter, not for a deploy.

Enumeration values are English here as well (`Banner`, `Single`, `Double`, `Main`) - the
compiler accepts them. The generated data does not carry those pairs yet (they live
in the distribution's `*G5Enum.class`), so the linter deliberately does not judge an ASCII value
of such a property: silence beats a false error on legal code.

Where a name has no English spelling of its own, the Russian one stays - that is the platform's
own vocabulary, not an omission:

- members of the form base type (`ВыполнитьЗаписатьИЗакрыть`, `ВыполнитьЗаписать`).

The documentation shipped with the platform is Russian only, so the docs panel and hovers stay
Russian whatever the editor's display language is.
