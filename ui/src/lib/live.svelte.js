/* Whether a session is on air, shared by the channel strip and the interview.
 *
 * The strip is on every page, so the tally has to be right when you land on the rundown
 * directly, not only when you arrive from the interview. `sync` asks the server; the
 * interview sets the value itself on every turn so the strip never lags a request behind. */
export const live = $state({ on: false, question: 0, total: 0 });

export async function sync() {
  try {
    const res = await fetch('/api/session');
    if (!res.ok) {
      // 404 is the ordinary answer when no session has been started.
      set(null);
      return;
    }
    set(await res.json());
  } catch {
    set(null);
  }
}

export function set(session) {
  live.on = !!session && !session.done;
  live.question = session?.question_number ?? 0;
  live.total = session?.question_total ?? 0;
}
