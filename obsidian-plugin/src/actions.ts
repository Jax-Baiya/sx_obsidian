import { Notice, TFile, TFolder, normalizePath } from 'obsidian';
import type SxDbPlugin from './main';
import { mergeMarkdownPreservingUserEdits } from './markdownMerge';
import { openPinnedFile } from './leafUtils';
import {
  clearMarkdownInFolder,
  collectMarkdownFiles,
  ensureFolder,
  ensureFolderDeep,
  slugFolderName
} from './shared/vaultFs';
import { extractUserMetaPayload, isMediaMissing } from './shared/frontmatterMeta';

type VaultWriteStrategy = 'active-only' | 'split';

function pickPreferredFileForId(plugin: SxDbPlugin, files: TFile[]): TFile {
  const activeRoot = normalizePath(plugin.settings.activeNotesDir);
  let best = files[0];
  let bestScore = -Infinity;

  for (const f of files) {
    const inActive = normalizePath(f.path).startsWith(activeRoot + '/');
    const mtime = Number((f.stat as any)?.mtime ?? 0);
    // Prefer active dir, then prefer newest file.
    const score = (inActive ? 1_000_000_000_000 : 0) + mtime;
    if (score > bestScore) {
      bestScore = score;
      best = f;
    }
  }

  return best;
}

function toArchiveRoot(activeDir: string): string {
  const p = normalizePath(activeDir);
  const first = p.split('/').filter(Boolean)[0] || '_db';
  return normalizePath(`${first}/_archive_legacy_notes`);
}

function tsSlug(d: Date): string {
  // 2026-02-09T12-34-56Z (path-safe)
  return d.toISOString().replace(/[:.]/g, '-');
}

export async function sxTestConnection(plugin: SxDbPlugin): Promise<void> {
  try {
    await (plugin as any).apiRequest({ path: '/health' });
    const stats = await (plugin as any).apiRequest({ path: '/stats' });
    // eslint-disable-next-line no-console
    console.log('[sx-obsidian-db] stats', stats.json);
    new Notice('✅ Connected. See console for /stats output.');
  } catch (e: any) {
    new Notice(`❌ Connection failed: ${String(e?.message ?? e)}`);
  }
}

export function sxOpenApiDocs(plugin: SxDbPlugin): void {
  window.open((plugin as any).apiUrl('/docs'));
}

export async function sxPinById(plugin: SxDbPlugin, id: string): Promise<void> {
  const safeId = String(id || '').trim();
  if (!safeId) {
    new Notice('No ID provided.');
    return;
  }

  const activeDir = normalizePath(plugin.settings.activeNotesDir);
  const targetPath = normalizePath(`${activeDir}/${safeId}.md`);

  try {
    const force = Boolean(plugin.settings.fetchForceRegenerate);
    const pathlinkerGroup = plugin.getPathlinkerGroupOverride();
    const resp = await (plugin as any).apiRequest({
      path: `/items/${encodeURIComponent(safeId)}/note`,
      query: {
        ...(force ? { force: 'true' } : {}),
        ...(pathlinkerGroup ? { pathlinker_group: pathlinkerGroup } : {})
      }
    });
    const md = (resp.json as any)?.markdown as string;
    if (!md) throw new Error('API returned no markdown');

    if (plugin.settings.skipMissingMediaOnPull && isMediaMissing(md)) {
      new Notice(`Skipped ${safeId}: media_missing=true (file(s) not present on disk).`);
      return;
    }

    await plugin.app.vault.createFolder(activeDir).catch(() => void 0);

    const existing = plugin.app.vault.getAbstractFileByPath(targetPath);
    if (existing && existing instanceof TFile) {
      const prev = await plugin.app.vault.read(existing);
      const merged = mergeMarkdownPreservingUserEdits(prev, md);
      await plugin.app.vault.modify(existing, merged);
    } else {
      await plugin.app.vault.create(targetPath, md);
    }
    plugin.markRecentlyWritten(targetPath);

    if (plugin.settings.openAfterPin) {
      const file = plugin.app.vault.getAbstractFileByPath(targetPath);
      if (file && file instanceof TFile) {
        await openPinnedFile(plugin, file);
      }
    }

    new Notice(`Pinned ${safeId} → ${targetPath}`);
  } catch (e: any) {
    new Notice(`Failed to pin ${safeId}: ${String(e?.message ?? e)}`);
  }
}

