# OpenRouter + Render validation

Validated October 12, 2026, America/Los_Angeles (October 13 UTC). Both clients completed real OpenRouter model calls and Render Sandbox execution in a Sandbox-enabled Render workspace.

| Check | Python | TypeScript |
| --- | --- | --- |
| Broken fixture fails with 125 instead of 375 | Passed | Passed |
| Model edits the actual source and runs visible tests | Passed | Passed |
| Original tests plus withheld cases in a fresh sandbox | 7 passed | 7 passed |
| Snapshot captured, original terminated, files restored into a different sandbox | Passed, source and marker matched | Passed, source and marker matched |
| Model adds shipping after restore; fresh independent verification | 12 passed | 12 passed |
| Exception, runtime limit, output limit, credentials absent | Passed | Passed |
| Outbound HTTPS request with `deny-all` | Did not complete before the 12-second execution deadline | Did not complete before the 12-second execution deadline |
| Positive control for the same URL from the host | HTTP 200 | HTTP 200 |
| Cleanup after an intentional failure immediately after creation | Passed | Passed |
| Cleanup after an intentional failure after snapshot capture | Passed | Passed |
| Cleanup replayed with stale local flags after provider resources were already deleted | Passed | Passed |
| Local failure-focused tests | 9 passed | 11 passed |
| Static checks | Ruff passed; dependencies consistent | TypeScript compiler passed |

The fresh Python environment installed from the documented requirements and completed the whole example. TypeScript installed from its package configuration and compiled against the pinned SDK. A final TypeScript live run passed after the deadline setup fix described below.

## Tested versions and evidence

- Python 3.13.14 for the full test matrix, plus Python 3.14.3 in a fresh virtual environment for installation, nine local tests, and the complete live example.
- Node.js 24.18.0, TypeScript 6.0.3, tsx 4.23.15.
- Render Python `render==1.2.0`; TypeScript `@renderinc/sdk==1.2.0`.
- HTTPX 0.28.1 for Python OpenRouter requests; native `fetch` for TypeScript.
- OpenRouter model: `anthropic/claude-haiku-5.5`, confirmed in response metadata.
- Render plan requested: `starter`; region: Oregon; sandbox lifetime: 600 seconds; filesystem snapshot expiry: one hour.

<a href="docs/public-validation.json" target="_blank" rel="noopener noreferrer">Sanitized run evidence</a> contains actual model metadata, usage, tool events, test output, initial failed probes, and successful retries. Workspace, resource, and model-request IDs are omitted from the public copy. The strongest final end-to-end records are `python-clean-install` and `typescript-deadlines-final`. Boundary, failure, and recovery checks use the `*-final` records.

<a href="docs/source-manifest.json" target="_blank" rel="noopener noreferrer">Source hashes</a> identify the tested files. The runtime, fixture, and test files published here match those hashes; the GitHub setup instructions and workflow were added afterward.

The independently fetched <a href="docs/public-validation.json" target="_blank" rel="noopener noreferrer">provider-state audit summary</a> covers all 32 distinct sandboxes and eight snapshots created during development and testing, including diagnostic runs. Every owned sandbox was reported terminated, none appeared in the active list, and no owned snapshot remained listed. Cleanup replay records reuse IDs and do not create additional resources.

## Problems found and fixed

1. A cleanup retry originally tried to read a snapshot before deleting it. That failed when deletion had succeeded but the local journal had not been updated. Cleanup now attempts the idempotent deletion first, then confirms absence in paginated results. Both clients passed a real replay against already-deleted snapshots.
2. The first network probe expected a connection exception. Render's deny-all environment instead left the request waiting until the process deadline. The check now records that exact outcome, with a successful host request as a control. The initial failed probe was cleaned up and retained in the evidence.
3. The first TypeScript deadline wrapper was installed after constructing the SDK client. Inspection showed that the SDK captures its HTTP transport during construction. The wrapper now precedes construction. Tests prove that provider requests respect cancellation and deadlines while cleanup requests remain possible. A subsequent complete live run passed.
4. TypeScript initially treated the shared test file as CommonJS. Renaming it to `.mts` fixed the module boundary; the compiler and test runner both pass.

## Scope of the proof

The tests establish this fixture's behavior through OpenRouter's client-tool interface and Render's experimental Sandbox SDKs. They do not establish support for every OpenRouter model or provider, an official partner listing, production readiness, or an OpenRouter Spawn integration.

The recorded outbound request checks one HTTPS destination and the effective deny-all policy. It does not prove isolation against every networking bypass. The tool contract restricts the exposed file operations, while generated Python still executes inside the sandbox's operating-system environment.

Resource verification uses Render's reported state and paginated listings. It is not an independent inspection of the underlying host machines. A creation request that loses its response remains an explicit unknown outcome and requires reconciliation rather than automatic retry.

## Documentation checks

The local README preview was rendered at 1120px and 390px widths. The diagram is 276px wide, with no page overflow or overlapping labels. Both language sections open, and authored links use a new tab with `noopener noreferrer`. This is a local preview, not a deployed Render docs page. See <a href="docs/preview-checks.json" target="_blank" rel="noopener noreferrer">preview checks</a>.

## GitHub checks

The repository workflow runs the nine Python tests on Python 3.11 and 3.14 and the eleven TypeScript tests plus the compiler on Node.js 22 and 24. These checks require no API keys and create no cloud resources. Live validation remains separate because it needs Sandbox access and model credits.
