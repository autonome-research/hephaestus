// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { DEFAULT_STATE } from '../src/state/workspace';
import { workspaceStore } from '../src/state/react';
import type * as QueryApi from '../src/api/queries';

vi.mock('../src/api/queries', async (original) => ({
  ...await original<typeof QueryApi>(),
  useBuild: () => ({ data: { artifact_ref: 'current-server-ref' } }),
}));
import { CurrentBuildObserver } from '../src/App';

it('re-adopts a cached current after same-part URL reset, never a held pin', () => {
  const host = document.createElement('div');
  const root = createRoot(host);
  try {
    workspaceStore.reset({ ...DEFAULT_STATE, part: 'two_solids' });
    act(() => { root.render(<CurrentBuildObserver />); });
    expect(workspaceStore.getSnapshot().artifact_ref).toBe('current-server-ref');
    act(() => { workspaceStore.reset({ ...DEFAULT_STATE, part: 'two_solids', view: '+Z' }); });
    expect(workspaceStore.getSnapshot().artifact_ref).toBe('current-server-ref');
    act(() => { workspaceStore.hold('held-immutable-ref'); });
    expect(workspaceStore.getSnapshot().artifact_ref).toBe('held-immutable-ref');
    act(() => { workspaceStore.reset({ ...DEFAULT_STATE, part: 'two_solids', pin_mode: 'pinned', artifact_ref: 'another-held-ref' }); });
    expect(workspaceStore.getSnapshot().artifact_ref).toBe('another-held-ref');
  } finally {
    act(() => { root.unmount(); });
    workspaceStore.reset(DEFAULT_STATE);
  }
});
