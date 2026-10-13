<!-- Center the project introduction and its navigation, as in the other demo READMEs. -->
<div align="center">

# OpenRouter + Render Sandboxes

Let an AI model repair Python code on a temporary Render computer, then check and download the result.

<!-- Each badge names a component and links to its documentation or client folder. -->
<p>
  <a href="https://render.com/docs/sandboxes?utm_source=github&amp;utm_medium=referral&amp;utm_campaign=ojus_demos&amp;utm_content=readme_badge" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Render-Sandboxes-6e40c9?logo=render&amp;logoColor=white" alt="Render Sandboxes" /></a>
  <a href="https://openrouter.ai/" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/OpenRouter-Models-555555?logo=openrouter&amp;logoColor=white" alt="OpenRouter Models" /></a>
  <a href="typescript/main.ts" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/TypeScript-Client-3178C6?logo=typescript&amp;logoColor=white" alt="TypeScript client" /></a>
  <a href="python/main.py" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/Python-Client-3776AB?logo=python&amp;logoColor=white" alt="Python client" /></a>
  <!-- GitHub supplies this badge's current status from the main branch's automated checks. -->
  <a href="https://github.com/ojusave/openrouter-sandboxes/actions/workflows/checks.yml" target="_blank" rel="noopener noreferrer"><img src="https://github.com/ojusave/openrouter-sandboxes/actions/workflows/checks.yml/badge.svg?branch=main" alt="Automated checks on main" /></a>
</p>

<!-- Offer a clear starting point, setup shortcut, and evidence link before the longer explanation. -->
<p>
  <a href="guides/openrouter-sandboxes.md" target="_blank" rel="noopener noreferrer"><strong>Read the beginner guide</strong></a>
  · <a href="#clone-and-configure-the-example">Run the example</a>
  · <a href="VALIDATION.md" target="_blank" rel="noopener noreferrer">Test results</a>
</p>

</div>

An AI model can write a code change, but you need to run the code to see whether it works. A **sandbox** gives it a separate place to run: a temporary environment where the example's files can be changed and tested, then copied out before that environment is discarded.

This example uses **OpenRouter** to reach an AI model and **Render Sandboxes** to run the generated Python code. The code runs on Render, separately from your computer. This is called **isolated code execution**. The sandbox is a real place to execute code; tests check whether that code gives the right answers.

You run this example in a **terminal**, the app where you type commands and read their output. A program on your computer, called the **client**, coordinates OpenRouter and Render. Choose either the TypeScript or Python client; both execute Python code inside Render. The example creates its temporary Render environments when you start it. There is no web interface to open.

## What you will see

1. **Reproduce a bug.** Three invoice items at 125 cents each should cost 375 cents. The starting code returns 125, so its test fails.
2. **Ask the model to fix it.** The model requests file reads, an edit, or test runs. These actions are called tools. The client checks each request and runs the allowed action in Render.
3. **Check the answer.** The client downloads the repair and runs seven tests in a fresh sandbox, using original tests and extra cases the model was not shown.
4. **Continue from saved files.** The client saves a copy of the sandbox's files, called a snapshot, and restores them into another sandbox. A new model task adds 50 cents shipping. The final total is 425 cents, and twelve independent tests check the result.
5. **Keep the result and clean up.** The client downloads both versions of the Python file, terminates the four sandboxes, and deletes the snapshot. The downloaded files remain on your computer.

![Where requests and code execute](docs/architecture.svg)

Your client keeps the account access keys on your computer. The sandbox receives neither key and has outgoing network connections disabled. The client sends sample file contents and test output back through OpenRouter to the model provider so the model can decide its next action.

## Prerequisites

- A <a href="https://render.com/docs/sandboxes" target="_blank" rel="noopener noreferrer">Render workspace with Sandboxes enabled</a>. This example requests the `starter` Sandbox plan.
- <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">OpenRouter access and model credits</a>. The tested model is `anthropic/claude-haiku-5.5`. You can set `OPENROUTER_MODEL` to another model that supports <a href="https://openrouter.ai/docs/guides/features/tool-calling" target="_blank" rel="noopener noreferrer">tool calling</a>.
- Node.js 22 or later for the TypeScript client, or Python 3.11 or later for the Python client.

