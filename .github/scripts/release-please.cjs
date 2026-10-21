// PR-only releases need a commit boundary and must clear merged PRs' pending labels.
module.exports = async function maintainReleasePR({ github, context, exec, core }, { GitHub, Manifest, registerVersioningStrategy }) {
  registerVersioningStrategy('commit-types', () => ({
    determineReleaseType(version, commits) {
      const types = new Set(commits.map(commit => commit.type));
      return {
        bump(current) {
          const Version = current.constructor;
          if (types.has('feat') || types.has('style')) {
            return new Version(current.major + 1, 0, 0);
          }
          if (types.has('fix')) {
            return new Version(current.major, current.minor + 1, 0);
          }
          if ([...types].some(type => type !== 'chore')) {
            return new Version(current.major, current.minor, current.patch + 1);
          }
          return current;
        }
      };
    },
    bump(version, commits) {
      return this.determineReleaseType(version, commits).bump(version);
    },
  }));
  const { stdout } = await exec.getExecOutput('git', [
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
    { lastReleaseSha },
  );
  const sections = manifest.repositoryConfig['.'].changelogSections;
  manifest.plugins.push({
    async preconfigure(strategies) { return strategies; },
    processCommits(commits) {
      if (!commits.some(commit => commit.type !== 'chore')) return [];
      // Unknown conventional types also trigger patches and need visible notes.
      for (const commit of commits) {
        if (!sections.some(section => section.type === commit.type)) {
          sections.push({ type: commit.type, section: 'Tech-only changes' });
        }
      }
      return commits;
    },
    async run(pullRequests) { return pullRequests; },
  });
  await manifest.createPullRequests();
};