export async function sxFetchNotes(plugin: SxDbPlugin): Promise<void> {
  const batch = Math.max(10, plugin.settings.syncBatchSize ?? 200);
  const maxItems = Math.max(0, plugin.settings.syncMaxItems ?? 2000);
  const replace = Boolean(plugin.settings.syncReplaceOnPull);
  const strategy = (plugin.settings.vaultWriteStrategy || 'split') as VaultWriteStrategy;

  const q = (plugin.settings.fetchQuery || '').trim();
  const statuses = Array.isArray(plugin.settings.fetchStatuses) ? plugin.settings.fetchStatuses : [];
  const force = Boolean(plugin.settings.fetchForceRegenerate);
  const pathlinkerGroup = plugin.getPathlinkerGroupOverride();

  const mode = plugin.settings.fetchMode || 'bookmarks';
  const authorUids = Array.isArray(plugin.settings.fetchAuthorUniqueIds)
    ? plugin.settings.fetchAuthorUniqueIds
    : plugin.settings.fetchAuthorUniqueId
      ? [plugin.settings.fetchAuthorUniqueId]
      : [];

  const bookmarkedOnly = mode === 'bookmarks';

  try {
    if (replace) {
      if (strategy === 'split' && mode === 'bookmarks') {
        const destDir = normalizePath(plugin.settings.bookmarksNotesDir);
        await ensureFolder(plugin.app, destDir);
        const deleted = await clearMarkdownInFolder(plugin.app, destDir);
        if (deleted) new Notice(`Cleared ${deleted} note(s) from ${destDir} before fetch.`);
      } else if (strategy !== 'split') {
        new Notice('Replace-on-pull is ignored for active-only strategy (to avoid deleting canonical notes).');
      }
    }

    let offset = 0;
    let written = 0;
    let lastTotal = 0;
    new Notice('Fetching notes from DB…');

    while (true) {
      if (maxItems && written >= maxItems) {
        new Notice(`Fetch stopped at safety cap (${maxItems}).`);
        break;
      }
      const limit = maxItems ? Math.min(batch, maxItems - written) : batch;

      const params: Record<string, string> = {
        limit: String(limit),
        offset: String(offset),
        order: bookmarkedOnly ? 'bookmarked' : 'recent'
      };
      if (q) params.q = q;
      if (authorUids.length) params.author_unique_id = authorUids.join(',');
      if (statuses.length) params.status = statuses.join(',');
      if (force) params.force = 'true';
      if (pathlinkerGroup) params.pathlinker_group = pathlinkerGroup;

      if (mode === 'bookmarks') params.bookmarked_only = 'true';
      else params.bookmarked_only = 'false';

      const resp = await (plugin as any).apiRequest({ path: '/notes', query: params });
      const data = resp.json as {
        notes: Array<{ id: string; markdown: string; bookmarked?: boolean; author_unique_id?: string | null; author_name?: string | null }>;
        total: number;
      };
      const notes = data?.notes ?? [];
      lastTotal = Number(data?.total ?? lastTotal);
      if (!notes.length) break;

      for (const n of notes) {
        const id = String(n.id);
        const md = String(n.markdown ?? '');
        if (!id || !md) continue;

        if (plugin.settings.skipMissingMediaOnPull && isMediaMissing(md)) {
          continue;
        }

        const isBm = Boolean(n.bookmarked);

        const activeDir = normalizePath(plugin.settings.activeNotesDir);
        const authorDir = normalizePath(
          `${plugin.settings.authorsNotesDir}/${slugFolderName(String(n.author_unique_id ?? n.author_name ?? 'unknown'))}`
        );
        const bookmarksDir = normalizePath(plugin.settings.bookmarksNotesDir);

        const destDirs: string[] =
          strategy === 'active-only'
            ? [activeDir]
            : mode === 'bookmarks'
              ? [bookmarksDir]
              : mode === 'authors'
                ? [authorDir]
                : isBm
                  ? [bookmarksDir, authorDir]
                  : [authorDir];

        for (const destDir of destDirs) {
          await ensureFolder(plugin.app, destDir);
          const targetPath = normalizePath(`${destDir}/${id}.md`);
          const existing = plugin.app.vault.getAbstractFileByPath(targetPath);
          if (existing && existing instanceof TFile) {
            const prev = await plugin.app.vault.read(existing);
            const merged = mergeMarkdownPreservingUserEdits(prev, md);
            await plugin.app.vault.modify(existing, merged);
          }
          else await plugin.app.vault.create(targetPath, md);
          plugin.markRecentlyWritten(targetPath);
        }

        written += 1;
      }

      offset += notes.length;
      if (notes.length < limit) break;
    }

    new Notice(`Fetch complete: wrote ${written} note(s). (API total matched: ${lastTotal})`);
  } catch (e: any) {
    new Notice(`Fetch failed: ${String(e?.message ?? e)}`);
  }
}

