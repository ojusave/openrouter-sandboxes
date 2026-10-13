# Run OpenRouter code repairs in Render Sandboxes

An AI model can suggest a code change, but it needs a computer to run tests and check that the change works. This example connects OpenRouter, which supplies model responses, to Render Sandboxes, which provide temporary Linux computers for running code.

Your local TypeScript or Python client gives the model three actions: read a file, replace `totals.py`, and run the tests. Asking a model to choose one of these actions is called **tool calling**. The client checks each request and runs the action in Render.

Both clients repair the same Python program. An invoice line costs 125 cents and has a quantity of three, but the broken program returns **125 instead of 375**. After the repair, the client checks the code in a fresh sandbox, saves its files, restores them into another sandbox, and asks the model to add a shipping charge. The final example returns **425 cents**, including 50 cents for shipping.

![Where requests and code execute](docs/architecture.svg)

OpenRouter requests originate from your computer. The sandbox has outbound network access disabled and receives neither API key. The model gets file contents and bounded test output through the client. Both client languages execute Python code in the sandbox.

## Prerequisites

- A <a href="https://render.com/docs/sandboxes" target="_blank" rel="noopener noreferrer">Render workspace with Sandboxes enabled</a>. This example requests the `starter` Sandbox plan.
- <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">OpenRouter access and model credits</a>. The tested model is `anthropic/claude-haiku-5.5`. You can set `OPENROUTER_MODEL` to another model that supports <a href="https://openrouter.ai/docs/guides/features/tool-calling" target="_blank" rel="noopener noreferrer">tool calling</a>.
- Node.js 22 or later for the TypeScript client, or Python 3.11 or later for the Python client.

| Variable | Purpose and required access | Where it stays |
| --- | --- | --- |
| `RENDER_API_KEY` | <a href="https://render.com/docs/api#1-create-an-api-key" target="_blank" rel="noopener noreferrer">Render API key</a> belonging to a user with permission to create, inspect, terminate, and snapshot Sandboxes in the selected workspace. | Your client process |
| `RENDER_WORKSPACE_ID` | The `tea-...` ID from the workspace's Dashboard settings. It selects where resources are created; it is not a secret. | Your client process |
| `OPENROUTER_API_KEY` | An <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">OpenRouter API key</a> with permission and credits for model requests. | Your client process |

Render's Sandbox interfaces are experimental. This example pins both Render SDKs to version 1.2.0. The Python client also pins HTTPX 0.28.1 for OpenRouter requests. See <a href="VALIDATION.md" target="_blank" rel="noopener noreferrer">the validation record</a> for exact tested versions and limits.

## Clone and configure the example

Clone this repository in a terminal, then enter its directory:

```shell
git clone https://github.com/ojusave/openrouter-sandboxes.git
cd openrouter-sandboxes
```

These setup commands use a macOS or Linux shell.

Create a private configuration file:

```shell
cp .env.example .env
chmod 600 .env
```

In your editor, fill in the three required values in `.env`. This file is ignored by Git. Leave the model value as supplied for the tested path. The commands above print nothing when they succeed.

Load those settings into the current terminal. Only source the configuration file you just created and edited:

```shell
set -a
. ./.env
set +a
```

Choose one client below. Each runs the complete example independently, so running both creates two sets of temporary resources and makes two sets of model calls.

<details open>
<summary><strong>TypeScript</strong></summary>

From the `openrouter-sandboxes` directory, install the pinned dependencies and run the client:

```shell
cd typescript
npm ci
npm run demo
```

The implementation is in <a href="typescript/main.ts" target="_blank" rel="noopener noreferrer">`typescript/main.ts`</a>. `npm ci` installs the packages in the lockfile. `npm run demo` starts the local client, which calls OpenRouter and Render.

</details>

<details>
<summary><strong>Python</strong></summary>

From the `openrouter-sandboxes` directory, create a separate place for the required packages, install them, and run the client:

```shell
cd python
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
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

The client first waits for Render to finish creating each sandbox. That wait means the computer is starting; it does not mean the model has finished the task. Model calls and snapshot capture may also take time between checkpoints.

## Inspect the result

Each run prints an `Evidence:` path under `.runs/`. That directory contains:

- `repaired.py`: the first repair downloaded from the sandbox.
- `totals.py`: the final program, including the shipping change.
- `run.json`: the requested model, actual models returned by OpenRouter, usage, test output, resource IDs, and confirmed cleanup state. It does not store API keys.

The repair passes seven tests in a fresh verification sandbox. The follow-up passes twelve. The model cannot edit the visible test files through its tools, and the fresh verifier receives the host's original tests plus additional cases withheld from the model. These checks establish the sample's behavior; they are not a general proof that arbitrary generated code is trustworthy.

The client also compares the restored source byte for byte and checks a randomly generated marker file. This proves that project files survived after the original sandbox was terminated. A filesystem snapshot restores files into a new sandbox. It does not restore a model conversation or a running process.

## Cleanup and recovery

The client downloads the wanted files before terminating all four sandboxes and deleting its one filesystem snapshot. Cleanup runs after success and handled failures, and checks the provider's state rather than treating a successful request as proof of deletion. Termination discards the sandbox; snapshot deletion removes the saved restore point. Local downloaded files remain available.

Resources have a ten-minute sandbox lifetime and a one-hour snapshot expiry as additional limits. Do not wait for expiry when cleanup can be confirmed immediately.

If a run stops, read its `run.json`. From your chosen client directory, retry cleanup for that exact run:

| TypeScript | Python |
| --- | --- |
| `npm run demo -- cleanup --run-dir ../.runs/YOUR-RUN` | `.venv/bin/python main.py cleanup --run-dir ../.runs/YOUR-RUN` |

The same workspace configuration is required. Cleanup only acts on IDs recorded by that run. If the journal contains `pending_create` or `pending_snapshot`, the creation request had an unknown outcome. Inspect resources in Render using the recorded time or snapshot name before attempting another creation. The client reports this uncertainty instead of silently retrying and potentially creating duplicates.

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

This is a runnable application-owned integration example. It uses OpenRouter's existing client-tool interface and Render's Sandbox SDKs. It does not implement an OpenRouter Spawn provider, an interactive terminal, a public web app, or Render Workflows. The existing <a href="https://openrouter.ai/docs/guides/community/render" target="_blank" rel="noopener noreferrer">Render Workflows guide on OpenRouter</a> covers the separate background-task pattern.
