"""The rule set a project's CI job runs, read from the pipeline file itself.

A project turns rules on in its pipeline (`xbsl e1c --enable conventions/missing-translation
...`), and a local run without those flags judges a narrower set: the difference is learned
from a red job, one push later. That happened on a file of the translation dictionary - the
finding existed, nothing local had a reason to report it.

The honest fix is not a second list of rules to keep in step, but reading the ONE list that
actually runs: the pipeline file next to the project. `xbsl --as-ci` (and `lint_paths(as_ci)`)
finds the file, takes the flags of its xbsl command and runs with them, so a local pass and
the job agree by construction.

What is taken is the RULE SET and the baseline - `--select`, `--ignore`, `--enable`,
`--baseline`/`--no-baseline`: everything that changes the verdict. What the job's command
says about transport - `--jobs`, `--format`, `--out`, the paths - is left to the caller, who
is linting one file as often as the whole tree.

The reader is format-agnostic on purpose: it walks the parsed YAML for the keys that hold
shell commands (`script`, `before_script`, `after_script`, `run`), so a GitLab job and a
GitHub Actions step are read by the same code.

A pipeline runs the linter more than once as soon as a project builds a second tree: one job
checks the sources, another checks what `translate` wrote, and those two judge DIFFERENT sets
(the translated tree has no baseline of its own and switches a rule off). Taking the first
command silently describes one of them, so the job can be named - `--as-ci-job <name>` - and
a file with more than one is reported by `alternatives`, which is how a caller learns there
was a choice at all.

A pipeline is rarely ONE file. GitLab's `include:` pulls the jobs in from elsewhere, and a
project on a shared template keeps the lint job exactly there - so a reader of the root file
alone answered "this pipeline runs no xbsl command" about a pipeline that runs one. The local
files of the repository are followed: `include: file.yml`, `include: {local: /ci/lint.yml}`,
lists of either, and the patterns GitLab expands there (`ci/*.yml`). Everything else is NOT
fetched - a remote URL, a GitLab template, a file of another project, a component - because
that needs the network and credentials, and a linter that downloads a URL out of a config
file behind the caller's back is a surprise, not a feature. What was left unread is NAMED
(`unread`, the `note()` line, the "runs no xbsl command" refusal), so a job that stays
invisible has a reason next to it instead of being a mystery.

Local includes are resolved against the ROOT of the checkout - the directory of the pipeline
file the run started from - as GitLab resolves them, and a nested include repeats that rather
than resolving against the file that writes it.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from xbsl import i18n

MESSAGES = {
    "ci.no-file": {
        "ru": "Рядом с проектом нет файла CI ({names}); укажите его: --as-ci <файл>",
        "en": "No CI file next to the project ({names}); name one: --as-ci <file>",
    },
    "ci.unreadable": {
        "ru": "Не прочитать {path}: {error}",
        "en": "Cannot read {path}: {error}",
    },
    "ci.named-directory": {
        "ru": "--as-ci берёт ФАЙЛ пайплайна, а {path} – каталог. Проверить его набором из CI:"
              " xbsl {path} --as-ci (ключ пишется ПОСЛЕ путей); файл пайплайна внутри каталога"
              " называют полным именем",
        "en": "--as-ci takes the pipeline FILE, and {path} is a directory. To check it with"
              " the CI rule set: xbsl {path} --as-ci (the flag goes AFTER the paths); a"
              " pipeline file inside the directory is named in full",
    },
    "ci.no-command": {
        "ru": "В {path} нет команды xbsl – набор правил брать неоткуда",
        "en": "{path} runs no xbsl command - there is no rule set to take",
    },
    "ci.unread-includes": {
        "ru": "Включения не читались (нужна сеть или чужой репозиторий): {items}",
        "en": "Includes left unread (they need the network or another repository): {items}",
    },
    "ci.from-include": {
        "ru": "{path} (включение {source})",
        "en": "{path} (include {source})",
    },
    "ci.adopted": {
        "ru": "Набор правил как в CI: {path}, джоба {job} – {flags}",
        "en": "Rule set as in CI: {path}, job {job} - {flags}",
    },
    "ci.adopted-nothing": {
        "ru": "Набор правил как в CI: {path}, джоба {job} – своих ключей у команды нет",
        "en": "Rule set as in CI: {path}, job {job} - the command carries no flags of its own",
    },
    "ci.other-jobs": {
        "ru": "Линтер в этом файле гоняет ещё: {jobs} – выбрать: --as-ci-job <имя>",
        "en": "The linter also runs in: {jobs} - choose one with --as-ci-job <name>",
    },
    "ci.no-job": {
        "ru": "В {path} нет джобы {job} с командой xbsl; есть: {jobs}",
        "en": "{path} has no job {job} running xbsl; it has: {jobs}",
    },
    "ci.ambiguous-job": {
        "ru": "В {path} под '{job}' подходит несколько джоб: {jobs} – назовите одну целиком",
        "en": "In {path} '{job}' fits several jobs: {jobs} - name one in full",
    },
}
i18n.register(MESSAGES)

#: The pipeline files looked for next to a project, in the order they are tried.
CI_FILES = (".gitlab-ci.yml", ".gitlab-ci.yaml", ".github/workflows")
#: Mapping keys whose value is a shell command (a string or a list of them).
_SCRIPT_KEYS = frozenset({"script", "before_script", "after_script", "run"})
#: Container keys that name no job - the job is the nearest key outside this set.
_CONTAINERS = frozenset({"jobs", "steps", "include", "default", "stages", "workflow"})
#: How the linter is invoked from a shell line.
_ENTRY_POINTS = frozenset({"xbsl", "xbsllint"})


class CiLintError(Exception):
    """A CI file that cannot answer "what does the job check" - the message is user-facing."""


@dataclass(frozen=True)
class CiLint:
    """The verdict-shaping half of a CI xbsl command."""

    path: Path
    job: str
    argv: tuple[str, ...]
    select: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    enable: tuple[str, ...] = ()
    baseline: str | None = None
    no_baseline: bool = False
    #: The paths the job checks - reported, never imposed: a local run lints what it is asked to.
    paths: tuple[str, ...] = field(default=())
    #: The OTHER jobs of the same file that run the linter, in document order. A run that was
    #: not told which job to take says out loud that there was a choice: the second job of a
    #: bilingual project judges a different tree by a different set, and a caller who never
    #: learns it exists compares its verdict with the wrong one.
    alternatives: tuple[str, ...] = field(default=())
    #: The INCLUDED file the command was read from - None when it stands in `path` itself.
    #: Named because "job X of .gitlab-ci.yml" is then a half-truth: the command a reader
    #: would go looking for is in another file, and on a shared template it is not even the
    #: project's own.
    source: Path | None = None
    #: The includes this reader did not open: a remote URL, a template, another project, a
    #: component. Carried rather than swallowed - a job that lives in one of them stays
    #: invisible, and the caller is the one who can tell whether that matters.
    unread: tuple[str, ...] = field(default=())

    def baseline_file(self) -> str | None:
        """The job's baseline as a path a local run can open.

        The job says `--baseline .xbsllint-baseline` relative to the checkout root, which is
        where the pipeline file lies - so a run started from a subdirectory (or from another
        drive) resolves it against that file, not against its own working directory. An
        included file does not move that origin: the job runs in the checkout of the ROOT
        file, and its baseline is relative to that checkout however deep the `include:` chain
        went.
        """
        if not self.baseline:
            return None
        named = Path(self.baseline)
        return str(named if named.is_absolute() else self.path.parent / named)

    def describe(self) -> str:
        """The line a run prints about itself: what was adopted and where from."""
        flags = []
        for name, values in (("--select", self.select), ("--ignore", self.ignore),
                             ("--enable", self.enable)):
            flags += [f"{name} {value}" for value in values]
        if self.baseline:
            flags.append(f"--baseline {self.baseline}")
        if self.no_baseline:
            flags.append("--no-baseline")
        key = "ci.adopted" if flags else "ci.adopted-nothing"
        return i18n.t(key, path=self.where(), job=self.job, flags=", ".join(flags))

    def where(self) -> str:
        """The file to open to read this job - the root pipeline file, or the include in it."""
        if self.source is None:
            return str(self.path)
        return i18n.t("ci.from-include", path=self.path, source=self.source)

    def hint(self) -> str:
        """The line about the jobs NOT taken, or empty when the file runs the linter once."""
        if not self.alternatives:
            return ""
        return i18n.t("ci.other-jobs", jobs=", ".join(self.alternatives))

    def note(self) -> str:
        """The line about the includes left unread, or empty when there were none.

        Apart from `hint()` on purpose: the alternatives are silenced once the caller names a
        job, while a blind spot of the reader stays worth saying out loud - the job the caller
        is looking for may be exactly the one behind a template nobody fetched.
        """
        if not self.unread:
            return ""
        return i18n.t("ci.unread-includes", items=_listed(self.unread))


def discover(start: Path | str) -> Path | None:
    """The pipeline file at `start` or above it - the way the baseline file is found."""
    here = Path(start).resolve()
    if here.is_file():
        here = here.parent
    for directory in (here, *here.parents):
        for name in CI_FILES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
            if candidate.is_dir():  # .github/workflows - every workflow of the repository
                workflows = sorted(
                    path for path in candidate.iterdir()
                    if path.suffix in (".yml", ".yaml") and path.is_file()
                )
                for workflow in workflows:
                    if _commands(_load(workflow)):
                        return workflow
    return None


def read(path: Path | str, job: str | None = None) -> CiLint:
    """The rule set of an xbsl command in the pipeline file. Raises CiLintError.

    Without `job` the FIRST command wins - the one a single-job pipeline has anyway. With it
    the named job is taken, so a project that lints a second tree in a second job can ask for
    that one; the name is matched as written, then case-blind, then as a part of a job name
    when exactly one fits (`--as-ci-job english` for "English to S3" - a name with spaces is
    tedious to quote, and a half-typed one that fits two jobs is refused, not guessed).

    A DIRECTORY named here is the typo the flag invites: `--as-ci` takes an optional file name,
    so `xbsl --as-ci e1c` hands it the tree that was meant to be checked, leaving the run to
    lint the current directory - and the reader got "cannot read e1c" from the file system,
    which says nothing about the mistake. The refusal names the flag's subject and the form
    that works instead of letting the file system speak for it.
    """
    path = Path(path)
    if path.is_dir():
        raise CiLintError(i18n.t("ci.named-directory", path=path))
    documents, unread = _documents(path)
    found: list[tuple[str, list[str], Path]] = [
        (name, argv, where)
        for where, document in documents
        for name, argv in _commands(document)
    ]
    if not found:
        refusal = i18n.t("ci.no-command", path=path)
        if unread:
            # The pipeline may well run the linter - in a template this reader did not fetch.
            # Ending on "runs no xbsl command" alone sends the caller to look for a mistake
            # in a file that does not have one.
            refusal += ". " + i18n.t("ci.unread-includes", items=_listed(unread))
        raise CiLintError(refusal)
    names: list[str] = []
    for entry in found:
        if entry[0] not in names:
            names.append(entry[0])
    chosen = _pick(path, found, names, job)
    name, argv, where = found[chosen]
    return _flags(path, name, argv,
                  alternatives=tuple(n for n in names if n != name),
                  source=None if where == path else where,
                  unread=tuple(unread))


def find(
    paths: list[str] | tuple[str, ...],
    named: str | None = None,
    job: str | None = None,
) -> CiLint:
    """The CI rule set for a run over `paths` - the named file, or the one found above them."""
    if named:
        return read(named, job)
    for start in list(paths) or ["."]:
        found = discover(start)
        if found is not None:
            return read(found, job)
    raise CiLintError(i18n.t("ci.no-file", names=", ".join(CI_FILES)))


def _pick(path: Path, found: list[tuple[str, list[str], Path]], names: list[str],
          job: str | None) -> int:
    """The index in `found` of the command to take: the first one, or the named job's."""
    if not job:
        return 0
    wanted = job.strip()
    for match in (lambda name: name == wanted,
                  lambda name: name.casefold() == wanted.casefold()):
        hits = [index for index, entry in enumerate(found) if match(entry[0])]
        if hits:
            return hits[0]
    fits = [name for name in names if wanted.casefold() in name.casefold()]
    if len(fits) > 1:
        raise CiLintError(i18n.t(
            "ci.ambiguous-job", path=path, job=wanted, jobs=", ".join(fits)))
    if fits:
        return next(index for index, entry in enumerate(found) if entry[0] == fits[0])
    raise CiLintError(i18n.t("ci.no-job", path=path, job=wanted, jobs=", ".join(names)))


