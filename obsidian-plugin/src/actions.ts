import { Notice, TFile, TFolder, normalizePath, parseYaml, requestUrl } from 'obsidian';
import type SxDbPlugin from './main';
import { mergeMarkdownPreservingUserEdits } from './markdownMerge';
import { openPinnedFile } from './leafUtils';

type VaultWriteStrategy = 'active-only' | 'split';

function tryGetFrontmatter(md: string): any | null {
  const text = String(md ?? '');
  if (!text.startsWith('---')) return null;
  const parts = text.split('---');
  // ['', '\n<yaml>\n', '<rest>...']
  if (parts.length < 3) return null;
  const raw = parts[1];
  try {
    return parseYaml(raw);
  } catch {
    return null;
  }
}

function extractUserMetaPayload(md: string): any | null {
  const fm = tryGetFrontmatter(md);
  if (!fm || typeof fm !== 'object') return null;

  const toStringOrNull = (v: any): string | null => {
    if (v == null) return null;
    const s = String(v).trim();
    return s ? s : null;
  };

  const toJsonOrStringOrNull = (v: any): string | null => {
    if (v == null) return null;
    if (Array.isArray(v) || (typeof v === 'object' && v)) {
      try {
        return JSON.stringify(v);
      } catch {
        return null;
      }
    }
    return toStringOrNull(v);
  };

  const toStringArrayOrNull = (v: any): string[] | null => {
    if (v == null) return null;
    if (Array.isArray(v)) {
      const arr = v.map((x: any) => String(x).trim()).filter(Boolean);
      return arr.length ? arr : [];
    }

    const s = String(v).trim();
    if (!s) return null;

    if ((s.startsWith('[') && s.endsWith(']')) || (s.startsWith('{') && s.endsWith('}'))) {
      try {
        const obj = JSON.parse(s);
        if (Array.isArray(obj)) {
          const arr = obj.map((x: any) => String(x).trim()).filter(Boolean);
          return arr.length ? arr : [];
        }
      } catch {
        // fall through to csv/newline split
      }
    }

    const arr = s
      .split(/[\n,]/g)
      .map((x) => String(x).trim())
      .filter(Boolean);
    return arr.length ? arr : [];
  };

  const tagsVal = (fm as any).tags;
  const tagsStr = Array.isArray(tagsVal)
    ? tagsVal.map((t: any) => String(t).trim()).filter(Boolean).join(',')
    : toStringOrNull(tagsVal);

  return {
    rating: (fm as any).rating != null && String((fm as any).rating).trim() !== '' ? Number((fm as any).rating) : null,
    status: (() => {
      const s = (fm as any).status;
      if (Array.isArray(s)) {
        const first = s.map((x: any) => String(x).trim()).filter(Boolean)[0];
        return first ? String(first) : null;
      }
      return toStringOrNull(s);
    })(),
    statuses: (() => {
      const s = (fm as any).status;
      if (Array.isArray(s)) {
        const arr = s.map((x: any) => String(x).trim()).filter(Boolean);
        return arr.length ? arr : null;
      }
      const one = toStringOrNull(s);
      return one ? [one] : null;
    })(),
    tags: tagsStr,
    notes: toStringOrNull((fm as any).notes),
    product_link: toStringOrNull((fm as any).product_link),
    author_links: toStringArrayOrNull((fm as any).author_links),
    platform_targets: toJsonOrStringOrNull((fm as any).platform_targets ?? (fm as any).platform_target),
    workflow_log: toJsonOrStringOrNull((fm as any).workflow_log),
    post_url: toStringOrNull((fm as any).post_url),
    published_time: toStringOrNull((fm as any).published_time)
  };
}

function isMediaMissing(md: string): boolean {
  const fm = tryGetFrontmatter(md);
  if (!fm || typeof fm !== 'object') return false;
  const v = (fm as any).media_missing;
  return v === true || v === 'true' || v === 1 || v === '1';
}

function slugFolderName(s: string): string {
  const v = (s || '').trim().toLowerCase();
  const slug = v
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+/, '')
    .replace(/-+$/, '');
  return slug || 'unknown';
}

