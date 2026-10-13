<!-- Center the project introduction and its navigation, as in the other demo READMEs. -->
<div align="center">

# OpenRouter + Render Sandboxes

Ask an AI model to fix Python code in a Render Sandbox, a temporary computer separate from your own.

<!-- Each badge names a component and links to its documentation or client folder. -->
<p>
  <a href="https://render.com/docs/sandboxes?utm_source=github&amp;utm_medium=referral&amp;utm_campaign=ojus_demos&amp;utm_content=readme_badge" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Render-Sandboxes-6e40c9?logo=render&amp;logoColor=white" alt="Render Sandboxes" /></a>
  <a href="https://openrouter.ai/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/OpenRouter-Models-555555?logo=openrouter&amp;logoColor=white" alt="OpenRouter Models" /></a>
  <a href="typescript/main.ts" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/TypeScript-Client-3178C6?logo=typescript&amp;logoColor=white" alt="TypeScript client" /></a>
  <a href="python/main.py" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Python-Client-3776AB?logo=python&amp;logoColor=white" alt="Python client" /></a>
</p>

<!-- Link the walkthrough and the commands for running the example. -->
<p>
  <a href="guides/openrouter-sandboxes.md" target="_blank" rel="noopener noreferrer"><strong>Guide</strong></a>
  · <a href="#quickstart">Quickstart</a>
</p>

</div>

The example fixes an invoice total (**125 → 375 cents**), restores saved files, adds shipping (**425 cents**), and checks the result. Choose a Python or TypeScript client; both run the generated Python code on Render.

## Quickstart

Requires Git, a macOS/Linux terminal, Node.js 22+ or Python 3.11+, <a href="https://render.com/docs/sandboxes#1-confirm-access" target="_blank" rel="noopener noreferrer">Render Sandbox access</a>, and <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">OpenRouter credits</a>. Render compute and model requests incur charges.

```shell
# Download the example and enter its folder.
git clone https://github.com/ojusave/openrouter-sandboxes.git
cd openrouter-sandboxes
# Create a settings file that only your user account can read or change.
cp .env.example .env
chmod 600 .env
```

Open `.env` in your editor. Fill in `RENDER_API_KEY`, `RENDER_WORKSPACE_ID`, and `OPENROUTER_API_KEY`. The keys authorize service requests; the workspace ID selects where sandboxes run. <a href="guides/openrouter-sandboxes.md#prerequisites" target="_blank" rel="noopener noreferrer">Find these values here.</a> Keep the file private.

```shell
# Share the settings loaded next with programs started from this terminal.
set -a
# Read the settings file you just edited.
. ./.env
# Stop automatically sharing any new settings defined later.
set +a
```

From this folder and terminal, choose **one** client:

<!-- Expand only the language you want to run; both complete the same task. -->
<details open>
<summary><strong>TypeScript</strong></summary>

```shell
# Enter the TypeScript folder, install its libraries, and run the example.
cd typescript
npm ci
npm run demo
```

</details>

<details>
<summary><strong>Python</strong></summary>

```shell
# Enter the Python folder and create a separate home for its local libraries.
cd python
python3 -m venv .venv
# Install the required libraries, then run the example with this Python setup.
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

</details>

## Expected result

A successful run ends with these checks (abbreviated from a real TypeScript run):

```text
followup_passed_independent_tests: true
cleanup_verified: true
```

Python prints `True` on the cleanup line. The earlier `initial_tests_fail: true` is expected: it confirms the starting bug.

The printed `Evidence:` folder contains `repaired.py`, the final `totals.py`, and `run.json` with test and cleanup results. The example removes its temporary Render resources after downloading the files.

<a href="guides/openrouter-sandboxes.md" target="_blank" rel="noopener noreferrer">Full walkthrough</a> · <a href="guides/openrouter-sandboxes.md#how-openrouter-sandbox-execution-works" target="_blank" rel="noopener noreferrer">How it works</a> · <a href="guides/openrouter-sandboxes.md#4-confirm-cleanup-or-recover-an-interrupted-run" target="_blank" rel="noopener noreferrer">Cleanup and recovery</a>