API keys are secret values that let the client request work from each service. The workspace identifier chooses where Render creates resources. The full guide links to account setup and explains each value.

| Variable | Purpose and required access | Where it stays |
| --- | --- | --- |
| `RENDER_API_KEY` | <a href="https://render.com/docs/api#1-create-an-api-key" target="_blank" rel="noopener noreferrer">Render API key</a> belonging to a user with permission to create, inspect, terminate, and snapshot Sandboxes in the selected workspace. | Your client process |
| `RENDER_WORKSPACE_ID` | The `tea-...` ID from the workspace's Dashboard settings. It selects where resources are created; it is not a secret. | Your client process |
| `OPENROUTER_API_KEY` | An <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">OpenRouter API key</a> with permission and credits for model requests. | Your client process |

Render Sandboxes is in early access. This example uses Render's software development kit (SDK), a library for creating and managing sandboxes, and pins both language versions to 1.2.0. The Python client also pins HTTPX 0.28.1 for OpenRouter requests. See <a href="VALIDATION.md" target="_blank" rel="noopener noreferrer">the validation record</a> for exact tested versions and limits.

## Clone and configure the example

Clone this repository in a terminal, then enter its directory:

```shell
# Download the example into a new folder named openrouter-sandboxes.
git clone https://github.com/ojusave/openrouter-sandboxes.git
# Make that folder the location for the following commands.
cd openrouter-sandboxes
```

These setup commands use a macOS or Linux shell.

Create a private configuration file:

```shell
# Copy the settings template; add your own values to this new file next.
cp .env.example .env
# Allow only your computer's user account to read or change the file.
chmod 600 .env
```

In your editor, fill in the three required values in `.env`. This file is ignored by Git. Leave the model value as supplied for the tested path. The commands above print nothing when they succeed.

Load those settings into the current terminal. Only source the configuration file you just created and edited:

```shell
# Share settings loaded next with programs started by this terminal.
set -a
# Read the .env file you just created and edited.
. ./.env
# Stop automatically sharing any additional settings you define later.
set +a
```

Choose one client below. Each runs the complete example independently, so running both creates two sets of temporary resources and makes two sets of model calls.

<details open>
<summary><strong>TypeScript</strong></summary>

From the `openrouter-sandboxes` directory, install the pinned dependencies and run the client:

```shell
# Enter the TypeScript client's folder.
cd typescript
# Install the exact library versions recorded with the example.
npm ci
# Start the client, which contacts OpenRouter and creates Render sandboxes.
npm run demo
```

The implementation is in <a href="typescript/main.ts" target="_blank" rel="noopener noreferrer">`typescript/main.ts`</a>. `npm ci` installs the packages in the lockfile. `npm run demo` starts the local client, which calls OpenRouter and Render.

</details>

<details>
<summary><strong>Python</strong></summary>

From the `openrouter-sandboxes` directory, create a separate place for the required packages, install them, and run the client:

```shell
# Enter the Python client's folder.
cd python
# Create a local folder to hold this client's Python packages.
python3 -m venv .venv
# Install the library versions listed by the example into that folder.
.venv/bin/python -m pip install -r requirements.txt
# Start the client using that folder's Python program and libraries.
.venv/bin/python main.py
```

The implementation is in <a href="python/main.py" target="_blank" rel="noopener noreferrer">`python/main.py`</a>. The `.venv` directory is a Python virtual environment, which keeps this example's packages separate from your other projects.

</details>

A successful TypeScript run prints the following checkpoints. These lines come from a live run; generated directory names vary. Python prints `True` for the final cleanup line.

```text
initial_tests_fail: true
repair_passed_independent_tests: true
restored_files_match: true
followup_passed_independent_tests: true
cleanup_verified: true
```

