# Third-party notices

Mockingbird's own code is MIT, in [LICENSE](LICENSE). This file lists the third-party work it
ships with or needs, and each one's terms. Only the typefaces are in this repository. The
Windows installer also carries a Python runtime and the Python packages below; the models and
the llama.cpp runtime are downloaded on first run from their own publishers and are never
redistributed by Mockingbird.

## In this repository

| Work | Licence | Where |
|---|---|---|
| Archivo, Copyright 2020 The Archivo Project Authors | SIL Open Font License 1.1 | `ui/static/fonts/archivo.woff2` |
| Azeret Mono, Copyright 2021 The Azeret Project Authors | SIL Open Font License 1.1 | `ui/static/fonts/azeret-mono.woff2` |
| Public Sans, Copyright 2015 The Public Sans Project Authors | SIL Open Font License 1.1 | `ui/static/fonts/public-sans.woff2` |

The full notices and the licence text are in [`ui/static/fonts/OFL.txt`](ui/static/fonts/OFL.txt),
which the build copies next to the fonts.

## Compiled into the built interface

`ui/build` is generated, not committed, and carries Svelte's runtime. The installer ships it.

| Package | Licence |
|---|---|
| Svelte | MIT |
| SvelteKit, `@sveltejs/adapter-static`, `@sveltejs/vite-plugin-svelte` | MIT |
| Vite | MIT |

## Python, and the Python packages

Installed by pip from source; bundled in the Windows installer, except Parselmouth. Each
bundled package keeps its own licence file in `python\Lib\site-packages\<package>.dist-info`.

| Package | Extra | Licence | In the installer |
|---|---|---|---|
| Python 3.12 (embeddable distribution) | | PSF-2.0, in `python\LICENSE.txt` | yes |
| pip | | MIT | yes, for the first-run Parselmouth install |
| FastAPI, Pydantic, pydantic-core | `web` | MIT | yes |
| Starlette, Uvicorn, Click | `web` | BSD-3-Clause | yes |
| AnyIO, h11, annotated-types, annotated-doc, typing-inspection | `web` | MIT | yes |
| idna | `web` | BSD-3-Clause | yes |
| colorama | `web` | BSD-3-Clause | yes |
| typing-extensions | `web` | PSF-2.0 | yes |
| websockets | `voice` | BSD-3-Clause | yes |
| NumPy | `voice` | BSD-3-Clause, with bundled parts under 0BSD, MIT, Zlib and CC0-1.0 | yes |
| sherpa-onnx, sherpa-onnx-core | `voice` | Apache-2.0; its binaries also contain espeak-ng (GPL-3.0-or-later) and piper-phonemize (MIT), below | yes |
| praat-parselmouth | `voice` | GPL-3.0-or-later | no, installed from PyPI on first run |
| pytest, HTTPX | `test` | MIT, BSD-3-Clause | no |

**Parselmouth is GPL-3.0-or-later.** The delivery measurements import it. Installing it beside
Mockingbird, as the README describes and as the installer's first run does from PyPI on the
user's machine, leaves Mockingbird's licence as it is. A distribution that bundles it must meet
GPL-3.0 for that bundle: include the GPL text and make Parselmouth's source available.

**sherpa-onnx's binaries contain espeak-ng, which is GPL-3.0-or-later, so the installer ships
GPL code.** The sherpa-onnx 1.13.6 wheel declares only Apache-2.0, but its compiled libraries
(`_sherpa_onnx*.pyd`, `sherpa-onnx-c-api.dll`, `sherpa-onnx-cxx-api.dll`) build in espeak-ng and
piper-phonemize for text-to-speech phonemisation. Mockingbird uses sherpa-onnx for live mode's
voice-activity detection and does not call that code, but the installer distributes it all the
same. The GPL text is in [`LICENSES/GPL-3.0-or-later.txt`](LICENSES/GPL-3.0-or-later.txt), which
the installer carries, and the source of each part, at the exact revision built into 1.13.6, is:

| Part | Licence | Source |
|---|---|---|
| sherpa-onnx 1.13.6 | Apache-2.0 | <https://github.com/k2-fsa/sherpa-onnx/tree/v1.13.6> |
| espeak-ng, k2-fsa's fork | GPL-3.0-or-later | <https://github.com/csukuangfj/espeak-ng/archive/ed530aa113046142eb5115cf2fc9157854d0ffe1.zip>, SHA-256 `e4e262cbe34f7fe21f91f1ba3397f2728e1f30eafbae7853f2b753a9ed13f0dd` |
| piper-phonemize, k2-fsa's fork | MIT, Copyright (c) 2023 Michael Hansen | <https://github.com/csukuangfj/piper-phonemize/archive/f3ff95afc03640bc1399e113e83361192a2fafb4.zip>, SHA-256 `d9cca4e2bdc7d6dd8dffb96a4668283dbd3f77a9c194a3e530c1e8eba9406a5d` |

The revisions and hashes are the ones sherpa-onnx's own build pins, in
`cmake/espeak-ng-for-piper.cmake` and `cmake/piper-phonemize.cmake` at v1.13.6. As with
Parselmouth, this leaves Mockingbird's own code under MIT.

## Models, downloaded on first run

| Model | Used for | Licence | Source |
|---|---|---|---|
| Qwen3-4B-Instruct-2507 | the interviewer | Apache-2.0 | `lmstudio-community/Qwen3-4B-Instruct-2507-GGUF` |
| LFM3-Audio-2B | speech recognition and the interviewer's voice | LFM Open License v1.0 | `LiquidAI/LFM3-Audio-2B-GGUF` |
| all-MiniLM-L6-v2 (optional) | comparing follow-up questions | Apache-2.0 | `second-state/All-MiniLM-L6-v2-Embedding-GGUF` |
| Silero VAD | live mode's end-of-answer detection | MIT | `snakers4/silero-vad` |

**LFM Open License v1.0** follows Apache-2.0 with one limit: commercial use is licensed only to
organisations under US$10 million in annual revenue (qualifying non-profits are exempt for
non-commercial and research use). That limit applies to anyone running Mockingbird with this
model. The first run downloads the licence text with the model, into `models\lfm3-audio\LICENSE`.

## Runtime, downloaded on first run

| Runtime | Used for | Licence |
|---|---|---|
| llama.cpp (`llama-server`), release b11981 | all three model servers: the interviewer, the voice and the embedder | MIT |
| NVIDIA CUDA runtime libraries, from the same llama.cpp release | running the models on the GPU | NVIDIA CUDA EULA, redistributable components |
