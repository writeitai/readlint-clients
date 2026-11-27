// Only the PR check workflow is eligible, never release.yml.
module.exports = async ({ github, context, core }) => {
  const pr = context.payload.pull_request;
  const repo = context.repo;
  const runs = await github.paginate(github.rest.actions.listWorkflowRuns, {
    ...repo,
    workflow_id: 'ci.yml',
    event: 'pull_request',
    branch: pr.head.ref,
    per_page: 100,
  });
  // Collect all pages before cancelling: cancellation must not shift pagination.
  for (const run of runs) {
    if (run.event !== 'pull_request' || run.path !== '.github/workflows/ci.yml'
        || run.head_branch !== pr.head.ref
        || (run.head_branch === 'main'
            && run.head_repository?.full_name === `${repo.owner}/${repo.repo}`)
        || run.head_repository?.full_name !== pr.head.repo.full_name
        // GitHub omits closed PRs from this list. Reject a different open PR
        // on a reused branch, but accept the empty list returned after closing.
        || run.pull_requests.some(({ number }) => number !== pr.number)
        || run.status === 'completed') continue;
    try {
      await github.rest.actions.cancelWorkflowRun({ ...repo, run_id: run.id });
      core.info(`Cancelled PR #${pr.number} CI run ${run.id}`);
    } catch (error) {
      // A run can finish between listing and cancellation. Do not hide failures.
      if (error.status !== 409) throw error;
      const { data } = await github.rest.actions.getWorkflowRun({ ...repo, run_id: run.id });
      if (data.status !== 'completed') throw error;
      core.info(`CI run ${run.id} already completed`);
    }
  }
};