export async function sxPushNotes(plugin: SxDbPlugin): Promise<void> {
  const max = Math.max(0, plugin.settings.syncMaxItems ?? 2000);
  const deleteAfter = Boolean(plugin.settings.pushDeleteAfter);

  const strategy = (plugin.settings.vaultWriteStrategy || 'split') as VaultWriteStrategy;

  const roots =
    strategy === 'active-only'
      ? [plugin.settings.activeNotesDir]
      : [plugin.settings.bookmarksNotesDir, plugin.settings.authorsNotesDir];
  let files: TFile[] = [];
  for (const r of roots) {
    const folder = plugin.app.vault.getAbstractFileByPath(r);
    if (folder && folder instanceof TFolder) {
      files = files.concat(collectMarkdownFiles(folder));
    }
  }

  if (!files.length) {
    new Notice('No markdown files found under configured _db folders.');
    return;
  }
  // De-dupe by ID (basename) to avoid double-pushing when duplicate files exist.
  const byId = new Map<string, TFile[]>();
  for (const f of files) {
    const id = String(f.basename || '').trim();
    if (!id) continue;
    const arr = byId.get(id) ?? [];
    arr.push(f);
    byId.set(id, arr);
  }

  let dupGroups = 0;
  const uniqueFiles: TFile[] = [];
  for (const [id, arr] of byId.entries()) {
    if (!arr.length) continue;
    if (arr.length > 1) dupGroups += 1;
    uniqueFiles.push(pickPreferredFileForId(plugin, arr));
  }

  files = uniqueFiles;
  if (max && files.length > max) files = files.slice(0, max);

  let pushed = 0;
  let deleted = 0;
  new Notice(`Pushing ${files.length} note(s) to DB…${dupGroups ? ` (${dupGroups} duplicate id group(s) skipped)` : ''}`);

  for (const f of files) {
    const id = f.basename;
    try {
      const md = await plugin.app.vault.read(f);
      await (plugin as any).apiRequest({
        path: `/items/${encodeURIComponent(id)}/note-md`,
        method: 'PUT',
        body: JSON.stringify({ markdown: md, template_version: 'user' }),
        headers: { 'Content-Type': 'application/json' }
      });

      // Best-effort: also persist user_meta fields from YAML.
      const payload = extractUserMetaPayload(md);
      if (payload) {
        await (plugin as any).apiRequest({
          path: `/items/${encodeURIComponent(id)}/meta`,
          method: 'PUT',
          body: JSON.stringify(payload),
          headers: { 'Content-Type': 'application/json' }
        });
      }

      pushed += 1;
      if (deleteAfter) {
        await plugin.app.vault.delete(f);
        deleted += 1;
      }
    } catch (e: any) {
      // eslint-disable-next-line no-console
      console.warn('[sx-obsidian-db] push failed', f.path, e);
    }
  }

  new Notice(`Push complete: ${pushed} pushed${deleteAfter ? `, ${deleted} deleted` : ''}.`);
}

