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
    "ci.no-command": {
        "ru": "В {path} нет команды xbsl – набор правил брать неоткуда",
        "en": "{path} runs no xbsl command - there is no rule set to take",
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

    def baseline_file(self) -> str | None:
        """The job's baseline as a path a local run can open.

        The job says `--baseline .xbsllint-baseline` relative to the checkout root, which is
        where the pipeline file lies - so a run started from a subdirectory (or from another
        drive) resolves it against that file, not against its own working directory.
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
        return i18n.t(key, path=self.path, job=self.job, flags=", ".join(flags))

    def hint(self) -> str:
        """The line about the jobs NOT taken, or empty when the file runs the linter once."""
        if not self.alternatives:
            return ""
        return i18n.t("ci.other-jobs", jobs=", ".join(self.alternatives))


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
    """
    path = Path(path)
    found = _commands(_load(path))
    if not found:
        raise CiLintError(i18n.t("ci.no-command", path=path))
    names = []
    for name, _argv in found:
        if name not in names:
            names.append(name)
    chosen = _pick(path, found, names, job)
    return _flags(path, found[chosen][0], found[chosen][1],
                  alternatives=tuple(n for n in names if n != found[chosen][0]))


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


def _pick(path: Path, found: list[tuple[str, list[str]]], names: list[str],
          job: str | None) -> int:
    """The index in `found` of the command to take: the first one, or the named job's."""
    if not job:
        return 0
    wanted = job.strip()
    for match in (lambda name: name == wanted,
                  lambda name: name.casefold() == wanted.casefold()):
        hits = [index for index, (name, _) in enumerate(found) if match(name)]
        if hits:
            return hits[0]
    fits = [name for name in names if wanted.casefold() in name.casefold()]
    if len(fits) > 1:
        raise CiLintError(i18n.t(
            "ci.ambiguous-job", path=path, job=wanted, jobs=", ".join(fits)))
    if fits:
        return next(index for index, (name, _) in enumerate(found) if name == fits[0])
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
           alternatives: tuple[str, ...] = ()) -> CiLint:
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
    )


#: Flags of the check mode that take a value - what to skip over when looking for the paths.
_WITH_VALUE = frozenset({
    "--write-baseline", "--jobs", "--format", "--out", "--lang", "--filename",
    "--element-version", "--data-dir",
})


def _takes_value(name: str) -> bool:
    return name in _WITH_VALUE
