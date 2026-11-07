# Third-party notices

Mockingbird's own code is MIT, in [LICENSE](LICENSE). This file lists the third-party work it
ships with or needs, and each one's terms. Only the typefaces are in this repository; everything
else is installed or downloaded separately and is not redistributed here.

## In this repository

| Work | Licence | Where |
|---|---|---|
| Archivo, Copyright 2020 The Archivo Project Authors | SIL Open Font License 1.1 | `ui/static/fonts/archivo.woff2` |
| Azeret Mono, Copyright 2021 The Azeret Project Authors | SIL Open Font License 1.1 | `ui/static/fonts/azeret-mono.woff2` |
| Public Sans, Copyright 2015 The Public Sans Project Authors | SIL Open Font License 1.1 | `ui/static/fonts/public-sans.woff2` |

The full notices and the licence text are in [`ui/static/fonts/OFL.txt`](ui/static/fonts/OFL.txt),
which the build copies next to the fonts.

## Compiled into the built interface

`ui/build` is generated, not committed, and carries Svelte's runtime.

| Package | Licence |
|---|---|
| Svelte | MIT |
| SvelteKit, `@sveltejs/adapter-static`, `@sveltejs/vite-plugin-svelte` | MIT |
| Vite | MIT |

## Python packages, installed by pip

| Package | Extra | Licence |
|---|---|---|
| FastAPI (with Starlette and Pydantic) | `web` | MIT (Starlette: BSD-3-Clause) |
| Uvicorn | `web` | BSD-3-Clause |
| websockets | `voice` | BSD-3-Clause |
| NumPy | `voice` | BSD-3-Clause, with bundled parts under 0BSD, MIT, Zlib and CC0-1.0 |
| sherpa-onnx | `voice` | Apache-2.0 |
| praat-parselmouth | `voice` | GPL-3.0-or-later |
| pytest, HTTPX | `test` | MIT, BSD-3-Clause |

**Parselmouth is GPL-3.0-or-later.** The delivery measurements import it. Installing it beside
Mockingbird, as the README describes, leaves Mockingbird's licence as it is. A distribution that
bundles it must meet GPL-3.0 for that bundle: include the GPL text and make Parselmouth's source
available. Mockingbird's MIT code is compatible with that.

## Models, downloaded separately

| Model | Used for | Licence |
|---|---|---|
| Qwen3-4B-Instruct-2507 | the interviewer | Apache-2.0 |
| LFM3-Audio-2B | speech recognition and the interviewer's voice | LFM Open License v1.0 |
| all-MiniLM-L6-v2 (optional) | comparing follow-up questions | Apache-2.0 |
| Silero VAD | live mode's end-of-answer detection | MIT |

**LFM Open License v1.0** follows Apache-2.0 with one limit: commercial use is licensed only to
organisations under US$10 million in annual revenue (qualifying non-profits are exempt for
non-commercial and research use). That limit applies to anyone running Mockingbird with this
model. Any redistribution of the model must include a copy of its licence.

## Runtime, installed separately

| Runtime | Used for | Licence |
|---|---|---|
| llama.cpp (`llama-server`) | all three model servers: the interviewer, the voice and the embedder | MIT |
