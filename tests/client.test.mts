import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { Run, validateTool, connectRender } from '../typescript/main.js';
const root = fileURLToPath(new URL('../', import.meta.url));
const fixture = (name: string) => readFileSync(join(root, 'shared', name), 'utf8');
function setup(t: test.TestContext, api: unknown) {
  mkdirSync(join(root, '.runs'), {recursive: true});
  const dir = mkdtempSync(join(root, '.runs', 'unit-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return new Run(api as Run['api'], join(dir, 'run'), 'test-model');
}
test('rejects unsafe paths, altered tests, extra arguments, and unknown actions', () => {
  for (const [name, args] of [
    ['write_file', { path: '../totals.py', content: '' }],
    ['write_file', { path: 'test_totals.py', content: '' }],
    ['read_file', { path: '/etc/passwd' }],
    ['read_file', { path: ['totals.py'] }],
    ['run_tests', { command: 'anything' }], ['shell', {}], ['run_tests', []],
  ] as [string, unknown][]) assert.throws(() => validateTool(name, args));
});
test('counts UTF-8 bytes when limiting writes', () => {
  assert.throws(() => validateTool('write_file', { path: 'totals.py', content: '€'.repeat(6000) }));
  assert.equal(validateTool('write_file', { path: 'totals.py', content: 'x'.repeat(16384) }).op, 'write');
});
test('termination follows pagination and accepts terminated timestamp', async t => {
  let calls = 0; let requested = '';
  const run = setup(t, { terminate: async (id: string) => { requested = id; }, list: async ({cursor}: {cursor?: string}) => {
    if (++calls === 1) return [{sandbox: {id:'other'},cursor:'p2'}];
    assert.equal(cursor,'p2'); return [{sandbox: {id:'sbx-owned',status:'errored',terminatedAt:'now'},cursor:'p3'}];
  }});
  const r = { id:'sbx-owned',terminated:false };
  await run.terminate(r); assert.equal(r.terminated,true); assert.equal(requested,'sbx-owned');
});
test('cleanup continues after failure and never claims success', async t => {
  const run = setup(t, {}); let calls = 0;
  run.state.sandboxes = ['first','second'].map(id => ({id,terminated:false}));
  run.terminate = async () => { if (++calls === 1) throw new Error('failure'); };
  await assert.rejects(run.cleanup()); assert.equal(calls,2); assert.equal(run.state.cleanup_verified,false);
});
test('snapshot cleanup can recover after deletion', async t => {
  const run = setup(t, {snapshots:{delete:async()=>{},list:async()=>[]}});
  run.state.snapshots=[{id:'snp-owned',group:'sbg-owned',deleted:false}];
  await run.cleanup(); assert.equal(run.state.snapshots[0].deleted,true);
});
test('unknown creation outcome cannot be reported clean', async t => {
  const run=setup(t,{});run.state.pending_create='known-start-time';
  await assert.rejects(run.cleanup());assert.equal(run.state.cleanup_verified,false);
});
test('missing exit event is not success',async t=>{
  const run=setup(t,{exec:async function*(){yield {type:'output',data:'{}'};}});
  await assert.rejects(run.rpc('sbx-owned',{op:'environment'}),/without an exit/);
});
test('stream output is bounded',async t=>{
  const run=setup(t,{exec:async function*(){yield {type:'output',data:'x'.repeat(131073)};}});
  await assert.rejects(run.rpc('sbx-owned',{op:'environment'}),/output limit/);
});
test('model success cannot bypass fresh independent verification',async t=>{
  const run=setup(t,{});run.create=async()=> 'sbx-verifier';
  run.setup=async(_sid,files)=>{assert.equal(files['test_totals.py'],fixture('test_totals.py'));assert.ok(files['test_acceptance.py']);};
  run.rpc=async()=>({exit_code:1});
  await assert.rejects(run.verify('broken source'),/Independent tests failed/);
});

test('SDK control requests honor cancellation while cleanup retains access', async t => {
  const original = globalThis.fetch;
  const controller = new AbortController();
  let cleanup = false;
  globalThis.fetch = async (_input, init) => {
    if (init?.signal?.aborted) throw init.signal.reason;
    return new Response('[]', {status:200,headers:{'Content-Type':'application/json'}});
  };
  const connection = connectRender(controller.signal, () => cleanup, 1000, {token:'test',ownerId:'tea-test'});
  t.after(() => {connection.restore();globalThis.fetch=original;});
  controller.abort(new Error('cancelled'));
  await assert.rejects(connection.api.list(), /cancelled/);
  cleanup = true;
  assert.deepEqual(await connection.api.list(), []);
});
test('SDK control requests have a deadline even when the provider hangs', async t => {
  const original = globalThis.fetch;
  globalThis.fetch = (_input, init) => new Promise((_resolve,reject) => {
    init?.signal?.addEventListener('abort', () => reject(init.signal!.reason), {once:true});
  });
  const connection = connectRender(new AbortController().signal, () => false, 20, {token:'test',ownerId:'tea-test'});
  const keepAlive = setTimeout(() => {}, 1000);
  t.after(() => {clearTimeout(keepAlive);connection.restore();globalThis.fetch=original;});
  await assert.rejects(connection.api.list(), /timeout/i);
});
