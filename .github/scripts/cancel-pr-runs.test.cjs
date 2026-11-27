const { test } = require('node:test');
const assert = require('node:assert/strict');
const cancel = require('./cancel-pr-runs.cjs');

const eligible = {
  id: 1, event: 'pull_request', path: '.github/workflows/ci.yml',
  head_branch: 'feature', head_repository: { full_name: 'writeitai/readlint-clients' },
  pull_requests: [], status: 'in_progress',
};
const context = {
  repo: { owner: 'writeitai', repo: 'readlint-clients' },
  payload: { pull_request: {
    number: 42, head: { ref: 'feature', repo: { full_name: 'writeitai/readlint-clients' } },
  } },
};

function harness(runs, cancelWorkflowRun = async () => {}, prContext = context) {
  const cancelled = [];
  const github = {
    paginate: async (method, args) => {
      assert.equal(args.workflow_id, 'ci.yml');
      assert.equal(args.event, 'pull_request');
      assert.equal(args.branch, prContext.payload.pull_request.head.ref);
      return runs;
    },
    rest: { actions: {
      listWorkflowRuns() {},
      cancelWorkflowRun: async (args) => {
        cancelled.push(args.run_id);
        await cancelWorkflowRun(args);
      },
      getWorkflowRun: async () => ({ data: { status: 'completed' } }),
    } },
  };
  return { github, context: prContext, core: { info() {} }, cancelled };
}

test('cancels only active CI runs for this PR, including queued runs', async () => {
  const h = harness([
    eligible, { ...eligible, id: 2, status: 'queued' },
    { ...eligible, id: 3, status: 'completed' },
    { ...eligible, id: 4, event: 'push', head_branch: 'main' },
    { ...eligible, id: 5, path: '.github/workflows/release.yml' },
    { ...eligible, id: 6, pull_requests: [{ number: 41 }] },
    { ...eligible, id: 7, head_repository: { full_name: 'fork/readlint-clients' } },
    { ...eligible, id: 8, head_branch: 'other' },
    { ...eligible, id: 9, head_branch: 'main' },
    { ...eligible, id: 10, event: 'workflow_dispatch' },
    { ...eligible, id: 11, pull_requests: [{ number: 42 }] },
  ]);
  await cancel(h);
  assert.deepEqual(h.cancelled, [1, 2, 11]);
});

test('accepts a completion race but propagates permissions and API errors', async () => {
  const h = harness([eligible], async () => { throw { status: 409 }; });
  await cancel(h);
  h.github.rest.actions.getWorkflowRun = async () => ({ data: { status: 'in_progress' } });
  await assert.rejects(cancel(h));
  const denied = harness([eligible], async () => { throw { status: 403 }; });
  await assert.rejects(cancel(denied));
});

// Fork authors commonly open PRs from main; these are PR checks, not main pushes.
test('cancels fork main PR checks without touching base main or another fork', async () => {
  const forkContext = { ...context, payload: { pull_request: {
    number: 42, head: { ref: 'main', repo: { full_name: 'fork/readlint-clients' } },
  } } };
  const h = harness([
    { ...eligible, id: 1, head_branch: 'main', head_repository: { full_name: 'fork/readlint-clients' } },
    { ...eligible, id: 2, head_branch: 'main', event: 'push' },
    { ...eligible, id: 3, head_branch: 'main' },
    { ...eligible, id: 4, head_branch: 'main', head_repository: { full_name: 'other/readlint-clients' } },
  ], undefined, forkContext);
  await cancel(h);
  assert.deepEqual(h.cancelled, [1]);
});
