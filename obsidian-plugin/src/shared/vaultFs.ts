import { App, TFile, TFolder, normalizePath } from 'obsidian';

export function slugFolderName(s: string): string {
  const v = (s || '').trim().toLowerCase();
  const slug = v
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+/, '')
    .replace(/-+$/, '');
  return slug || 'unknown';
}

export function collectMarkdownFiles(folder: TFolder): TFile[] {
  const out: TFile[] = [];
  const stack = [...folder.children];
  while (stack.length) {
    const f = stack.pop();
    if (!f) continue;
    if (f instanceof TFile) {
      if (f.extension === 'md') out.push(f);
    } else if (f instanceof TFolder) {
      stack.push(...f.children);
    }
  }
  return out;
}

export async function ensureFolder(app: App, folderPath: string): Promise<TFolder> {
  const existing = app.vault.getAbstractFileByPath(folderPath);
  if (existing && existing instanceof TFolder) return existing;
  await app.vault.createFolder(folderPath).catch(() => void 0);
  const created = app.vault.getAbstractFileByPath(folderPath);
  if (!created || !(created instanceof TFolder)) throw new Error(`Failed to create folder: ${folderPath}`);
  return created;
}

export async function ensureFolderDeep(app: App, folderPath: string): Promise<void> {
  const fp = normalizePath(folderPath);
  const parts = fp.split('/').filter(Boolean);
  let cur = '';
  for (const part of parts) {
    cur = cur ? `${cur}/${part}` : part;
    await app.vault.createFolder(cur).catch(() => void 0);
  }
}

export async function clearMarkdownInFolder(app: App, folderPath: string): Promise<number> {
  const root = app.vault.getAbstractFileByPath(folderPath);
  if (!root || !(root instanceof TFolder)) return 0;
  const files = collectMarkdownFiles(root);
  let deleted = 0;
  for (const f of files) {
    await app.vault.delete(f);
    deleted += 1;
  }
  return deleted;
}
