"""Source-to-source translation of a project into English spellings.

The platform is bilingual all the way into the sources: every keyword, metadata key, type,
member and enumeration value has an English spelling, extracted from the distribution into
the dataset. This package rewrites a whole project into those spellings: platform tokens by
the metamodel and the term dictionaries, the project's OWN names and comments by a project
dictionary (see dictionary.py), localized-string dictionaries by swapping the base language.

Entry points: `xbsl translate` (cli.py), the `conventions/missing-translation` rule
(xbsl/rules/translation_gaps.py) and `project.translate_project` for tooling.
"""
