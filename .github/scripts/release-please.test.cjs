// I think this only runs locally and manually, e.g. node --test .github/scripts/release-please.test.cjs, but it also requires installing the packages used below
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { test } = require('node:test');
const { Manifest, setLogger } = require('release-please');
const maintainReleasePR = require('./release-please.cjs');

const config = JSON.parse(fs.readFileSync('release-please-config.json', 'utf8'));
const repo = { owner: 'example', repo: 'app' };
const quiet = { info() { }, warn() { }, error() { }, debug() { } };
setLogger(quiet);

function harness(messages, version = '1.0.0') {
  const boundary = 'a'.repeat(40);
  const files = { '.release-please-manifest.json': JSON.stringify({ '.': version }) };
  const created = [];
  const merged = [{
    number: 10, merged_at: '2026-01-01',
    head: { ref: 'release-please--branches--master', repo: { full_name: 'example/app' } },
    labels: [{ name: 'autorelease: pending' }],
  }];
  const client = {
    repository: { ...repo, defaultBranch: 'master' },
    async getFileJson(path) {
      if (path === 'release-please-config.json') return config;
      return JSON.parse(files[path]);
    },
    async *releaseIterator() { },
    async *tagIterator() { },
    async *mergeCommitIterator() {
      for (const [index, message] of messages.entries()) {
        yield { sha: String(index + 1).repeat(40), message, files: ['src/app.py'] };
      }
      yield { sha: boundary, message: 'chore: previous release', files: [] };
      yield { sha: 'b'.repeat(40), message: 'feat!: old breaking change', files: [] };
    },
    async *pullRequestIterator(branch, state) {
      if (state === 'MERGED') yield* merged.map(pull => ({ ...pull, labels: pull.labels.map(label => label.name) }));
    },
    async createPullRequest(pull, branch, message, updates) {
      created.push(pull);
      for (const update of updates) {
        files[update.path] = update.updater.updateContent(files[update.path]);
      }
      return { ...pull, number: 11 };
    },
  };
  return {
    files, created,
    async run() {
      await maintainReleasePR({
        context: { repo }, core: quiet,
        exec: { async getExecOutput() { return { stdout: boundary + '\n' }; } },
        github: {
          rest: {
            pulls: { list() { } }, issues: {
              async removeLabel({ issue_number, name }) {
                assert.equal(issue_number, 10);
                merged[0].labels = merged[0].labels.filter(label => label.name !== name);
              },
            }
          },
          async paginate() { return merged; },
        },
      }, { Manifest, GitHub: { async create() { return client; } } });
    },
  };
}

for (const [message, expected] of [
  ['feat: new filters', '1.1.0'],
  ['fix: correct counts', '1.0.1'],
  ...['perf', 'refactor', 'build', 'ci', 'deps', 'revert', 'style'].map(type => [`${type}: update something`, '1.0.1']),
  ...['docs', 'test', 'chore', 'custom'].map(type => [`${type}: update something`, null]),
  ['feat!: replace filters', '2.0.0'],
  ['chore!: remove legacy support', '2.0.0'],
]) {
  test(message, async () => {
    const state = harness([message]);
    await state.run();
    assert.equal(state.created.length, expected ? 1 : 0);
    if (expected) {
      assert.equal(state.files['version.txt'].trim(), expected);
      assert.equal(JSON.parse(state.files['.release-please-manifest.json'])['.'], expected);
      assert.match(state.files['CHANGELOG.md'], new RegExp(expected.replaceAll('.', '\\.')));
    }
  });
}

test('a second PR-only release uses the merged manifest version', async () => {
  const state = harness(['fix: follow-up correction'], '1.1.0');
  await state.run();
  assert.equal(state.files['version.txt'].trim(), '1.1.1');
});

test('a feature and fix together use one minor bump and preserve manual notes', async () => {
  const state = harness(['fix: counts', 'feat: filters']);
  state.files['CHANGELOG.md'] = '# Changelog\n\n## 1.0.0\n\nManual note.\n';
  await state.run();
  assert.equal(state.files['version.txt'].trim(), '1.1.0');
  assert.match(state.files['CHANGELOG.md'], /Manual note\./);
});

test('release notes separate client changes from all technical changes', async () => {
  const state = harness([
    'feat: add client filters', 'fix: correct client counts',
    'style: improve client spacing', 'perf: speed up client searches',
    'chore: refresh tooling', 'refactor: simplify query helpers',
    'test: cover filter edge cases', 'docs: explain developer setup',
  ]);
  await state.run();
  assert.equal(state.files['version.txt'].trim(), '1.1.0');
  const notes = state.files['CHANGELOG.md'];
  const userFacing = notes.match(/### User-facing changes\n([\s\S]*?)(?=\n### |$)/)[1];
  const technical = notes.match(/### Technical changes \(clients can skip\)\n([\s\S]*?)(?=\n### |$)/)[1];
  for (const message of ['add client filters', 'correct client counts', 'improve client spacing', 'speed up client searches']) {
    assert.ok(userFacing.includes(message));
    assert.ok(!technical.includes(message));
  }
  for (const message of ['refresh tooling', 'simplify query helpers', 'cover filter edge cases', 'explain developer setup']) {
    assert.ok(technical.includes(message));
    assert.ok(!userFacing.includes(message));
  }
});

test('a batch of maintenance and custom commits waits for a release', async () => {
  const state = harness(['docs: setup', 'test: coverage', 'chore: tooling', 'custom: internal task']);
  await state.run();
  assert.equal(state.created.length, 0);
});
