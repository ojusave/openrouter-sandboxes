import { readFileSync, writeFileSync, mkdirSync, renameSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { resolve, join } from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { setTimeout as sleep } from 'node:timers/promises';
import { Render } from '@renderinc/sdk';

const ROOT = fileURLToPath(new URL('../', import.meta.url));
const SHARED = join(ROOT, 'shared');
const fixture = (name: string) => readFileSync(join(SHARED, name), 'utf8');
const contract = JSON.parse(fixture('contract.json'));
const remote = Buffer.from(fixture('remote.py')).toString('base64');
export class IntegrationError extends Error { override name = 'IntegrationError'; }
type API = Render['experimental']['sandboxes'];
type Payload = { op: string; [key: string]: unknown };
type Result = { content?: string; exit_code?: number; stdout?: string; stderr?: string; limit?: string | null; error?: string; credentials_absent?: boolean };
type SandboxRecord = { id: string; terminated: boolean; final_status?: string };
type SnapshotRecord = { id: string; group: string; deleted: boolean };
interface State {
  language: string; started_at: string; model: string; workspace?: string;
  sandboxes: SandboxRecord[]; snapshots: SnapshotRecord[];
  checks: Record<string, unknown>; calls: Record<string, unknown>[];
  tool_events: Record<string, unknown>[]; complete: boolean;
  pending_create?: string; pending_snapshot?: { source: string; name: string };
  cleanup_verified?: boolean; cleanup_errors?: string[]; failure_type?: string; failure_reason?: string; boundary_results?: Record<string, Result>; source_sha256?: string;
}

export function validateTool(name: string, args: unknown): Payload {
  if (!args || typeof args !== 'object' || Array.isArray(args)) throw new IntegrationError('Tool arguments must be an object');
  const a = args as Record<string, unknown>;
  const keys = Object.keys(a).sort().join(',');
  if (name === 'read_file' && keys === 'path' && typeof a.path === 'string' && ['totals.py', 'test_totals.py', 'test_followup.py'].includes(String(a.path)))
    return { op: 'read', ...a };
  if (name === 'write_file' && keys === 'content,path' && a.path === 'totals.py' && typeof a.content === 'string' && Buffer.byteLength(a.content) <= contract.max_file_bytes)
    return { op: 'write', ...a };
  if (name === 'run_tests' && keys === '') return { op: 'tests' };
  throw new IntegrationError('Unsupported action, path, arguments, or file size');
}

const quote = (s: string) => "'" + s.replaceAll("'", "'\\''") + "'";

export class Run {
  state: State;
  constructor(public api: API, public output: string, model: string) {
    mkdirSync(output, { recursive: false });
    this.state = { language: 'typescript', started_at: new Date().toISOString(), model,
      sandboxes: [], snapshots: [], checks: {}, calls: [], tool_events: [], complete: false };
    this.save();
  }
  save() {
    writeFileSync(join(this.output, 'run.json.tmp'), JSON.stringify(this.state, null, 2) + '\n');
    renameSync(join(this.output, 'run.json.tmp'), join(this.output, 'run.json'));
  }
  check(name: string, value: unknown) {
    this.state.checks[name] = value; this.save();
    console.log(`${name}: ${JSON.stringify(value)}`);
    if (value === false) throw new IntegrationError('Check failed: ' + name);
  }
  async create(snapshotId?: string) {
    this.state.pending_create = new Date().toISOString(); this.save();
    let s = await this.api.create({ plan: 'starter', timeoutSeconds: 600,
      networkPolicy: { default: 'deny-all' }, ...(snapshotId ? { snapshotId } : {}) });
    this.state.sandboxes.push({ id: s.id, terminated: false });
    delete this.state.pending_create; this.save();
    for (let n = 0; n < 45; n++) {
      s = await this.api.get(s.id);
      if (s.status === 'running') {
        if (s.networkPolicy.default !== 'deny-all') throw new IntegrationError('Effective network policy differs from deny-all');
        return s.id;
      }
      if (!['creating', 'pending'].includes(s.status)) throw new IntegrationError('Sandbox failed during startup');
      await sleep(2000);
    }
    throw new IntegrationError('Sandbox readiness deadline exceeded');
  }
  async rpc(sid: string, payload: Payload): Promise<Result> {
    const encoded = Buffer.from(JSON.stringify(payload)).toString('base64');
    const command = ['python3', '-I', '-c', `import base64;exec(base64.b64decode('${remote}'))`, encoded].map(quote).join(' ');
    const chunks: Buffer[] = []; let size = 0; let exit: number | undefined;
    // Aborting a stream alone does not stop remote code. The caller's finally terminates the VM.
    for await (const event of await this.api.exec(sid, command, undefined, AbortSignal.timeout(30_000))) {
      if (event.type === 'output') {
        const chunk = Buffer.from(event.data); size += chunk.length;
        if (size > 131072) throw new IntegrationError('Remote response exceeded host output limit');
        chunks.push(chunk);
      } else exit = event.exit_code;
    }
    if (exit === undefined) throw new IntegrationError('Command stream ended without an exit code');
    if (exit !== 0) throw new IntegrationError('Sandbox helper failed');
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  }
  async setup(sid: string, files: Record<string, string>) { await this.rpc(sid, { op: 'setup', files }); }
  async terminate(record: SandboxRecord) {
    if (record.terminated) return;
    for (let attempt = 0; attempt < 3; attempt++) {
      try { await this.api.terminate(record.id); } catch { /* Confirm state even if the response was lost. */ }
      let cursor: string | undefined;
      for (let page = 0; page < 100; page++) {
        const rows = await this.api.list({ limit: 100, ...(cursor ? { cursor } : {}) });
        const found = rows.find(r => r.sandbox.id === record.id)?.sandbox;
        if (found && (found.status === 'terminated' || found.terminatedAt)) {
          record.terminated = true; record.final_status = found.status; this.save(); return;
        }
        const next = rows.at(-1)?.cursor;
        if (!rows.length || !next) break;
        if (next === cursor) throw new IntegrationError('Sandbox pagination did not advance');
        cursor = next;
      }
      await sleep(2000 * (attempt + 1));
    }
    throw new IntegrationError('Cleanup unconfirmed for ' + record.id);
  }
  async waitSnapshot(record: SnapshotRecord) {
    for (let n = 0; n < 45; n++) {
      const s = await this.api.snapshots.get({ sandboxGroupId: record.group, snapshotId: record.id });
      if (s.status !== 'creating') {
        if (s.status === 'failed') throw new IntegrationError('Snapshot capture failed');
        return;
      }
      await sleep(2000);
    }
    throw new IntegrationError('Snapshot readiness deadline exceeded');
  }
  async snapshot(sid: string) {
    const name = 'openrouter-' + this.output.split('/').at(-1);
    this.state.pending_snapshot = { source: sid, name }; this.save();
    const s = await this.api.snapshots.create({ sandboxId: sid, kind: 'filesystem', name,
      expiresAt: new Date(Date.now() + 3600_000).toISOString() });
    const record = { id: s.id, group: s.sandboxGroupId, deleted: false };
    this.state.snapshots.push(record); delete this.state.pending_snapshot; this.save();
    await this.waitSnapshot(record); return s.id;
  }
  async cleanup() {
    const errors: string[] = [];
    for (const r of this.state.sandboxes) {
      try { await this.terminate(r); } catch { errors.push(r.id + ': termination unconfirmed'); }
    }
    for (const r of this.state.snapshots) {
      if (r.deleted) continue;
      try {
        // Delete first so a resumed cleanup handles already-deleted snapshots too.
        try { await this.api.snapshots.delete({ sandboxGroupId: r.group, snapshotId: r.id }); }
        catch {
          try { await this.waitSnapshot(r); } catch (e) { if (!(e instanceof Error) || e.message !== 'Snapshot capture failed') throw e; }
          await this.api.snapshots.delete({ sandboxGroupId: r.group, snapshotId: r.id });
        }
        let cursor: string | undefined;
        for (let page = 0; page < 100; page++) {
          const rows = await this.api.snapshots.list({ sandboxGroupId: r.group, limit: 100, ...(cursor ? { cursor } : {}) });
          if (rows.some(row => row.snapshot.id === r.id)) throw new IntegrationError('Deleted snapshot remains listed');
          const next = rows.at(-1)?.cursor;
          if (!rows.length || !next) { r.deleted = true; break; }
          if (next === cursor) throw new IntegrationError('Snapshot pagination did not advance');
          cursor = next;
        }
        if (!r.deleted) throw new IntegrationError('Snapshot pagination budget exceeded');
        this.save();
      } catch { errors.push(r.id + ': snapshot deletion unconfirmed'); }
    }
    if (this.state.pending_create || this.state.pending_snapshot) errors.push('Unknown creation outcome: inspect provider resources before retrying');
    this.state.cleanup_errors = errors; this.state.cleanup_verified = !errors.length; this.save();
    if (errors.length) throw new IntegrationError('Cleanup remains unconfirmed; inspect run.json');
  }
  async agent(sid: string, followup = false) {
    const messages: Record<string, unknown>[] = [{ role: 'system', content: contract.system },
      { role: 'user', content: followup ? contract.followup : contract.initial }];
    let count = 0;
    for (let turn = 0; turn < contract.max_turns; turn++) {
      const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {
        method: 'POST', signal: AbortSignal.timeout(60_000),
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + process.env.OPENROUTER_API_KEY,
          'X-OpenRouter-Title': 'Render Sandbox repair example' },
        body: JSON.stringify({ model: this.state.model, messages, tools: contract.tools, max_tokens: 2048,
          provider: { require_parameters: true } }),
      });
      if (!response.ok) throw new IntegrationError('OpenRouter returned HTTP ' + response.status);
      const body = await response.json();
      if (body.error || !body.choices?.length) throw new IntegrationError('OpenRouter did not return a completion');
      const choice = body.choices[0]; const message = choice.message;
      this.state.calls.push({ model: body.model, id: body.id, usage: body.usage, followup }); this.save();
      // Keep provider reasoning_details intact when returning tool results.
      messages.push(message);
      if (!message.tool_calls?.length) {
        if (choice.finish_reason !== 'stop') throw new IntegrationError('Model stopped before completing its turn');
        return;
      }
      for (const call of message.tool_calls) {
        if (++count > contract.max_tool_calls) throw new IntegrationError('Tool call budget exceeded');
        let payload: Payload | undefined; let result: Result;
        try { payload = validateTool(call.function.name, JSON.parse(call.function.arguments)); }
        catch { /* Invalid model requests are recoverable, transport failures are not. */ }
        if (payload) {
          if (payload.op === 'tests') payload.names = ['test_totals', ...(followup ? ['test_followup'] : [])];
          result = await this.rpc(sid, payload);
        } else result = { error: 'Invalid tool request. Use only the listed actions and files.' };
        messages.push({ role: 'tool', tool_call_id: call.id, content: JSON.stringify(result) });
        this.state.tool_events.push({ name: call.function.name, followup, exit_code: result.exit_code ?? null, error: result.error ?? null }); this.save();
      }
    }
    throw new IntegrationError('Model turn budget exceeded');
  }
  async verify(source: string, followup = false) {
    const sid = await this.create();
    const names = ['test_totals', 'test_acceptance', ...(followup ? ['test_followup', 'test_shipping_acceptance'] : [])];
    await this.setup(sid, { 'totals.py': source, ...Object.fromEntries(names.map(n => [n + '.py', fixture(n + '.py')])) });
    const result = await this.rpc(sid, { op: 'tests', names });
    this.state.checks[followup ? 'followup_verification' : 'repair_verification'] = result; this.save();
    if (result.exit_code !== 0) throw new IntegrationError('Independent tests failed');
    await this.terminate(this.state.sandboxes.find(r => r.id === sid)!);
  }
  async demo() {
    const sid = await this.create(); const marker = randomUUID();
    await this.setup(sid, { 'totals.py': fixture('totals.py'), 'test_totals.py': fixture('test_totals.py'), 'restore-marker.txt': marker });
    const before = await this.rpc(sid, { op: 'tests', names: ['test_totals'] });
    this.check('initial_tests_fail', before.exit_code !== 0 && before.stderr?.includes('AssertionError: 125 != 375'));
    await this.agent(sid);
    const source = (await this.rpc(sid, { op: 'read', path: 'totals.py' })).content!;
    writeFileSync(join(this.output, 'repaired.py'), source);
    await this.verify(source); this.check('repair_passed_independent_tests', true);
    const snapshot = await this.snapshot(sid);
    await this.terminate(this.state.sandboxes.find(r => r.id === sid)!);
    const restored = await this.create(snapshot);
    const saved = (await this.rpc(restored, { op: 'read', path: 'totals.py' })).content;
    const savedMarker = (await this.rpc(restored, { op: 'read', path: 'restore-marker.txt' })).content;
    this.check('restored_files_match', saved === source && savedMarker === marker && restored !== sid);
    await this.setup(restored, { 'test_followup.py': fixture('test_followup.py') });
    await this.agent(restored, true);
    const final = (await this.rpc(restored, { op: 'read', path: 'totals.py' })).content!;
    writeFileSync(join(this.output, 'totals.py'), final);
    await this.verify(final, true); this.check('followup_passed_independent_tests', true);
    this.state.source_sha256 = createHash('sha256').update(final).digest('hex');
  }
  async boundaries() {
    const control = await fetch('https://example.com', { signal: AbortSignal.timeout(10_000) });
    this.check('network_host_control', control.status === 200);
    const sid = await this.create();
    const environment = await this.rpc(sid, { op: 'environment' });
    this.check('sandbox_credentials_absent', environment.credentials_absent);
    const probes: [string, string, (r: Result) => boolean][] = [
      ['exception_is_failure', 'raise RuntimeError("intentional")', r => r.exit_code !== 0 && r.limit === null],
      ['timeout_enforced', 'import time; time.sleep(60)', r => r.exit_code === 124 && r.limit === 'timeout'],
      ['output_bounded', 'print("x"*100000)', r => r.exit_code === 125 && Buffer.byteLength((r.stdout ?? '') + (r.stderr ?? '')) <= 16384],
      ['credentials_absent', 'import os; assert not any(os.environ.get(k) for k in ["RENDER_API_KEY","OPENROUTER_API_KEY"])', r => r.exit_code === 0],
      ['network_request_blocked_or_timed_out', 'import urllib.request\nprint("network_attempt_started",flush=True)\ntry:\n urllib.request.urlopen("https://example.com",timeout=3)\nexcept urllib.error.HTTPError:\n raise\nexcept (urllib.error.URLError, TimeoutError):\n print("network_blocked",flush=True)\nelse:\n raise AssertionError("network reached")', r => (r.exit_code === 0 && r.stdout?.includes('network_blocked') === true) || (r.exit_code === 124 && r.stdout?.includes('network_attempt_started') === true)],
    ];
    for (const [name, code, accept] of probes) {
      await this.setup(sid, { 'test_probe.py': code });
      const result = await this.rpc(sid, { op: 'tests', names: ['test_probe'] });
      this.state.boundary_results ??= {}; this.state.boundary_results[name] = result; this.save();
      this.check(name, accept(result));
    }
  }
}

