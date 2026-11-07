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
| sherpa-onnx, sherpa-onnx-core | `voice` | Apache-2.0 | yes |
| praat-parselmouth | `voice` | GPL-3.0-or-later | no, installed from PyPI on first run |
| pytest, HTTPX | `test` | MIT, BSD-3-Clause | no |

**Parselmouth is GPL-3.0-or-later.** The delivery measurements import it. Installing it beside
Mockingbird, as the README describes and as the installer's first run does from PyPI on the
user's machine, leaves Mockingbird's licence as it is. A distribution that bundles it must meet
GPL-3.0 for that bundle: include the GPL text and make Parselmouth's source available.

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
