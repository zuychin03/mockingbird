# Contributing to Mockingbird

Thanks for helping. Mockingbird is maintained by one person, so small, focused pull requests get reviewed fastest. For anything large, open an issue first so we can agree on the approach before you build it.

## What Mockingbird holds to

- **The model writes sentences. Python owns consent, pacing and every score.** A change that hands one of those decisions to the model won't be merged.
- **Local first.** Nothing leaves the computer unless the person chooses a cloud provider and confirms what it sends, and recordings never leave it. `tests/test_nfr.py` checks this.
- **A text interview needs only the standard library.** Third-party packages belong in an optional extra in `pyproject.toml`, and nothing on the text path may import one.
- **Measured behaviour.** The interviewer's prompts, the question bank and the choice of model were tuned against recorded interviews that aren't in this repository. Open an issue before changing them, because fixture tests alone can't show whether a change helps.

## Set up and run the tests

Mockingbird is built and released on Windows, and the commands below use its shell. Use Python 3.12 or later, and Node for the interface.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[test,web,voice]"
python -m pytest
```

The install is editable on purpose, because paths are resolved from the repository root. Some tests are skipped without the `web` or `voice` extras, and the encrypted key tests run only on Windows. The tests don't need the models or a GPU.

To run the app with its interface:

```bash
npm --prefix ui install
npm --prefix ui run build
python -m uvicorn api.main:app --port 8000
```

A real interview also needs the models and `llama-server`. `python -m app.download` fetches them and `python -m app.servers` starts them. See [Running it from source](README.md#running-it-from-source).

## Where things live

The [layout](README.md#layout) in the README lists every module, and the [architecture](docs/ARCHITECTURE.md) explains how they fit together. In short, `app/` is the runtime, `api/` the HTTP and WebSocket surface, `ui/` the SvelteKit interface, `config/` the plans and question bank, and `installer/` the Windows installer build.

## Interface changes

- Follow [DESIGN.md](DESIGN.md), the design system the interface is built from. The tokens live in `ui/src/lib`, and `tests/test_theme.py` checks their contrast from the stylesheet.
- Check every surface at both widths. `tools/shots.sh` takes the screenshots.

## Pull requests

- Keep each pull request to one change, with tests for new behaviour and for the bug you fixed.
- Say what changed, why, and how you checked it. Add screenshots at both widths for interface changes.
- Describe user-visible changes in the pull request. The maintainer updates [CHANGELOG.md](CHANGELOG.md).
- Never commit recordings, sessions, anything from `data/`, model files or API keys.

## Licence

Mockingbird's code is licensed under [MIT](LICENSE). By contributing, you agree that your contributions are licensed under the same terms. Third-party parts keep their own licences, listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
