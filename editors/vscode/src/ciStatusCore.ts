// Pure core of the CI-parity indicator (no vscode import), unit-tested under plain Node.
//
// Why an indicator at all: `xbsl.linter.asCi` makes the panel judge by the rule set of the
// project's CI job, and until now the only trace of what came of that was one line in the
// XBSL output channel, printed once at startup. Nobody reads that channel while looking at a
// finding. Worse, the server does NOT refuse when there is no pipeline file - a refusal would
// cost the whole editing session - so it quietly goes on judging by the settings' own rules
// while the reader believes the panel and the merge request agree. That state deserves a word
// in the place where the verdict is read.
//
// The wording is NOT built here. The server answers with its own sentences (the same ones the
// output channel carries, in the language it was started with), and this module only decides
// WHICH state the bar is in and which lines belong in the tooltip - so the editor and the
// channel cannot start describing one adoption in two different ways.

// What the server answers to `xbsl/ciStatus`. Everything is optional: an older engine has no
// such request at all, and `lspRequest` then hands back undefined.
export interface CiStatus {
  enabled?: boolean;
  adopted?: boolean;
  job?: string;
  file?: string | null;
  source?: string | null;
  jobs?: string[];
  unread_includes?: string[];
  line?: string;
  hint?: string;
  note?: string;
  error?: string;
}

// "off" - the parity was never asked for (or the engine does not answer): show nothing.
// "adopted" - the job's set is what the panel judges by.
// "refused" - it was asked for and NOT taken; the settings' own rules are in force.
export type CiState = "off" | "adopted" | "refused";

export interface CiIndicator {
  state: CiState;
  job: string;
  // The server's own lines, in the order it prints them, with the empty ones dropped.
  details: string[];
  // The file a click opens: the include the command actually stands in, or the root file.
  open?: string;
}

// How much of a job name fits the status bar before it starts pushing everything else out.
const NAME_LIMIT = 24;

export function ciIndicator(status: CiStatus | undefined): CiIndicator {
  if (!status || status.enabled !== true) {
    return { state: "off", job: "", details: [] };
  }
  if (!status.adopted) {
    return { state: "refused", job: "", details: lines([status.error]) };
  }
  return {
    state: "adopted",
    job: (status.job ?? "").trim(),
    details: lines([status.line, status.hint, status.note]),
    open: (status.source || status.file || undefined) ?? undefined,
  };
}

// The job name as the bar shows it: trimmed, and cut with an ellipsis when it is a sentence
// rather than a name ("Lint the sources of the application" happens).
export function shortJob(job: string): string {
  const name = (job ?? "").trim();
  return name.length > NAME_LIMIT ? `${name.slice(0, NAME_LIMIT - 3)}...` : name;
}

function lines(parts: (string | undefined)[]): string[] {
  return parts.map((part) => (part ?? "").trim()).filter((part) => part.length > 0);
}
