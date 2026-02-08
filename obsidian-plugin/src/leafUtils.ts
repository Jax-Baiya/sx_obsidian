import { TFile, WorkspaceLeaf } from 'obsidian';
import type SxDbPlugin from './main';

export type OpenAfterPinSplitMode = 'new-tab' | 'replace';

function isLeafValid(leaf: WorkspaceLeaf | null | undefined): leaf is WorkspaceLeaf {
  if (!leaf) return false;
  try {
    const anyLeaf: any = leaf as any;
    if (!anyLeaf.parent) return false;
    const el: HTMLElement | null | undefined = anyLeaf?.view?.containerEl;
    if (el && el.isConnected === false) return false;
    return true;
  } catch {
    return false;
  }
}

function getStoredPinLeaf(plugin: SxDbPlugin): WorkspaceLeaf | null {
  return ((plugin as any)._sxdbPinSplitLeaf as WorkspaceLeaf | null) ?? null;
}

function setStoredPinLeaf(plugin: SxDbPlugin, leaf: WorkspaceLeaf | null): void {
  (plugin as any)._sxdbPinSplitLeaf = leaf;
}

/**
 * Open a pinned note in the preferred leaf.
 *
 * Goals:
 * - If split mode is enabled: create ONE split the first time, then keep reusing it.
 * - If split already exists: either replace current tab OR open a new tab within that split.
 */
export async function openPinnedFile(plugin: SxDbPlugin, file: TFile): Promise<void> {
  const ws: any = plugin.app.workspace as any;
  const mode = (plugin.settings as any).openAfterPinSplitMode as OpenAfterPinSplitMode | undefined;
  const splitMode: OpenAfterPinSplitMode = mode === 'replace' ? 'replace' : 'new-tab';

  if (!plugin.settings.openAfterPinSplit) {
    await plugin.app.workspace.getLeaf(true).openFile(file);
    return;
  }

  // Reuse existing dedicated split leaf if possible.
  let splitLeaf = getStoredPinLeaf(plugin);
  if (!isLeafValid(splitLeaf)) splitLeaf = null;

  if (!splitLeaf) {
    const created: WorkspaceLeaf | null = (ws.getLeaf?.('split') as WorkspaceLeaf | null) ?? null;
    splitLeaf = created ?? plugin.app.workspace.getLeaf(true);
    setStoredPinLeaf(plugin, splitLeaf);
  }

  if (splitLeaf && splitMode === 'replace') {
    await splitLeaf.openFile(file);
    return;
  }

  // new-tab: try to create a new tab *within the same split pane*.
  const prevActive: WorkspaceLeaf | null = (plugin.app.workspace as any).activeLeaf ?? null;
  try {
    ws.setActiveLeaf?.(splitLeaf, false, true);
  } catch {
    // ignore
  }

  const tabLeaf: WorkspaceLeaf | null = (ws.getLeaf?.('tab') as WorkspaceLeaf | null) ?? null;
  if (tabLeaf) {
    await tabLeaf.openFile(file);
    // store the most-recent leaf in that split pane so subsequent opens keep landing there
    setStoredPinLeaf(plugin, tabLeaf);
  } else {
    await splitLeaf.openFile(file);
  }

  // Restore focus back to where the user was working.
  try {
    if (prevActive) ws.setActiveLeaf?.(prevActive, false, true);
  } catch {
    // ignore
  }
}
