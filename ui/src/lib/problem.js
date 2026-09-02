/* Turning a failure into something a person can act on.
 *
 * The three pages used to render `String(e)`, so the most likely failure of a local-only app
 * -- LM Studio not serving -- reached the screen as the words "TypeError: Failed to fetch".
 * A refusal the server wrote is different: those sentences exist to explain a reason, so they
 * are shown as written and never dressed up. */

const UNREACHABLE = {
  title: 'Cannot reach Mockingbird',
  detail:
    'The interview runs on this machine, so nothing here works while the server is down. ' +
    'Check that it is still running, then try again.'
};

const NO_MODEL = {
  title: 'The model is not loaded',
  detail:
    'Mockingbird talks to LM Studio on this machine. Start its server and load the model, ' +
    'then try again.'
};

/** A network-level failure: the request never reached the server. */
export function unreachable(error) {
  return { ...UNREACHABLE, raw: String(error) };
}

/** A refusal the server described. `status` decides how much help to add around it. */
export function refused(status, detail) {
  if (status === 503) {
    return { ...NO_MODEL, detail: detail || NO_MODEL.detail, raw: null };
  }
  return { title: null, detail: detail || 'Something went wrong.', raw: null };
}