// Install before constructing Render: its HTTP client captures fetch at construction.
export function connectRender(overall: AbortSignal, isCleanup: () => boolean,
  requestTimeoutMs = 45_000, options?: ConstructorParameters<typeof Render>[0]) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (input, init) => {
    const existing = init?.signal ?? (input instanceof Request ? input.signal : undefined);
    return originalFetch(input, { ...init, signal: AbortSignal.any([
      AbortSignal.timeout(requestTimeoutMs), ...(existing ? [existing] : []), ...(!isCleanup() ? [overall] : []),
    ]) });
  };
  try {
    return { api: new Render(options).experimental.sandboxes, restore: () => { globalThis.fetch = originalFetch; } };
  } catch (error) { globalThis.fetch = originalFetch; throw error; }
}

async function main() {
  const mode = process.argv[2] ?? 'demo';
  if (mode === '--help') { console.log('main.ts [demo|boundaries|fail-after-create|fail-after-snapshot|cleanup] [--run-dir PATH]'); return; }
  if (!['demo', 'boundaries', 'fail-after-create', 'fail-after-snapshot', 'cleanup'].includes(mode)) throw new IntegrationError('Unknown mode');
  for (const key of ['RENDER_API_KEY', 'RENDER_WORKSPACE_ID', ...(mode === 'demo' ? ['OPENROUTER_API_KEY'] : [])])
    if (!process.env[key]) throw new IntegrationError('Missing ' + key);
  if (process.env.RENDER_USE_LOCAL_DEV || process.env.RENDER_LOCAL_DEV_URL) throw new IntegrationError('Unset Render local development overrides');
  const dirArg = process.argv.indexOf('--run-dir');
  const output = dirArg >= 0 ? resolve(process.argv[dirArg + 1]!) : join(ROOT, '.runs', 'typescript-' + randomUUID().slice(0, 12));
  let cleanup = mode === 'cleanup';
  const controller = new AbortController();
  const onSignal = () => controller.abort(new IntegrationError('Interrupted'));
  process.on('SIGINT', onSignal); process.on('SIGTERM', onSignal);
  const overall = AbortSignal.any([controller.signal, AbortSignal.timeout(480_000)]);
  const connection = connectRender(overall, () => cleanup);
  const api = connection.api;
  let run: Run;
  try {
    if (mode === 'cleanup') {
      if (dirArg < 0) throw new IntegrationError('cleanup requires --run-dir');
      run = Object.create(Run.prototype) as Run;
      run.api = api; run.output = output; run.state = JSON.parse(readFileSync(join(output, 'run.json'), 'utf8'));
      if (run.state.workspace !== process.env.RENDER_WORKSPACE_ID) throw new IntegrationError('Cleanup workspace does not match run.json');
      await run.cleanup(); return;
    }
    mkdirSync(join(ROOT, '.runs'), { recursive: true });
    run = new Run(api, output, process.env.OPENROUTER_MODEL ?? contract.model);
    run.state.workspace = process.env.RENDER_WORKSPACE_ID; run.save();
    console.log('Run journal: ' + join(output, 'run.json'));
    try {
      if (mode === 'demo') await run.demo();
      else if (mode === 'boundaries') await run.boundaries();
      else { const sid = await run.create(); if (mode === 'fail-after-snapshot') await run.snapshot(sid); throw new IntegrationError('Intentional failure for cleanup verification'); }
      run.state.complete = true;
    } catch (e) {
      run.state.failure_type = e instanceof Error ? e.name : 'UnknownError'; if (e instanceof IntegrationError) run.state.failure_reason = e.message; run.save(); throw e;
    } finally {
      cleanup = true;
      await run.cleanup();
      console.log('cleanup_verified: ' + run.state.cleanup_verified);
      console.log('Evidence: ' + join(output, 'run.json'));
    }
  } finally {
    connection.restore();
    process.off('SIGINT', onSignal); process.off('SIGTERM', onSignal);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { console.error('Run stopped: ' + (error instanceof IntegrationError ? error.message : error.name) + '. See run.json for cleanup state.'); process.exitCode = 1; });
}
