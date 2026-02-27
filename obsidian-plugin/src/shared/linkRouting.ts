import type { App } from 'obsidian';

function openExternalUrl(url: string): boolean {
  const raw = String(url || '').trim();
  if (!raw) return false;
  try {
    const electron = (window as any).require?.('electron');
    if (electron?.shell?.openExternal) {
      void electron.shell.openExternal(raw);
      return true;
    }
  } catch {
    // ignore
  }
  return false;
}

function normalizeProtocolPathForHost(rawPath: string): string {
  let p = String(rawPath || '').trim();
  if (!p) return '';

  try {
    p = decodeURIComponent(p);
  } catch {
    // keep raw path
  }

  p = p.replace(/^\/\//, '');

  const isWin = String((globalThis as any)?.process?.platform || '').toLowerCase() === 'win32';
  if (!isWin) return p;

  const m = p.match(/^\/mnt\/([a-zA-Z])\/(.*)$/);
  if (m) {
    const drive = String(m[1] || '').toUpperCase();
    const tail = String(m[2] || '').replace(/\//g, '\\');
    return tail ? `${drive}:\\${tail}` : `${drive}:\\`;
  }

  return p;
}

function openProtocolDirectly(url: string): boolean {
  const raw = String(url || '').trim();
  const m = raw.match(/^(sxopen|sxreveal):(.*)$/i);
  if (!m) return false;

  const protocol = String(m[1] || '').toLowerCase();
  const targetPath = normalizeProtocolPathForHost(String(m[2] || ''));
  if (!targetPath) return false;

  try {
    const electron = (window as any).require?.('electron');
    const shell = electron?.shell;
    if (!shell) return false;

    if (protocol === 'sxreveal' && typeof shell.showItemInFolder === 'function') {
      shell.showItemInFolder(targetPath);
      return true;
    }

    if (protocol === 'sxopen' && typeof shell.openPath === 'function') {
      void shell.openPath(targetPath);
      return true;
    }
  } catch {
    // ignore
  }

  return false;
}

export function openProtocolOrUrl(app: App, link: string): void {
  const raw = String(link || '').trim();
  if (!raw) return;

  if (/^(sxopen|sxreveal):/i.test(raw)) {
    try {
      if (openProtocolDirectly(raw)) return;
      if (!openExternalUrl(raw)) window.open(raw);
    } catch {
      window.open(raw);
    }
    return;
  }

  if (/^https?:\/\//i.test(raw)) {
    try {
      if (!openExternalUrl(raw)) window.open(raw);
    } catch {
      window.open(raw);
    }
    return;
  }

  try {
    (app as any).openWithDefaultApp?.(raw);
  } catch {
    window.open(raw);
  }
}

export function shouldCopyLinkOnClickWithMode(mode: string, evt: MouseEvent): boolean {
  const m = String(mode || 'ctrl-cmd');
  if (m === 'alt') return Boolean((evt as any).altKey);
  if (m === 'shift') return Boolean((evt as any).shiftKey);
  return Boolean((evt as any).ctrlKey) || Boolean((evt as any).metaKey);
}
