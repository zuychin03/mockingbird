# Security policy

## Supported versions

Security fixes go into the latest release and into `main`. Older versions don't get separate fixes.

## Reporting a vulnerability

Please report vulnerabilities privately. Don't open a public issue, discussion or pull request.

1. Go to the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Include what's affected, the steps to reproduce it, the impact you expect, and the version or commit you tested.

This is a small project maintained in spare time, so a reply may take a few days. You'll hear back once the report has been looked at, and again when a fix is ready. Please keep the details private until then.

## Scope

In scope:

- The HTTP API and voice WebSocket, including another website changing anything through them.
- The cloud API key: how it's stored, and anything that sends it somewhere other than the chosen provider.
- Interview text, recordings or exports leaving the computer without the person choosing it.
- An answer that changes a score, skips consent or makes the app act, when Python is meant to decide those things.
- First-run downloads and their SHA-256 checks, the installer and the release workflow.

Out of scope:

- Problems in llama.cpp, the models, cloud providers, Python packages or browsers, unless this code uses them unsafely.
- The interviewer wording something oddly. That's a bug, so please open an issue.
- Findings that need an already compromised computer or user account.

## Keeping your installation safe

- Download the installer only from this repository's GitHub Releases. It isn't code-signed yet, so Windows SmartScreen warns before it runs.
- Mockingbird listens on 127.0.0.1 only. Don't expose its port to your network.
- Keep exports private. They hold your answers and recordings.
