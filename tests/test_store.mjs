import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Exercise the store without Alpine/DOM; browser rendering is tested separately.
const source = readFileSync(new URL('../webui/store.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace('export const store =', 'globalThis.store =');
const env = vm.createContext({createStore: (_, state) => state, getContext: () => 'chat-1'});
vm.runInContext(source, env);
const store = env.store;
const status = fingerprint => ({scope: {fingerprint, root: '/workspace', debug_targets: {}}, workspace: {diagnostics: [], debuggers: []}});
store.context = 'chat-1';
store.status = status('before');
store.path = 'old.py';
store.breakpointPath = 'old.py';
store.breakpointLines = '9';
store.queryResult = {items: ['old result']};
store.actions = [{action_id: 'old-action'}];
store.selectedFrame = 19;
store.variableHistory = [{reference: 7}];
store.request = async () => status('after');
await store.refresh(true);
assert.equal(store.path, '');
assert.equal(store.breakpointPath, '');
assert.equal(store.breakpointLines, '');
assert.equal(store.queryResult, null);
assert.equal(store.actions.length, 0);
assert.equal(store.selectedFrame, null);
assert.equal(store.variableHistory.length, 0);
store.path = 'keep.py';
await store.refresh(true);
assert.equal(store.path, 'keep.py');
env.getContext = () => 'chat-2';
await store.refresh(true);
assert.equal(store.path, '');
console.log('Store workspace changes clear old results and breakpoints; stable workspaces preserve inputs.');
