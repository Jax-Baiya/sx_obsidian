import { App, TFile, normalizePath } from 'obsidian';

export async function findVaultNotesForId(app: App, id: string, roots: string[]): Promise<TFile[]> {
  const safeId = String(id || '').trim();
  if (!safeId) return [];

  const normalizedRoots = roots.map((r) => normalizePath(String(r || ''))).filter(Boolean);
  const out: TFile[] = [];
  const seen = new Set<string>();

  const directCandidates: string[] = normalizedRoots.slice(0, 2).map((r) => normalizePath(`${r}/${safeId}.md`));
  for (const p of directCandidates) {
    const af = app.vault.getAbstractFileByPath(p);
    if (af && af instanceof TFile) {
      if (!seen.has(af.path)) {
        seen.add(af.path);
        out.push(af);
      }
    }
  }

  const files = app.vault.getFiles();
  for (const f of files) {
    if (f.extension !== 'md') continue;
    if (f.basename !== safeId) continue;
    const p = normalizePath(f.path);
    if (!normalizedRoots.some((r) => r && (p === r || p.startsWith(r + '/')))) continue;
    if (seen.has(f.path)) continue;
    seen.add(f.path);
    out.push(f);
  }

  return out;
}

export async function openVaultNoteForId(
  app: App,
  id: string,
  activeNotesDir: string,
  bookmarksNotesDir: string,
  authorsNotesDir: string
): Promise<boolean> {
  const safeId = String(id || '').trim();
  if (!safeId) return false;

  const candidates: string[] = [
    normalizePath(`${activeNotesDir}/${safeId}.md`),
    normalizePath(`${bookmarksNotesDir}/${safeId}.md`)
  ];

  for (const p of candidates) {
    const af = app.vault.getAbstractFileByPath(p);
    if (af && af instanceof TFile) {
      await app.workspace.getLeaf(true).openFile(af);
      return true;
    }
  }

  const authorsRoot = normalizePath(authorsNotesDir);
  const found = app.vault
    .getFiles()
    .find((f) => f.extension === 'md' && f.basename === safeId && (f.path === authorsRoot || f.path.startsWith(authorsRoot + '/')));
  if (found) {
    await app.workspace.getLeaf(true).openFile(found);
    return true;
  }

  return false;
}
