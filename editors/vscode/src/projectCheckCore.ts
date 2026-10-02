// Share one explicit project pass until its completion, including cleanup after failure.
export function singleProjectCheck(work: () => Promise<void>, state: (busy: boolean) => void): () => Promise<void> {
  let pending: Promise<void> | undefined;
  return () => {
    if (pending) { return pending; }
    state(true);
    pending = Promise.resolve().then(work).finally(() => {
      pending = undefined;
      state(false);
    });
    return pending;
  };
}