function collectMarkdownFiles(folder: TFolder): TFile[] {
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

async function ensureFolder(plugin: SxDbPlugin, folderPath: string): Promise<TFolder> {
  const existing = plugin.app.vault.getAbstractFileByPath(folderPath);
  if (existing && existing instanceof TFolder) return existing;
  await plugin.app.vault.createFolder(folderPath).catch(() => void 0);
  const created = plugin.app.vault.getAbstractFileByPath(folderPath);
  if (!created || !(created instanceof TFolder)) throw new Error(`Failed to create folder: ${folderPath}`);
  return created;
}

async function ensureFolderDeep(plugin: SxDbPlugin, folderPath: string): Promise<void> {
  const fp = normalizePath(folderPath);
  const parts = fp.split('/').filter(Boolean);
  let cur = '';
  for (const part of parts) {
    cur = cur ? `${cur}/${part}` : part;
    // createFolder can throw if parents are missing depending on platform/version.
    await plugin.app.vault.createFolder(cur).catch(() => void 0);
  }
}

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

async function clearMarkdownInFolder(plugin: SxDbPlugin, folderPath: string): Promise<number> {
  const root = plugin.app.vault.getAbstractFileByPath(folderPath);
  if (!root || !(root instanceof TFolder)) return 0;
  const files = collectMarkdownFiles(root);
  let deleted = 0;
  for (const f of files) {
    await plugin.app.vault.delete(f);
    deleted += 1;
  }
  return deleted;
}

export async function sxTestConnection(plugin: SxDbPlugin): Promise<void> {
  const baseUrl = plugin.settings.apiBaseUrl.replace(/\/$/, '');
  try {
    await requestUrl({ url: `${baseUrl}/health` });
    const stats = await requestUrl({ url: `${baseUrl}/stats` });
    // eslint-disable-next-line no-console
    console.log('[sx-obsidian-db] stats', stats.json);
    new Notice('✅ Connected. See console for /stats output.');
  } catch (e: any) {
    new Notice(`❌ Connection failed: ${String(e?.message ?? e)}`);
  }
}

export function sxOpenApiDocs(plugin: SxDbPlugin): void {
  const baseUrl = plugin.settings.apiBaseUrl.replace(/\/$/, '');
  window.open(`${baseUrl}/docs`);
}

export async function sxPinById(plugin: SxDbPlugin, id: string): Promise<void> {
  const safeId = String(id || '').trim();
  if (!safeId) {
    new Notice('No ID provided.');
    return;
  }

  const baseUrl = plugin.settings.apiBaseUrl.replace(/\/$/, '');
  const activeDir = normalizePath(plugin.settings.activeNotesDir);
  const targetPath = normalizePath(`${activeDir}/${safeId}.md`);

  try {
    const force = Boolean(plugin.settings.fetchForceRegenerate);
    const url = `${baseUrl}/items/${encodeURIComponent(safeId)}/note${force ? '?force=true' : ''}`;
    const resp = await requestUrl({ url });
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
  const baseUrl = plugin.settings.apiBaseUrl.replace(/\/$/, '');
  const batch = Math.max(10, plugin.settings.syncBatchSize ?? 200);
  const maxItems = Math.max(0, plugin.settings.syncMaxItems ?? 2000);
  const replace = Boolean(plugin.settings.syncReplaceOnPull);
  const strategy = (plugin.settings.vaultWriteStrategy || 'split') as VaultWriteStrategy;

  const q = (plugin.settings.fetchQuery || '').trim();
  const statuses = Array.isArray(plugin.settings.fetchStatuses) ? plugin.settings.fetchStatuses : [];
  const force = Boolean(plugin.settings.fetchForceRegenerate);

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
        await ensureFolder(plugin, destDir);
        const deleted = await clearMarkdownInFolder(plugin, destDir);
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

      if (mode === 'bookmarks') params.bookmarked_only = 'true';
      else params.bookmarked_only = 'false';

      const qs = Object.entries(params)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join('&');
      const url = `${baseUrl}/notes?${qs}`;

      const resp = await requestUrl({ url });
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
          await ensureFolder(plugin, destDir);
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
  const baseUrl = plugin.settings.apiBaseUrl.replace(/\/$/, '');
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
      await requestUrl({
        url: `${baseUrl}/items/${encodeURIComponent(id)}/note-md`,
        method: 'PUT',
        body: JSON.stringify({ markdown: md, template_version: 'user' }),
        headers: { 'Content-Type': 'application/json' }
      });

      // Best-effort: also persist user_meta fields from YAML.
      const payload = extractUserMetaPayload(md);
      if (payload) {
        await requestUrl({
          url: `${baseUrl}/items/${encodeURIComponent(id)}/meta`,
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

  await ensureFolder(plugin, activeDir);
  await ensureFolderDeep(plugin, archiveRoot);

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
        await ensureFolderDeep(plugin, archivePath.split('/').slice(0, -1).join('/'));

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