export async function sxConsolidateLegacyNotesToActiveDir(plugin: SxDbPlugin): Promise<void> {
  const strategy = (plugin.settings.vaultWriteStrategy || 'split') as VaultWriteStrategy;
  const activeDir = normalizePath(plugin.settings.activeNotesDir);
  const bookmarksDir = normalizePath(plugin.settings.bookmarksNotesDir);
  const authorsDir = normalizePath(plugin.settings.authorsNotesDir);

  if (strategy !== 'active-only') {
    const ok = window.confirm(
      'Your vaultWriteStrategy is not set to active-only.\n\nThis tool is meant to consolidate legacy split folders into the Active notes folder.\n\nProceed anyway?'
    );
    if (!ok) return;
  }

  // Collect legacy files.
  let legacyFiles: TFile[] = [];
  for (const r of [bookmarksDir, authorsDir]) {
    const folder = plugin.app.vault.getAbstractFileByPath(r);
    if (folder && folder instanceof TFolder) legacyFiles = legacyFiles.concat(collectMarkdownFiles(folder));
  }

  if (!legacyFiles.length) {
    new Notice('No legacy notes found under Bookmarks/Authors folders.');
    return;
  }

  // Dry-run summary
  const activeFolderExists = Boolean(plugin.app.vault.getAbstractFileByPath(activeDir));
  if (!activeFolderExists) {
    // We'll create it if user proceeds.
  }

  const archiveRoot = normalizePath(`${toArchiveRoot(activeDir)}/${tsSlug(new Date())}`);
  let wouldMove = 0;
  let wouldMerge = 0;

  for (const f of legacyFiles) {
    const id = String(f.basename || '').trim();
    if (!id) continue;
    const targetPath = normalizePath(`${activeDir}/${id}.md`);
    const existing = plugin.app.vault.getAbstractFileByPath(targetPath);
    if (existing && existing instanceof TFile) wouldMerge += 1;
    else wouldMove += 1;
  }

  const proceed = window.confirm(
    [
      'Consolidate legacy notes into Active notes folder?',
      '',
      `Active folder: ${activeDir}`,
      `Legacy roots:`,
      `  - ${bookmarksDir}`,
      `  - ${authorsDir}`,
      '',
      `Plan:`,
      `  - Move ${wouldMove} note(s) into ${activeDir}`,
      `  - Merge ${wouldMerge} note(s) into existing active notes`,
      `  - Archive legacy duplicates into ${archiveRoot}`,
      '',
      'Continue?'
    ].join('\n')
  );
  if (!proceed) return;

  await ensureFolder(plugin.app, activeDir);
  await ensureFolderDeep(plugin.app, archiveRoot);

  let moved = 0;
  let merged = 0;
  let archived = 0;
  let failed = 0;

  for (const f of legacyFiles) {
    const id = String(f.basename || '').trim();
    if (!id) continue;
    const targetPath = normalizePath(`${activeDir}/${id}.md`);

    try {
      const existing = plugin.app.vault.getAbstractFileByPath(targetPath);
      if (existing && existing instanceof TFile) {
        const activeMd = await plugin.app.vault.read(existing);
        const legacyMd = await plugin.app.vault.read(f);
        const next = mergeMarkdownPreservingUserEdits(activeMd, legacyMd);
        await plugin.app.vault.modify(existing, next);
        plugin.markRecentlyWritten(existing.path);
        merged += 1;

        // Archive the legacy file (keep structure to avoid collisions).
        const normPath = normalizePath(f.path);
        const rel = normPath.startsWith(bookmarksDir + '/')
          ? `bookmarks/${normPath.slice(bookmarksDir.length + 1)}`
          : normPath.startsWith(authorsDir + '/')
            ? `authors/${normPath.slice(authorsDir.length + 1)}`
            : `misc/${f.name}`;

        let archivePath = normalizePath(`${archiveRoot}/${rel}`);
        await ensureFolderDeep(plugin.app, archivePath.split('/').slice(0, -1).join('/'));

        // If collision, add suffix.
        if (plugin.app.vault.getAbstractFileByPath(archivePath)) {
          const base = archivePath.replace(/\.md$/i, '');
          let i = 2;
          while (plugin.app.vault.getAbstractFileByPath(`${base}__dup${i}.md`)) i += 1;
          archivePath = `${base}__dup${i}.md`;
        }

        await plugin.app.vault.rename(f, archivePath);
        archived += 1;
      } else {
        // Move into activeDir.
        await plugin.app.vault.rename(f, targetPath);
        plugin.markRecentlyWritten(targetPath);
        moved += 1;
      }
    } catch (e: any) {
      failed += 1;
      // eslint-disable-next-line no-console
      console.warn('[sx-obsidian-db] consolidate failed', f.path, e);
    }
  }

  new Notice(
    `Consolidation complete: ${moved} moved, ${merged} merged, ${archived} archived${failed ? `, ${failed} failed` : ''}.`
  );
}

export function sxPreviewVideoById(plugin: SxDbPlugin, id: string): void {
  const safeId = String(id || '').trim();
  if (!safeId) {
    new Notice('No ID found to preview.');
    return;
  }

  const url = `${plugin.settings.apiBaseUrl.replace(/\/$/, '')}/media/video/${encodeURIComponent(safeId)}`;
  try {
    (plugin.app as any).openWithDefaultApp?.(url);
  } catch {
    window.open(url);
  }
}
