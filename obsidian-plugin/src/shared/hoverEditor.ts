import { App, Notice, TFile } from 'obsidian';

export function hoverEditorCommandId(): string {
  return 'obsidian-hover-editor:open-current-file-in-new-popover';
}

export function hasHoverEditorInstalled(app: App): boolean {
  try {
    const cmds = (app as any).commands?.commands as Record<string, any> | undefined;
    return Boolean(cmds && cmds[hoverEditorCommandId()]);
  } catch {
    return false;
  }
}

export async function openFileInHoverEditor(app: App, file: TFile): Promise<void> {
  const cmdId = hoverEditorCommandId();
  const commands: any = (app as any).commands;
  if (!commands?.executeCommandById) {
    new Notice('Cannot open in Hover Editor: command API unavailable.');
    return;
  }
  if (!hasHoverEditorInstalled(app)) {
    new Notice('Hover Editor plugin is not installed/enabled.');
    return;
  }

  const ws: any = app.workspace as any;
  const prevLeaf = ws.activeLeaf as any;
  const prevFile = app.workspace.getActiveFile();

  const tempLeaf = app.workspace.getLeaf(true);
  try {
    await tempLeaf.openFile(file);
    try {
      ws.setActiveLeaf?.(tempLeaf, false, true);
    } catch {
      // ignore
    }
    await commands.executeCommandById(cmdId);
  } finally {
    try {
      (tempLeaf as any)?.detach?.();
    } catch {
      // ignore
    }
    try {
      if (prevLeaf) ws.setActiveLeaf?.(prevLeaf, false, true);
    } catch {
      // ignore
    }
    if (prevFile) {
      try {
        const activeNow = app.workspace.getActiveFile();
        if (activeNow?.path !== prevFile.path && prevLeaf?.openFile) await prevLeaf.openFile(prevFile);
      } catch {
        // ignore
      }
    }
  }
}
