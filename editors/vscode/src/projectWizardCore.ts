// Pure core of the "new 1C:Element project" wizard: input validation and assembly of the engine
// call arguments. No vscode dependency, so it is unit-tested with plain Node asserts (see
// test/projectWizardCore.test.ts). The UI layer (projectWizard.ts) maps the validation reasons to
// localized messages and drives the native prompts.
//
// Why the wizard validates stricter than the engine: the engine's _check_identifier accepts any
// identifier (the letter ё and a lowercase start included), but the 1C:Element naming standard
// wants the project vendor and name to be identifiers that start with a capital letter and carry no
// ё (the linter's project/* and naming/yo rules). Failing fast in the prompt is friendlier than a
// rejected build.

export type IdentifierReason = "empty" | "yo" | "identifier" | "lowercase";

export type IdentifierCheck =
  | { ok: true; value: string }
  | { ok: false; reason: IdentifierReason };

// A project identifier: a letter or underscore, then letters/digits/underscores. The letter ё is
// handled by a dedicated earlier check, so it is intentionally left out of this class.
const IDENTIFIER = /^[A-Za-zА-Яа-я_][A-Za-zА-Яа-я0-9_]*$/;

// Validate a project vendor/name against the naming standard. The order of the checks fixes the
// message the user sees: a blank field, then the letter ё, then a non-identifier character, then a
// lowercase start.
export function checkProjectIdentifier(raw: string): IdentifierCheck {
  const value = raw.trim();
  if (!value) {
    return { ok: false, reason: "empty" };
  }
  if (/[ёЁ]/.test(value)) {
    return { ok: false, reason: "yo" };
  }
  if (!IDENTIFIER.test(value)) {
    return { ok: false, reason: "identifier" };
  }
  if (!/^[A-ZА-Я]/.test(value)) {
    return { ok: false, reason: "lowercase" };
  }
  return { ok: true, value };
}

export interface NewProjectInput {
  root: string;
  vendor: string;
  name: string;
  representation?: string;
  library: boolean;
}

// Assemble the two transports callMeta needs: the LSP params object (xbsl/metaNewProject) and the
// CLI positional+flag argv (xbsl new-project). Kept in one place so both stay in sync with the
// engine signature - root vendor name [--representation X] [--library]. Version, compatibility and
// the first subsystem stay at the engine defaults.
export function buildNewProjectCall(input: NewProjectInput): {
  lspParams: Record<string, unknown>;
  cliArgs: string[];
} {
  const lspParams: Record<string, unknown> = {
    root: input.root,
    vendor: input.vendor,
    name: input.name,
    library: input.library,
  };
  const cliArgs: string[] = [input.root, input.vendor, input.name];
  const representation = input.representation?.trim();
  if (representation) {
    lspParams.representation = representation;
    cliArgs.push("--representation", representation);
  }
  if (input.library) {
    cliArgs.push("--library");
  }
  return { lspParams, cliArgs };
}
