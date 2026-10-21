// PR-only releases need a commit boundary and must clear merged PRs' pending labels.
module.exports = async function maintainReleasePR({github, context, exec, core}, {GitHub, Manifest}) {
  const {stdout} = await exec.getExecOutput('git', [
    'log', '-1', '--format=%H', 'HEAD', '--', '.release-please-manifest.json',
  ]);
  const lastReleaseSha = stdout.trim();
  if (!/^[a-f0-9]{40}$/.test(lastReleaseSha)) {
    throw new Error('Cannot find the version manifest commit boundary.');
  }
  core.info(`Considering commits after ${lastReleaseSha}`);

  const pulls = await github.paginate(github.rest.pulls.list, {
    ...context.repo,
    state: 'closed',
    base: 'master',
    sort: 'updated',
    direction: 'desc',
    per_page: 100,
  });
  for (const pull of pulls) {
    if (pull.merged_at &&
        pull.head.repo?.full_name === `${context.repo.owner}/${context.repo.repo}` &&
        pull.head.ref === 'release-please--branches--master' &&
        pull.labels.some(label => label.name === 'autorelease: pending')) {
      await github.rest.issues.removeLabel({
        ...context.repo,
        issue_number: pull.number,
        name: 'autorelease: pending',
      });
    }
  }

  const client = await GitHub.create({
    ...context.repo,
    token: process.env.RELEASE_PLEASE_TOKEN,
  });
  const manifest = await Manifest.fromManifest(
    client, 'master', 'release-please-config.json', '.release-please-manifest.json',
    {lastReleaseSha},
  );
  // Visible maintenance notes must not turn docs/test/chore-only batches into releases.
  const noBumpTypes = new Set(['docs', 'test', 'chore']);
  const releaseTypes = new Set(
    manifest.repositoryConfig['.'].changelogSections
      .filter(section => !section.hidden && !noBumpTypes.has(section.type))
      .map(section => section.type),
  );
  manifest.plugins.push({
    async preconfigure(strategies) {return strategies;},
    processCommits(commits) {
      const needsRelease = commits.some(commit =>
        commit.breaking || releaseTypes.has(commit.type) ||
        commit.notes.some(note => note.title === 'RELEASE AS'),
      );
      if (needsRelease) return commits;
      return [];
    },
    async run(pullRequests) {return pullRequests;},
  });
  await manifest.createPullRequests();
};
