// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import process from 'node:process';
import { browserPaths, launchOptions, launchSettled, profilePath } from './macos-browser-paths.mjs';

test('missing launch acknowledgement is not absence; terminal evidence is required', () => {
  assert.equal(launchSettled(false, undefined), true);
  assert.equal(launchSettled(true, undefined), false);
  assert.equal(launchSettled(true, { exitCode: null, signalCode: null }), false);
  assert.equal(launchSettled(true, { exitCode: 0, signalCode: null }), true);
  assert.equal(launchSettled(true, { exitCode: null, signalCode: 'SIGTERM' }), true);
});

// Serial: HOME/TMPDIR are process-global; no Chrome or application acceptance.
test('actual launch options confine HOME, temp, artifacts and temporary profile', () => {
  const root = mkdtempSync(join(realpathSync(tmpdir()), 'heph-browser-paths-'));
  const old = { HOME: process.env.HOME, TMPDIR: process.env.TMPDIR };
  try {
    for (const leaf of ['', '/home', '/tmp', '/artifacts']) {
      mkdirSync(join(root, 'runtime' + leaf), { mode: 0o700 });
    }
    process.env.HOME = join(root, 'runtime/home');
    process.env.TMPDIR = join(root, 'runtime/tmp');
    const paths = browserPaths(root);
    const options = launchOptions(paths);
    assert.deepEqual(options.env, {
      PATH: '/usr/bin:/bin', LANG: 'C', LC_ALL: 'C', HOME: paths.home, TMPDIR: paths.tmp,
    });
    assert.equal(options.artifactsDir, paths.artifacts);
    assert.equal(options.downloadsPath, paths.artifacts);
    const profile = mkdtempSync(join(paths.tmp, 'playwright_chromiumdev_profile-'));
    assert.equal(profilePath({ spawnargs: ['chrome', '--user-data-dir=' + profile] }, paths), profile);
    assert.throws(() => profilePath({ spawnargs: ['--user-data-dir=' + root] }, paths), /escaped/);
    assert.throws(() => profilePath({ spawnargs: [] }, paths), /missing/);
    symlinkSync(profile, join(paths.tmp, 'alias'));
    assert.throws(() => profilePath({ spawnargs: ['--user-data-dir=' + join(paths.tmp, 'alias')] }, paths), /symlink/);
    process.env.TMPDIR = root;
    assert.throws(() => browserPaths(root), /HOME\/TMPDIR/);
    process.env.TMPDIR = paths.tmp;
    rmSync(paths.artifacts, { recursive: true });
    symlinkSync(paths.tmp, paths.artifacts);
    assert.throws(() => browserPaths(root), /symlink/);
  } finally {
    for (const [key, value] of Object.entries(old)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    rmSync(root, { recursive: true, force: true });
  }
});