def _load(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CiLintError(i18n.t("ci.unreadable", path=path, error=exc)) from exc
    try:
        # A pipeline file may carry tags a plain loader refuses (`!reference` in GitLab); the
        # composer's error is not a reason to lose the rule set, so unknown tags are dropped.
        return yaml.load(text, Loader=_Loader)
    except yaml.YAMLError as exc:
        raise CiLintError(i18n.t("ci.unreadable", path=path, error=exc)) from exc


class _Loader(yaml.SafeLoader):
    """SafeLoader that does not choke on a pipeline's own tags."""


_Loader.add_multi_constructor("!", lambda loader, suffix, node: None)


#: Keys of an `include:` entry that name something outside this checkout. Not fetched: each
#: needs the network (and often a token), and downloading a URL taken out of a config file is
#: not what a caller asked a linter to do.
_FOREIGN_INCLUDES = ("remote", "template", "project", "component")
#: How deep an `include:` chain is followed. A template that includes a template is ordinary;
#: ten of them are a loop nobody meant to write, and `seen` already stops the honest ones.
_INCLUDE_DEPTH = 10
#: How many unread includes are named before the count takes over - a pipeline of a big
#: project pulls in a dozen templates, and a dozen names is a wall, not a message.
_UNREAD_SHOWN = 3


def _documents(path: Path) -> tuple[list[tuple[Path, object]], list[str]]:
    """The pipeline file with every LOCAL file its `include:` pulls in, and what stayed unread.

    The root file comes first, and that is GitLab's own precedence: a job defined both in the
    file and in what it includes is the file's. Order matters here because the first xbsl
    command wins when no job is named.
    """
    document = _load(path)
    documents: list[tuple[Path, object]] = [(path, document)]
    unread: list[str] = []
    _follow(document, path.parent, {path.resolve()}, documents, unread, 0)
    return documents, unread


def _follow(document: object, base: Path, seen: set[Path],
            documents: list[tuple[Path, object]], unread: list[str], depth: int) -> None:
    """Walk one document's `include:`, appending what was read and what was not."""
    if depth >= _INCLUDE_DEPTH:
        return
    for entry in _include_entries(document):
        if isinstance(entry, str):
            if _is_url(entry):
                unread.append(f"remote: {entry}")
                continue
            targets = _local_targets(entry, base)
        elif isinstance(entry, dict):
            if "local" not in entry:
                unread.append(_foreign(entry))
                continue
            targets = _local_targets(entry["local"], base)
        else:
            continue
        for target in targets:
            key = target.resolve()
            if key in seen:  # a file included twice, and the loop a template can close
                continue
            seen.add(key)
            try:
                included = _load(target)
            except CiLintError as exc:
                # A local include the checkout does not have is the likeliest reason a job
                # cannot be found, so it is named with the rest rather than raised: the root
                # file may still carry the command that was asked for.
                unread.append(str(exc))
                continue
            documents.append((target, included))
            _follow(included, base, seen, documents, unread, depth + 1)


def _include_entries(document: object) -> list[object]:
    """The entries of `include:` - one string, one mapping, or a list of either."""
    if not isinstance(document, dict):
        return []
    value = document.get("include")
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _local_targets(value: object, base: Path) -> list[Path]:
    """The files a local include names, resolved against the root of the checkout.

    A leading slash is how GitLab spells "from the repository root" and is not a path from the
    root of the drive. The patterns GitLab expands there (`ci/*.yml`) are expanded too - a
    project that keeps a job per file in a folder writes exactly that, and reading the pattern
    as a file name would lose every one of them.
    """
    names = value if isinstance(value, list) else [value]
    found: list[Path] = []
    for name in names:
        if not isinstance(name, str) or not name.strip():
            continue
        spelled = name.strip().lstrip("/")
        if any(sign in spelled for sign in "*?["):
            found += sorted(match for match in base.glob(spelled) if match.is_file())
        else:
            found.append(base / spelled)
    return found


def _is_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


def _foreign(entry: dict) -> str:
    """A short label for an include that is not a file of this checkout."""
    if "project" in entry:
        files = entry.get("file")
        named = files if isinstance(files, list) else ([files] if files else [])
        ref = f"@{entry['ref']}" if entry.get("ref") else ""
        tail = " " + ", ".join(str(name) for name in named) if named else ""
        return f"project: {entry['project']}{ref}{tail}"
    for key in _FOREIGN_INCLUDES:
        if key in entry:
            return f"{key}: {entry[key]}"
    return "include: " + ", ".join(sorted(str(key) for key in entry))


def _listed(items: tuple[str, ...] | list[str]) -> str:
    """The unread includes as one line: the first few by name, the rest as a count."""
    shown = ", ".join(items[:_UNREAD_SHOWN])
    rest = len(items) - _UNREAD_SHOWN
    return f"{shown} (+{rest})" if rest > 0 else shown


def _commands(document: object) -> list[tuple[str, list[str]]]:
    """[(job, argv)] for every xbsl CHECK command in the file, in document order."""
    found: list[tuple[str, list[str]]] = []
    for job, line in _shell_lines(document, ()):
        for argv in _split(line):
            if _is_check(argv):
                found.append((job, argv))
    return found


def _shell_lines(node: object, keys: tuple[str, ...]) -> list[tuple[str, str]]:
    """Every shell command string of the document, each with the job it belongs to."""
    lines: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            name = str(key)
            if name in _SCRIPT_KEYS:
                job = next((part for part in reversed(keys) if part not in _CONTAINERS), name)
                for text in (value if isinstance(value, list) else [value]):
                    if isinstance(text, str):
                        lines += [(job, text)]
            else:
                lines += _shell_lines(value, keys + (name,))
    elif isinstance(node, list):
        for item in node:
            lines += _shell_lines(item, keys)
    return lines


def _split(line: str) -> list[list[str]]:
    """A script entry -> the argv of each command in it (newlines, `&&`, `;` separate them)."""
    argvs = []
    for statement in line.replace("&&", "\n").replace(";", "\n").splitlines():
        statement = statement.strip()
        if not statement:
            continue
        try:
            argv = shlex.split(statement, posix=True)
        except ValueError:  # an unbalanced quote - not a command we can read
            continue
        if argv:
            argvs.append(argv)
    return argvs


def _is_check(argv: list[str]) -> bool:
    """Whether the command is a linter RUN - not `xbsl translate`, not another program."""
    head = Path(argv[0]).name.lower()
    head = head[:-4] if head.endswith(".exe") else head
    rest = argv[1:]
    if head in ("python", "python3", "py") and rest[:2] == ["-m", "xbsl"]:
        rest = rest[2:]
    elif head not in _ENTRY_POINTS:
        return False
    from xbsl.cli import COMMANDS  # imported here: the CLI imports this module in turn

    first = next((token for token in rest if not token.startswith("-")), None)
    return first not in {command.name for command in COMMANDS}


def _flags(path: Path, job: str, argv: list[str],
           alternatives: tuple[str, ...] = (),
           source: Path | None = None,
           unread: tuple[str, ...] = ()) -> CiLint:
    """The verdict-shaping flags of one command line; everything else is the caller's."""
    lists: dict[str, list[str]] = {"--select": [], "--ignore": [], "--enable": []}
    baseline: str | None = None
    no_baseline = False
    paths: list[str] = []
    tokens = list(argv[1:])
    while tokens:
        token = tokens.pop(0)
        name, _, inline = token.partition("=")
        if name in lists:
            value = inline if inline else (tokens.pop(0) if tokens else "")
            # A flag takes a comma-separated list as readily as a repetition - both forms
            # reach the engine as one set, and the CLI splits them the same way.
            lists[name] += [part.strip() for part in value.split(",") if part.strip()]
        elif name == "--baseline":
            baseline = inline if inline else (tokens.pop(0) if tokens else "")
        elif name == "--no-baseline":
            no_baseline = True
        elif token.startswith("-"):
            # Another flag: drop its value too, so a path is not read out of it.
            if not inline and tokens and not tokens[0].startswith("-") and _takes_value(name):
                tokens.pop(0)
        else:
            paths.append(token)
    return CiLint(
        path=path, job=job, argv=tuple(argv),
        select=tuple(lists["--select"]), ignore=tuple(lists["--ignore"]),
        enable=tuple(lists["--enable"]), baseline=baseline or None,
        no_baseline=no_baseline, paths=tuple(paths), alternatives=alternatives,
        source=source, unread=unread,
    )


#: Flags of the check mode that take a value - what to skip over when looking for the paths.
_WITH_VALUE = frozenset({
    "--write-baseline", "--jobs", "--format", "--out", "--lang", "--filename",
    "--element-version", "--data-dir",
})


def _takes_value(name: str) -> bool:
    return name in _WITH_VALUE