**The first failure is expected:** `initial_tests_fail: true` confirms the starting invoice bug. The next checkpoints confirm the repair, restored files, shipping change, and cleanup.

The client first waits for Render to finish creating each sandbox. That wait means the computer is starting; it does not mean the model has finished the task. Model calls and snapshot capture may also take time between checkpoints.

## Inspect the result

Each run prints an `Evidence:` path under `.runs/`. That directory contains:

- `repaired.py`: the first repair downloaded from the sandbox.
- `totals.py`: the final program, including the shipping change.
- `run.json`: the requested model, actual models returned by OpenRouter, usage, test output, resource IDs, and confirmed cleanup state. It does not store API keys.

The repair passes seven tests in a fresh verification sandbox. The follow-up passes twelve. The model cannot edit the visible test files through its tools, and the fresh sandbox receives the original tests kept on your computer plus additional cases the model was not shown. These checks establish the sample's behavior; they are not a general proof that arbitrary generated code is trustworthy.

The client also compares the restored source byte for byte and checks a randomly generated marker file. This proves that project files survived after the original sandbox was terminated. A filesystem snapshot restores files into a new sandbox. It does not restore a model conversation or a running process.

## Cleanup and recovery

The client downloads the wanted files before terminating all four sandboxes and deleting its one filesystem snapshot. Cleanup runs after success and handled failures, and checks the provider's state rather than treating a successful request as proof of deletion. Termination discards the sandbox; snapshot deletion removes the saved restore point. Local downloaded files remain available.

Resources have a ten-minute sandbox lifetime and a one-hour snapshot expiry as additional limits. Do not wait for expiry when cleanup can be confirmed immediately.

If a run stops, read its `run.json`. From your chosen client directory, retry cleanup for that exact run:

| TypeScript | Python |
| --- | --- |
| `npm run demo -- cleanup --run-dir ../.runs/YOUR-RUN` | `.venv/bin/python main.py cleanup --run-dir ../.runs/YOUR-RUN` |

The same workspace configuration is required. Cleanup only acts on IDs recorded by that run. If `run.json` contains `pending_create` or `pending_snapshot`, the creation request had an unknown outcome. Inspect resources in Render using the recorded time or snapshot name before attempting another creation. The client reports this uncertainty instead of silently retrying and potentially creating duplicates.

## Run the checks

Offline checks exercise invalid tool requests, write limits, missing command exit events, excessive output, paginated cleanup, recovery after deletion, and rejection of a failed independent verification.

| TypeScript directory | Python directory |
| --- | --- |
| `npm run check` and `npm test` | `.venv/bin/python -m unittest discover -s ../tests -p 'test_*.py' -v` |

To test the actual execution limits and failure cleanup, run each mode from the same client directory:

| What is checked | TypeScript | Python |
| --- | --- | --- |
| Runtime/output limits, credentials absent, outbound request blocked or timed out with a successful host control | `npm run demo -- boundaries` | `.venv/bin/python main.py boundaries` |
| Cleanup after an intentionally failed run | `npm run demo -- fail-after-create` | `.venv/bin/python main.py fail-after-create` |
| Cleanup after a snapshot was captured | `npm run demo -- fail-after-snapshot` | `.venv/bin/python main.py fail-after-snapshot` |

The two `fail-` modes intentionally exit with an error. Success for these checks means the failure is recorded and `cleanup_verified` is true. The model is not called in these modes.

Test commands have a twelve-second execution limit and retain at most 16,384 bytes of output before stopping the child process group. File writes are limited to 16,384 UTF-8 bytes. Each model task is limited to ten responses and twenty-four tool calls. Remote command transport failures stop the run and trigger sandbox cleanup.

## Scope

This example lets your application control the model's actions and the temporary computers where code runs. It uses OpenRouter's tool-calling interface and Render's Sandbox SDKs. The existing <a href="https://openrouter.ai/docs/guides/community/render" target="_blank" rel="noopener noreferrer">Render Workflows guide on OpenRouter</a> covers the separate background-task pattern.
