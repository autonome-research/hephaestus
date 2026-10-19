// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Explicit scratch contract shared by the native collector and its controls.
import { lstatSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { tmpdir } from 'node:os';
import process from 'node:process';

function directory(path) {
  if (!isAbsolute(path) || resolve(path) !== path) throw new Error('noncanonical browser path');
  for (let current = path; ; current = dirname(current)) {
    const info = lstatSync(current);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('browser path symlink/type');
    if (current === path && (info.uid !== process.getuid() || (info.mode & 0o077))) {
      throw new Error('browser path must be private and owned');
    }
    if (dirname(current) === current) break;
  }
  return path;
}

export function browserPaths(evidence) {
  const runtime = directory(join(evidence, 'runtime'));
  const home = directory(join(runtime, 'home'));
  const tmp = directory(join(runtime, 'tmp'));
  const artifacts = directory(join(runtime, 'artifacts'));
  // Playwright's temporary profile is created in the Node owner's os.tmpdir(),
  // not merely the env passed to Chrome. Both must agree before launch.
  if (process.env.HOME !== home || process.env.TMPDIR !== tmp || tmpdir() !== tmp) {
    throw new Error('browser HOME/TMPDIR must match fixture-owned paths');
  }
  return { home, tmp, artifacts, profile_parent: tmp };
}

export function launchOptions(paths) {
  return {
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true, host: '127.0.0.1', timeout: 30000,
    artifactsDir: paths.artifacts, downloadsPath: paths.artifacts,
    env: { PATH: '/usr/bin:/bin', LANG: 'C', LC_ALL: 'C', HOME: paths.home, TMPDIR: paths.tmp },
    args: ['--disable-background-networking', '--disable-component-update'],
  };
}

export function launchSettled(attempted, child) {
  return !attempted || (!!child && (child.exitCode !== null || child.signalCode !== null));
}

export function profilePath(child, paths) {
  const args = child.spawnargs.filter(arg => arg.startsWith('--user-data-dir='));
  if (args.length !== 1) throw new Error('missing/duplicate browser profile argument');
  const profile = directory(args[0].slice('--user-data-dir='.length));
  const childPath = relative(paths.profile_parent, profile);
  if (!childPath || childPath.startsWith('..' + sep) || childPath === '..' || isAbsolute(childPath)) {
    throw new Error('browser profile escaped fixture');
  }
  return profile;
}
