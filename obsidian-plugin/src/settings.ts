import { App, Notice, PluginSettingTab, Setting, TFile, TFolder, normalizePath, requestUrl } from 'obsidian';
import type SxDbPlugin from './main';

export interface SxDbSettings {
  apiBaseUrl: string;
  activeNotesDir: string;
  bookmarksNotesDir: string;
  authorsNotesDir: string;
  // Where pull/sync operations write markdown notes.
  // - active-only: always write to activeNotesDir (recommended)
  // - split: legacy behavior (bookmarks + authors folders)
  vaultWriteStrategy: 'active-only' | 'split';
  syncBatchSize: number;
  syncMaxItems: number;
  syncReplaceOnPull: boolean;
  pushDeleteAfter: boolean;
  searchLimit: number;
  debounceMs: number;
  bookmarkedOnly: boolean;
  openAfterPin: boolean;
  openAfterPinSplit: boolean;
  openAfterPinSplitMode: 'new-tab' | 'replace';

  // Settings-page fetch filters (used by DB → vault fetch action)
  fetchMode: 'bookmarks' | 'authors' | 'both';
  fetchBookmarkedOnly: boolean;
  fetchForceRegenerate: boolean;
  fetchQuery: string;
  fetchAuthorUniqueId: string; // legacy single-select (kept for backward compat)
  fetchAuthorUniqueIds: string[]; // preferred multi-select
  fetchStatuses: string[];

  // When enabled, do not create/overwrite notes whose frontmatter has media_missing: true.
  skipMissingMediaOnPull: boolean;
  
  // Autosave: when a user edits a note in the vault, automatically push it back to the DB.
  autoPushOnEdit: boolean;
  autoPushDebounceMs: number;

  // SX Library view UX
  libraryHoverVideoPreview: boolean;
  libraryHoverPreviewMuted: boolean;
  libraryHoverPreviewWidth: number;
  libraryHoverPreviewHeight: number;

  // SX Library: ID column UX
  libraryIdWrapMode: 'wrap' | 'ellipsis' | 'clip';
  libraryIdCtrlHoverPreview: boolean;
  /** Which engine to use when Ctrl/Cmd-hovering IDs in the SX Library.
   * - auto: prefer Obsidian core Page Preview if enabled (so Hover Editor can enhance it), else fall back to SX custom.
   * - native: always trigger Obsidian's hover-link preview.
   * - custom: always use SX's own markdown popover (reads from _db notes).
   */
  libraryIdCtrlHoverPreviewEngine: 'auto' | 'native' | 'custom';
  libraryNotePeekEnabled: boolean;
  /**
   * How the pinned preview should be displayed.
   * - inline: render markdown into SX's floating window (fast, self-contained)
    * - inline-leaf: embed an Obsidian leaf inside the SX floating window (experimental)
   * - hover-editor: open the note in Hover Editor's popover (Obsidian-native view; requires the plugin)
   * - popout: open the note in an Obsidian popout window leaf (Obsidian-native view)
   */
    libraryNotePeekEngine: 'inline' | 'inline-leaf' | 'hover-editor' | 'popout';
  libraryNotePeekWidth: number;
  libraryNotePeekHeight: number;

  // SX Library column layout
  libraryColumnOrder: string[];
  libraryColumnWidths: Record<string, number>;

  // SX Library view state (persist filters/sort between sessions)
  libraryState: {
    q: string;
    bookmarkedOnly: boolean;
    bookmarkFrom: string;
    bookmarkTo: string;
    authorFilter: string;
    statuses: string[];
    sortOrder: 'recent' | 'bookmarked' | 'author' | 'status' | 'rating';
    tag: string;
    ratingMin: string;
    ratingMax: string;
    hasNotes: boolean;
    authorSearch: string;
  };

  // SX Library columns: per-column visibility.
  // Keys correspond to internal column ids used by LibraryView.
  libraryColumns: Record<string, boolean>;
}

export const DEFAULT_SETTINGS: SxDbSettings = {
  apiBaseUrl: 'http://127.0.0.1:8123',
  activeNotesDir: '_db/media_active',
  bookmarksNotesDir: '_db/bookmarks',
  authorsNotesDir: '_db/authors',
  vaultWriteStrategy: 'active-only',
  syncBatchSize: 200,
  syncMaxItems: 2000,
  syncReplaceOnPull: false,
  pushDeleteAfter: false,
  searchLimit: 50,
  debounceMs: 250,
  bookmarkedOnly: false,
  openAfterPin: false,
  openAfterPinSplit: false,
  openAfterPinSplitMode: 'new-tab',

  fetchMode: 'bookmarks',
  fetchBookmarkedOnly: true,
  fetchForceRegenerate: true,
  fetchQuery: '',
  fetchAuthorUniqueId: '',
  fetchAuthorUniqueIds: [],
  fetchStatuses: [],

  skipMissingMediaOnPull: true,

  autoPushOnEdit: true,
  autoPushDebounceMs: 1200,

  libraryHoverVideoPreview: true,
  // Default: unmuted (requested), but note some systems may still block autoplay with sound.
  libraryHoverPreviewMuted: false,
  // Default: portrait hover preview (roughly 9:16), “mini TikTok” sized.
  libraryHoverPreviewWidth: 240,
  libraryHoverPreviewHeight: 426,

  libraryIdWrapMode: 'ellipsis',
  libraryIdCtrlHoverPreview: true,
  libraryIdCtrlHoverPreviewEngine: 'auto',
  libraryNotePeekEnabled: true,
  libraryNotePeekEngine: 'inline',
  libraryNotePeekWidth: 420,
  libraryNotePeekHeight: 520,
  libraryState: {
    q: '',
    bookmarkedOnly: false,
    bookmarkFrom: '',
    bookmarkTo: '',
    authorFilter: '',
    statuses: [],
    sortOrder: 'bookmarked',
    tag: '',
    ratingMin: '',
    ratingMax: '',
    hasNotes: false,
    authorSearch: ''
  },

  libraryColumns: {
    thumb: true,
    id: true,
    author: true,
    bookmarked: true,
    status: true,
    rating: true,
    tags: true,
    notes: true,
    product_link: false,
    platform_targets: false,
    post_url: false,
    published_time: false,
    workflow_log: false,
    actions: true
  },

  libraryColumnOrder: [
    'thumb',
    'id',
    'author',
    'bookmarked',
    'status',
    'rating',
    'tags',
    'notes',
    'product_link',
    'platform_targets',
    'post_url',
    'published_time',
    'workflow_log',
    'actions'
  ],
  libraryColumnWidths: {}
};

const WORKFLOW_STATUSES = ['raw', 'reviewing', 'reviewed', 'scheduling', 'scheduled', 'published', 'archived'];

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

async function ensureFolder(app: App, folderPath: string): Promise<TFolder> {
  const existing = app.vault.getAbstractFileByPath(folderPath);
  if (existing && existing instanceof TFolder) return existing;
  await app.vault.createFolder(folderPath).catch(() => void 0);
  const created = app.vault.getAbstractFileByPath(folderPath);
  if (!created || !(created instanceof TFolder)) throw new Error(`Failed to create folder: ${folderPath}`);
  return created;
}

async function clearMarkdownInFolder(app: App, folderPath: string): Promise<number> {
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

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export class SxDbSettingTab extends PluginSettingTab {
  plugin: SxDbPlugin;

  constructor(app: App, plugin: SxDbPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    containerEl.createEl('h2', { text: 'SX Obsidian DB' });

    const tabBar = containerEl.createDiv({ cls: 'sxdb-settings-tabs' });
    const panelsHost = containerEl.createDiv();

    const tabs: Array<{ id: string; label: string }> = [
      { id: 'connection', label: 'Connection' },
      { id: 'sync', label: 'Sync' },
      { id: 'fetch', label: 'Fetch' },
      { id: 'backend', label: 'Backend' },
      { id: 'views', label: 'Views' },
      { id: 'danger', label: 'Danger Zone' },
      { id: 'advanced', label: 'Advanced' }
    ];

    const panels: Record<string, HTMLDivElement> = {};
    const buttons: Record<string, HTMLButtonElement> = {};

    const activate = (id: string) => {
      // Stash desired tab on plugin so commands can preselect it on open.
      (this.plugin as any).uiActiveSettingsTabId = id;
      for (const t of tabs) {
        const b = buttons[t.id];
        const p = panels[t.id];
        if (b) b.classList.toggle('is-active', t.id === id);
        if (p) p.classList.toggle('is-active', t.id === id);
      }
    };

    for (const t of tabs) {
      const btn = tabBar.createEl('button', { text: t.label, cls: 'sxdb-settings-tab' });
      buttons[t.id] = btn;
      const panel = panelsHost.createDiv({ cls: 'sxdb-settings-panel' });
      panels[t.id] = panel;
      btn.addEventListener('click', () => activate(t.id));
    }

    // default / requested tab
    const requested = String((this.plugin as any).uiActiveSettingsTabId || '').trim();
    const initial = tabs.some((t) => t.id === requested) ? requested : 'connection';
    activate(initial);

    // ── Connection tab ──────────────────────────────────────────────────────
    {
      const el = panels.connection;
      el.createEl('h3', { text: 'Connection' });

      new Setting(el)
        .setName('API base URL')
        .setDesc('FastAPI service base URL (WSL2 localhost forwarding works).')
        .addText((text) =>
          text
            .setPlaceholder('http://127.0.0.1:8123')
            .setValue(this.plugin.settings.apiBaseUrl)
            .onChange(async (value) => {
              this.plugin.settings.apiBaseUrl = value.trim() || DEFAULT_SETTINGS.apiBaseUrl;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Test connection')
        .setDesc('Checks /health and prints database stats from /stats.')
        .addButton((btn) =>
          btn.setButtonText('Test').setCta().onClick(async () => {
            const baseUrl = this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
            try {
              const health = await requestUrl({ url: `${baseUrl}/health` });
              const stats = await requestUrl({ url: `${baseUrl}/stats` });
              // eslint-disable-next-line no-console
              console.log('[sx-obsidian-db] health', health.json);
              // eslint-disable-next-line no-console
              console.log('[sx-obsidian-db] stats', stats.json);
              new Notice('✅ Connected. See console for /stats output.');
            } catch (e: any) {
              new Notice(`❌ Connection failed: ${String(e?.message ?? e)}`);
            }
          })
        )
        .addButton((btn) =>
          btn.setButtonText('Open API docs').onClick(() => {
            const baseUrl = this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
            window.open(`${baseUrl}/docs`);
          })
        );

      new Setting(el)
        .setName('Open plugin views')
        .setDesc('These are the main entry points inside Obsidian.')
        .addButton((btn) =>
          btn.setButtonText('Library table').setCta().onClick(() => {
            // Registered in main.ts
            const pid = this.plugin.manifest?.id || 'sx-obsidian-db';
            (this.app as any).commands?.executeCommandById?.(`${pid}:sxdb-open-library-table`);
          })
        )
        .addButton((btn) =>
          btn.setButtonText('Search modal').onClick(() => {
            const pid = this.plugin.manifest?.id || 'sx-obsidian-db';
            (this.app as any).commands?.executeCommandById?.(`${pid}:sxdb-open-search`);
          })
        );
    }

    // ── Fetch tab ──────────────────────────────────────────────────────────
    {
      const el = panels.fetch;
      el.createEl('h3', { text: 'Fetch (DB → Vault)' });
      el.createEl('p', {
        text:
          'Materialize an “active working set” of notes into your vault. You can fetch Bookmarks, Authors, or both, with flexible filters.'
      });

      // Fetch mode
      new Setting(el)
        .setName('Fetch mode')
        .setDesc('Choose what you want to materialize into _db folders.')
        .addDropdown((dd) => {
          dd.addOption('bookmarks', 'Bookmarks only');
          dd.addOption('authors', 'Authors only (non-bookmarked)');
          dd.addOption('both', 'Bookmarks + Authors (auto-route)');
          dd.setValue(this.plugin.settings.fetchMode || 'bookmarks');
          dd.onChange(async (value) => {
            this.plugin.settings.fetchMode = (value as any) || 'bookmarks';
            // Keep legacy toggle in sync for older logic.
            this.plugin.settings.fetchBookmarkedOnly = this.plugin.settings.fetchMode === 'bookmarks';
            await this.plugin.saveSettings();
          });
        });

      // Query
      new Setting(el)
        .setName('Search (q)')
        .setDesc('Optional text filter applied server-side (caption/author/id).')
        .addText((text) =>
          text.setPlaceholder('e.g. amazon skincare').setValue(this.plugin.settings.fetchQuery || '').onChange(async (v) => {
            this.plugin.settings.fetchQuery = v;
            await this.plugin.saveSettings();
          })
        );

      // Force regenerate
      new Setting(el)
        .setName('Regenerate DB template notes')
        .setDesc(
          'When enabled, the backend regenerates notes using the latest DB template (safe: it will not overwrite notes you pushed with template_version="user").'
        )
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.fetchForceRegenerate)).onChange(async (value) => {
            this.plugin.settings.fetchForceRegenerate = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Skip items missing media')
        .setDesc(
          'When enabled, Fetch/Pin will not create notes whose frontmatter reports media_missing: true. This prevents “phantom” notes when files are not actually downloaded.'
        )
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.skipMissingMediaOnPull)).onChange(async (value) => {
            this.plugin.settings.skipMissingMediaOnPull = value;
            await this.plugin.saveSettings();
          })
        );

      // Status multi-select (pills)
      el.createEl('h4', { text: 'Status filter' });
      const statusPills = el.createDiv({ cls: 'sxdb-pills' });
      const selectedStatuses = new Set<string>(
        Array.isArray(this.plugin.settings.fetchStatuses) ? this.plugin.settings.fetchStatuses : []
      );
      for (const s of WORKFLOW_STATUSES) {
        const pill = statusPills.createEl('button', { text: s, cls: 'sxdb-pill' });
        pill.classList.toggle('is-active', selectedStatuses.has(s));
        pill.addEventListener('click', async (evt) => {
          evt.preventDefault();
          if (selectedStatuses.has(s)) selectedStatuses.delete(s);
          else selectedStatuses.add(s);
          this.plugin.settings.fetchStatuses = Array.from(selectedStatuses);
          pill.classList.toggle('is-active', selectedStatuses.has(s));
          await this.plugin.saveSettings();
        });
      }

      // Author multi-select (search + checklist)
      el.createEl('h4', { text: 'Authors (optional)' });
      el.createEl('p', {
        text:
          'Select one or more authors to fetch. Leave empty for “any author”. (Tip: choose mode “Authors only” to build work queues by creator.)'
      });

      const authorWrap = el.createDiv({ cls: 'sxdb-author-picker' });
      const authorSearch = authorWrap.createEl('input', { type: 'text', placeholder: 'Filter authors…' });
      const authorList = authorWrap.createDiv({ cls: 'sxdb-author-list' });

      const selectedAuthorUids = new Set<string>(
        Array.isArray(this.plugin.settings.fetchAuthorUniqueIds)
          ? this.plugin.settings.fetchAuthorUniqueIds
          : this.plugin.settings.fetchAuthorUniqueId
          ? [this.plugin.settings.fetchAuthorUniqueId]
          : []
      );

      const renderAuthors = (authors: Array<{ uid: string; label: string }>, filter: string) => {
        authorList.empty();
        const f = (filter || '').trim().toLowerCase();
        const show = authors.filter((a) => (!f ? true : a.label.toLowerCase().includes(f) || a.uid.toLowerCase().includes(f)));

        const actions = authorList.createDiv({ cls: 'sxdb-author-actions' });
        const allBtn = actions.createEl('button', { text: 'Select visible' });
        const noneBtn = actions.createEl('button', { text: 'Clear' });

        allBtn.addEventListener('click', async (evt) => {
          evt.preventDefault();
          for (const a of show) selectedAuthorUids.add(a.uid);
          this.plugin.settings.fetchAuthorUniqueIds = Array.from(selectedAuthorUids);
          this.plugin.settings.fetchAuthorUniqueId = '';
          await this.plugin.saveSettings();
          renderAuthors(authors, authorSearch.value);
        });
        noneBtn.addEventListener('click', async (evt) => {
          evt.preventDefault();
          selectedAuthorUids.clear();
          this.plugin.settings.fetchAuthorUniqueIds = [];
          this.plugin.settings.fetchAuthorUniqueId = '';
          await this.plugin.saveSettings();
          renderAuthors(authors, authorSearch.value);
        });

        for (const a of show) {
          const row = authorList.createEl('label', { cls: 'sxdb-author-row' });
          const cb = row.createEl('input', { type: 'checkbox' });
          cb.checked = selectedAuthorUids.has(a.uid);
          row.createSpan({ text: a.label });
          cb.addEventListener('change', async () => {
            if (cb.checked) selectedAuthorUids.add(a.uid);
            else selectedAuthorUids.delete(a.uid);
            this.plugin.settings.fetchAuthorUniqueIds = Array.from(selectedAuthorUids);
            this.plugin.settings.fetchAuthorUniqueId = '';
            await this.plugin.saveSettings();
          });
        }

        if (!show.length) {
          authorList.createEl('em', { text: 'No authors match your filter.' });
        }
      };

      (async () => {
        const baseUrl = this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
        try {
          const resp = await requestUrl({ url: `${baseUrl}/authors?limit=2000&order=count` });
          const data = resp.json as {
            authors: Array<{
              author_id?: string | null;
              author_unique_id?: string | null;
              author_name?: string | null;
              items_count?: number | null;
            }>;
          };
          const authorsRaw = data?.authors ?? [];
          const authors = authorsRaw
            .map((a) => {
              const uid = String(a.author_unique_id || '').trim();
              if (!uid) return null;
              const aid = String(a.author_id || '').trim();
              const name = String(a.author_name || '').trim();
              const count = Number(a.items_count || 0);
              const label = `${name || '(no name)'}  ·  @${uid}${aid ? `  ·  id:${aid}` : ''}  ·  ${count}`;
              return { uid, label };
            })
            .filter(Boolean) as Array<{ uid: string; label: string }>;

          renderAuthors(authors, authorSearch.value);
          authorSearch.addEventListener('input', () => renderAuthors(authors, authorSearch.value));
        } catch {
          authorList.createEl('em', { text: 'Authors list unavailable (API not reachable). You can still fetch without selecting authors.' });
        }
      })();

      // Fetch action
      new Setting(el)
        .setName('DB → vault: fetch notes')
        .setDesc('Fetches notes from the API and writes them into your vault (destination depends on Vault write strategy).')
        .addButton((btn) =>
          btn.setButtonText('Fetch now').setCta().onClick(async () => {
            const baseUrl = this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
            const batch = Math.max(10, this.plugin.settings.syncBatchSize ?? 200);
            const maxItems = Math.max(0, this.plugin.settings.syncMaxItems ?? 2000);
            const replace = Boolean(this.plugin.settings.syncReplaceOnPull);
            const strategy = String(this.plugin.settings.vaultWriteStrategy || 'split');

            const q = (this.plugin.settings.fetchQuery || '').trim();
            const statuses = Array.isArray(this.plugin.settings.fetchStatuses) ? this.plugin.settings.fetchStatuses : [];
            const force = Boolean(this.plugin.settings.fetchForceRegenerate);

            const mode = this.plugin.settings.fetchMode || 'bookmarks';
            const authorUids = Array.isArray(this.plugin.settings.fetchAuthorUniqueIds)
              ? this.plugin.settings.fetchAuthorUniqueIds
              : this.plugin.settings.fetchAuthorUniqueId
              ? [this.plugin.settings.fetchAuthorUniqueId]
              : [];

            // legacy toggle -> mode compatibility
            const bookmarkedOnly = mode === 'bookmarks';

            try {
              // Replacement behavior (safe subsets only)
              if (replace) {
                if (strategy === 'split' && mode === 'bookmarks') {
                  const destDir = normalizePath(this.plugin.settings.bookmarksNotesDir);
                  await ensureFolder(this.app, destDir);
                  const deleted = await clearMarkdownInFolder(this.app, destDir);
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

                // Use explicit mode routing rather than just bookmarked_only.
                // - bookmarks: server-side filter
                // - authors/both: fetch and route client-side
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

                  const isBm = Boolean(n.bookmarked);

                  // Destination routing:
                  // - bookmarks: always write into bookmarks folder (server already filters bookmarked_only=true)
                  // - authors: always write into authors folder (even if bookmarked)
                  // - both: if bookmarked, write into BOTH bookmarks + authors; else write into authors.

                  const authorDir = normalizePath(
                    `${this.plugin.settings.authorsNotesDir}/${slugFolderName(String(n.author_unique_id ?? n.author_name ?? 'unknown'))}`
                  );
                  const bookmarksDir = normalizePath(this.plugin.settings.bookmarksNotesDir);
                  const activeDir = normalizePath(this.plugin.settings.activeNotesDir);

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
                    await ensureFolder(this.app, destDir);
                    const targetPath = normalizePath(`${destDir}/${id}.md`);
                    const existing = this.app.vault.getAbstractFileByPath(targetPath);
                    if (existing && existing instanceof TFile) await this.app.vault.modify(existing, md);
                    else await this.app.vault.create(targetPath, md);
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
          })
        );
    }

    // ── Sync tab ───────────────────────────────────────────────────────────
    {
      const el = panels.sync;
      el.createEl('h3', { text: 'Sync (DB ↔ Vault)' });
      el.createEl('p', {
        text:
          'SQLite is the canonical store. You can materialize a small subset as .md files in the vault (DB → vault), and optionally push edits back (vault → DB).'
      });

      new Setting(el)
        .setName('Active notes folder')
        .setDesc('Canonical destination for pinned notes (relative to vault root).')
        .addText((text) =>
          text
            .setPlaceholder('_db/media_active')
            .setValue(this.plugin.settings.activeNotesDir)
            .onChange(async (value) => {
              this.plugin.settings.activeNotesDir = value.trim() || DEFAULT_SETTINGS.activeNotesDir;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Vault write strategy')
        .setDesc(
          'Controls where DB → vault operations write note files. “Active-only” prevents duplicates by writing everything into the Active notes folder.'
        )
        .addDropdown((dd) =>
          dd
            .addOption('active-only', 'Active-only (recommended)')
            .addOption('split', 'Split (legacy: bookmarks + authors)')
            .setValue(String(this.plugin.settings.vaultWriteStrategy || 'split'))
            .onChange(async (value) => {
              this.plugin.settings.vaultWriteStrategy = value === 'active-only' ? 'active-only' : 'split';
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Bookmarks notes folder')
        .setDesc('Legacy split strategy only: destination for bookmarked items (relative to vault root).')
        .addText((text) =>
          text
            .setPlaceholder('_db/bookmarks')
            .setValue(this.plugin.settings.bookmarksNotesDir)
            .onChange(async (value) => {
              this.plugin.settings.bookmarksNotesDir = value.trim() || DEFAULT_SETTINGS.bookmarksNotesDir;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Authors notes folder')
        .setDesc('Legacy split strategy only: destination base folder for author-grouped notes. Files go into _db/authors/<author>/ID.md')
        .addText((text) =>
          text
            .setPlaceholder('_db/authors')
            .setValue(this.plugin.settings.authorsNotesDir)
            .onChange(async (value) => {
              this.plugin.settings.authorsNotesDir = value.trim() || DEFAULT_SETTINGS.authorsNotesDir;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Consolidate legacy folders (dedupe)')
        .setDesc('Moves/merges notes from legacy Bookmarks/Authors folders into the Active notes folder, archiving duplicates for safety.')
        .addButton((btn) =>
          btn.setButtonText('Consolidate now').onClick(async () => {
            try {
              await (this.app as any).commands?.executeCommandById?.('sxdb-consolidate-legacy-notes');
            } catch {
              new Notice('Consolidation command is unavailable. Please reload the plugin.');
            }
          })
        );

      new Setting(el)
        .setName('Sync batch size')
        .setDesc('How many notes to fetch per API call when syncing. (200 is a good default.)')
        .addText((text) =>
          text
            .setPlaceholder('200')
            .setValue(String(this.plugin.settings.syncBatchSize))
            .onChange(async (value) => {
              const n = Number(value);
              this.plugin.settings.syncBatchSize =
                Number.isFinite(n) && n > 0 ? Math.floor(n) : DEFAULT_SETTINGS.syncBatchSize;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Sync max items')
        .setDesc('Safety cap per sync run to avoid writing thousands of notes by accident.')
        .addText((text) =>
          text
            .setPlaceholder('2000')
            .setValue(String(this.plugin.settings.syncMaxItems))
            .onChange(async (value) => {
              const n = Number(value);
              this.plugin.settings.syncMaxItems =
                Number.isFinite(n) && n >= 0 ? Math.floor(n) : DEFAULT_SETTINGS.syncMaxItems;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Replace destination folder contents on pull')
        .setDesc('When enabled, the destination folder is cleared before pulling a new batch (only when safe).')
        .addToggle((toggle) =>
          toggle.setValue(this.plugin.settings.syncReplaceOnPull).onChange(async (value) => {
            this.plugin.settings.syncReplaceOnPull = value;
            await this.plugin.saveSettings();
          })
        );

      el.createEl('h4', { text: 'Tip' });
      el.createEl('p', { text: 'Fetching filters & actions live in the Fetch tab.' });

      new Setting(el)
        .setName('Vault → DB: delete local files after push')
        .setDesc('After pushing _db notes back into SQLite, delete those .md files to prevent compounding batches.')
        .addToggle((toggle) =>
          toggle.setValue(this.plugin.settings.pushDeleteAfter).onChange(async (value) => {
            this.plugin.settings.pushDeleteAfter = value;
            await this.plugin.saveSettings();
          })
        );

      el.createEl('h4', { text: 'Autosave (recommended)' });
      new Setting(el)
        .setName('Auto-push edits to DB')
        .setDesc(
          'When enabled, any edits you make to notes under _db folders are automatically pushed to SQLite (vault → DB), creating a backup that survives template re-syncs.'
        )
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.autoPushOnEdit)).onChange(async (value) => {
            this.plugin.settings.autoPushOnEdit = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Auto-push debounce (ms)')
        .setDesc('Wait this long after your last keystroke before auto-pushing (prevents spammy requests).')
        .addText((text) =>
          text
            .setPlaceholder('1200')
            .setValue(String(this.plugin.settings.autoPushDebounceMs ?? DEFAULT_SETTINGS.autoPushDebounceMs))
            .onChange(async (value) => {
              const n = Number(value);
              this.plugin.settings.autoPushDebounceMs =
                Number.isFinite(n) && n >= 250 ? Math.floor(n) : DEFAULT_SETTINGS.autoPushDebounceMs;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Vault → DB: push _db notes')
        .setDesc(
          'Upserts markdown files under your configured _db folders into video_notes via PUT /items/{id}/note-md. (Active-only strategy pushes from Active notes folder.)'
        )
        .addButton((btn) =>
          btn.setButtonText('Push now').onClick(async () => {
            const baseUrl = this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
            const max = Math.max(0, this.plugin.settings.syncMaxItems ?? 2000);
            const deleteAfter = Boolean(this.plugin.settings.pushDeleteAfter);

            const strategy = String(this.plugin.settings.vaultWriteStrategy || 'split');

            const roots =
              strategy === 'active-only'
                ? [this.plugin.settings.activeNotesDir]
                : [this.plugin.settings.bookmarksNotesDir, this.plugin.settings.authorsNotesDir];
            let files: TFile[] = [];
            for (const r of roots) {
              const folder = this.app.vault.getAbstractFileByPath(r);
              if (folder && folder instanceof TFolder) {
                files = files.concat(collectMarkdownFiles(folder));
              }
            }

            if (!files.length) {
              new Notice('No markdown files found under configured _db folders.');
              return;
            }
            // De-dupe by ID (basename) to avoid pushing the same item multiple times.
            const byId = new Map<string, TFile[]>();
            for (const f of files) {
              const id = String(f.basename || '').trim();
              if (!id) continue;
              const arr = byId.get(id) ?? [];
              arr.push(f);
              byId.set(id, arr);
            }

            const activeRoot = normalizePath(this.plugin.settings.activeNotesDir);
            let dupGroups = 0;
            const uniqueFiles: TFile[] = [];
            for (const arr of byId.values()) {
              if (!arr.length) continue;
              if (arr.length > 1) dupGroups += 1;

              let best = arr[0];
              let bestScore = -Infinity;
              for (const f of arr) {
                const inActive = normalizePath(f.path).startsWith(activeRoot + '/');
                const mtime = Number((f.stat as any)?.mtime ?? 0);
                const score = (inActive ? 1_000_000_000_000 : 0) + mtime;
                if (score > bestScore) {
                  bestScore = score;
                  best = f;
                }
              }

              uniqueFiles.push(best);
            }

            files = uniqueFiles;
            if (max && files.length > max) files = files.slice(0, max);

            let pushed = 0;
            let deleted = 0;
            new Notice(`Pushing ${files.length} note(s) to DB…${dupGroups ? ` (${dupGroups} duplicate id group(s) skipped)` : ''}`);

            for (const f of files) {
              const id = f.basename;
              try {
                const md = await this.app.vault.read(f);
                await requestUrl({
                  url: `${baseUrl}/items/${encodeURIComponent(id)}/note-md`,
                  method: 'PUT',
                  body: JSON.stringify({ markdown: md, template_version: 'user' }),
                  headers: { 'Content-Type': 'application/json' }
                });
                pushed += 1;
                if (deleteAfter) {
                  await this.app.vault.delete(f);
                  deleted += 1;
                }
              } catch (e: any) {
                // eslint-disable-next-line no-console
                console.warn('[sx-obsidian-db] push failed', f.path, e);
              }
            }

            new Notice(`Push complete: ${pushed} pushed${deleteAfter ? `, ${deleted} deleted` : ''}.`);
          })
        );
    }

    // ── Backend tab ─────────────────────────────────────────────────────────
    {
      const el = panels.backend;
      el.createEl('h3', { text: 'Backend server' });
      el.createEl('p', {
        text:
          'Obsidian plugins cannot reliably start your Python server for security reasons. Use the buttons below to copy commands, then run them in a terminal.'
      });

      new Setting(el)
        .setName('Start server (copy commands)')
        .setDesc('Run from the sx_obsidian repo root.')
        .addButton((btn) =>
          btn.setButtonText('Copy: sxctl api serve').setCta().onClick(async () => {
            const ok = await copyToClipboard('./sxctl.sh api serve');
            new Notice(ok ? 'Copied.' : 'Copy failed (clipboard permissions).');
          })
        )
        .addButton((btn) =>
          btn.setButtonText('Copy: python -m sx_db serve').onClick(async () => {
            const ok = await copyToClipboard('./.venv/bin/python -m sx_db serve');
            new Notice(ok ? 'Copied.' : 'Copy failed (clipboard permissions).');
          })
        )
        .addButton((btn) =>
          btn.setButtonText('Open /docs').onClick(() => {
            const baseUrl = this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
            window.open(`${baseUrl}/docs`);
          })
        );
    }

    // ── Views tab ─────────────────────────────────────────────────────────
    {
      const el = panels.views;
      el.createEl('h3', { text: 'Views' });
      el.createEl('p', { text: 'Customize SX Library view behavior and appearance.' });

      el.createEl('h4', { text: 'ID column' });
      new Setting(el)
        .setName('ID wrapping')
        .setDesc('Controls how long IDs are displayed in the SX Library table.')
        .addDropdown((dd) => {
          dd.addOption('ellipsis', 'Overflow: ellipsis');
          dd.addOption('clip', 'Overflow: clip');
          dd.addOption('wrap', 'Wrap');
          dd.setValue(this.plugin.settings.libraryIdWrapMode || 'ellipsis');
          dd.onChange(async (v) => {
            const next = (v as any) || 'ellipsis';
            this.plugin.settings.libraryIdWrapMode = next;
            await this.plugin.saveSettings();
          });
        });

      new Setting(el)
        .setName('Ctrl/Cmd + hover: show Obsidian note preview')
        .setDesc('When enabled, holding Ctrl (Cmd on macOS) and hovering an ID shows a note preview. You can choose the native Page Preview engine (so Hover Editor can enhance it) or the SX custom preview (reads _db notes directly).')
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.libraryIdCtrlHoverPreview)).onChange(async (value) => {
            this.plugin.settings.libraryIdCtrlHoverPreview = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Ctrl/Cmd + hover: preview engine')
        .setDesc('Auto = Native Page Preview if enabled (best compatibility with Hover Editor), otherwise SX Custom.')
        .addDropdown((dd) => {
          dd.addOption('auto', 'Auto (Native → fallback to SX Custom)');
          dd.addOption('native', 'Native (Obsidian Page Preview / hover-link)');
          dd.addOption('custom', 'SX Custom (renders _db markdown directly)');
          dd.setValue(this.plugin.settings.libraryIdCtrlHoverPreviewEngine || 'auto');
          dd.setDisabled(!Boolean(this.plugin.settings.libraryIdCtrlHoverPreview));
          dd.onChange(async (v) => {
            const next = (v as any) || 'auto';
            this.plugin.settings.libraryIdCtrlHoverPreviewEngine = next;
            await this.plugin.saveSettings();
            // refresh UI so disabled state stays in sync with toggle
            this.display();
          });
        });

      new Setting(el)
        .setName('Pinned Note Peek window')
        .setDesc('Enables the “Peek” button in the ID column, opening a draggable/resizable note preview window.')
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.libraryNotePeekEnabled)).onChange(async (value) => {
            this.plugin.settings.libraryNotePeekEnabled = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Pinned Note Peek: preview engine')
        .setDesc(
          'Choose how Peek opens notes. “Hover Editor” and “Popout” use Obsidian’s native note views (properties, reading/live preview), while “Inline” is SX’s lightweight renderer.'
        )
        .addDropdown((dd) => {
          dd.addOption('inline', 'Inline (SX window)');
          dd.addOption('inline-leaf', 'Inline (Obsidian leaf) — experimental');
          dd.addOption('hover-editor', 'Hover Editor popover (requires Hover Editor plugin)');
          dd.addOption('popout', 'Popout window (Obsidian leaf)');
          dd.setValue((this.plugin.settings as any).libraryNotePeekEngine || 'inline');
          dd.setDisabled(!Boolean(this.plugin.settings.libraryNotePeekEnabled));
          dd.onChange(async (v) => {
            (this.plugin.settings as any).libraryNotePeekEngine = (v as any) || 'inline';
            await this.plugin.saveSettings();
            this.display();
          });
        });

      new Setting(el)
        .setName('Pinned Note Peek size')
        .setDesc('Default size in pixels (width/height).')
        .addText((text) =>
          text
            .setPlaceholder('width')
            .setValue(String(this.plugin.settings.libraryNotePeekWidth ?? DEFAULT_SETTINGS.libraryNotePeekWidth))
            .onChange(async (v) => {
              const n = Number(v);
              this.plugin.settings.libraryNotePeekWidth =
                Number.isFinite(n) && n >= 280 ? Math.floor(n) : DEFAULT_SETTINGS.libraryNotePeekWidth;
              await this.plugin.saveSettings();
            })
        )
        .addText((text) =>
          text
            .setPlaceholder('height')
            .setValue(String(this.plugin.settings.libraryNotePeekHeight ?? DEFAULT_SETTINGS.libraryNotePeekHeight))
            .onChange(async (v) => {
              const n = Number(v);
              this.plugin.settings.libraryNotePeekHeight =
                Number.isFinite(n) && n >= 220 ? Math.floor(n) : DEFAULT_SETTINGS.libraryNotePeekHeight;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('SX Library: hover video preview')
        .setDesc('When enabled, hovering a thumbnail shows an inline video preview (streams via /media/video/{id}).')
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.libraryHoverVideoPreview)).onChange(async (value) => {
            this.plugin.settings.libraryHoverVideoPreview = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('SX Library: mute hover preview')
        .setDesc('When enabled, hover previews are muted. If disabled, autoplay with sound may still be blocked by your system/browser policies.')
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.libraryHoverPreviewMuted)).onChange(async (value) => {
            this.plugin.settings.libraryHoverPreviewMuted = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('SX Library: hover preview size')
        .setDesc('Width/height in pixels for the hover video overlay.')
        .addText((text) =>
          text
            .setPlaceholder('width')
            .setValue(String(this.plugin.settings.libraryHoverPreviewWidth ?? DEFAULT_SETTINGS.libraryHoverPreviewWidth))
            .onChange(async (v) => {
              const n = Number(v);
              this.plugin.settings.libraryHoverPreviewWidth = Number.isFinite(n) && n >= 120 ? Math.floor(n) : DEFAULT_SETTINGS.libraryHoverPreviewWidth;
              await this.plugin.saveSettings();
            })
        )
        .addText((text) =>
          text
            .setPlaceholder('height')
            .setValue(String(this.plugin.settings.libraryHoverPreviewHeight ?? DEFAULT_SETTINGS.libraryHoverPreviewHeight))
            .onChange(async (v) => {
              const n = Number(v);
              this.plugin.settings.libraryHoverPreviewHeight = Number.isFinite(n) && n >= 90 ? Math.floor(n) : DEFAULT_SETTINGS.libraryHoverPreviewHeight;
              await this.plugin.saveSettings();
            })
        );

      el.createEl('p', {
        text:
          'Tip: If preview feels slow, disable hover preview and use the Preview/Open/Reveal buttons in the table.'
      });
    }

    // ── Danger Zone tab ───────────────────────────────────────────────────
    {
      const el = panels.danger;
      el.createEl('h3', { text: 'Danger Zone' });
      el.createEl('p', {
        text:
          'These actions delete data from the SQLite DB. They are intended for recovery and troubleshooting. Use Preview first, then Apply only if you are sure.'
      });

      const state: any = (this.plugin.settings as any).libraryState ?? {};
      const filtersPreview = [
        `q=${String(state.q ?? '').trim() || '∅'}`,
        `bookmarkedOnly=${Boolean(state.bookmarkedOnly)}`,
        `author=${String(state.authorFilter ?? '').trim() || '∅'}`,
        `statuses=${Array.isArray(state.statuses) && state.statuses.length ? state.statuses.join(',') : '∅'}`,
        `tag=${String(state.tag ?? '').trim() || '∅'}`,
        `ratingMin=${String(state.ratingMin ?? '').trim() || '∅'}`,
        `ratingMax=${String(state.ratingMax ?? '').trim() || '∅'}`,
        `hasNotes=${Boolean(state.hasNotes)}`,
        `sort=${String(state.sortOrder ?? 'bookmarked')}`
      ].join(' | ');

      el.createEl('p', {
        text:
          `Scope: uses your last SX Library filters (open SX Library to change them). Current: ${filtersPreview}`
      });

      let resetMeta = true;
      let resetUserNotes = false;
      let resetCachedNotes = false;
      let confirmText = '';

      new Setting(el)
        .setName('Reset user meta (rating/status/tags/notes)')
        .setDesc('Deletes rows from user_meta for matching items.')
        .addToggle((t) => t.setValue(resetMeta).onChange((v) => (resetMeta = v)));

      new Setting(el)
        .setName('Reset user notes (DB backup)')
        .setDesc("Deletes notes in video_notes where template_version='user' for matching items. This effectively reverts to template notes.")
        .addToggle((t) => t.setValue(resetUserNotes).onChange((v) => (resetUserNotes = v)));

      new Setting(el)
        .setName('Reset cached template notes')
        .setDesc('Deletes cached non-user notes in video_notes for matching items (forces regeneration).')
        .addToggle((t) => t.setValue(resetCachedNotes).onChange((v) => (resetCachedNotes = v)));

      new Setting(el)
        .setName("Type RESET to enable Apply")
        .setDesc('Required confirmation string.')
        .addText((text) =>
          text
            .setPlaceholder('RESET')
            .setValue('')
            .onChange((v) => {
              confirmText = v;
            })
        );

      const out = el.createEl('pre', { text: '' });
      out.style.whiteSpace = 'pre-wrap';

      const buildFilters = (): any => {
        const s: any = (this.plugin.settings as any).libraryState ?? {};
        const statuses = Array.isArray(s.statuses) ? s.statuses.filter((x: any) => typeof x === 'string' && x.trim()) : [];
        const ratingMin = String(s.ratingMin ?? '').trim();
        const ratingMax = String(s.ratingMax ?? '').trim();
        return {
          q: String(s.q ?? ''),
          bookmarked_only: Boolean(s.bookmarkedOnly),
          author_unique_id: String(s.authorFilter ?? '').trim() || null,
          status: statuses.length ? statuses.join(',') : null,
          tag: String(s.tag ?? '').trim() || null,
          rating_min: ratingMin && !Number.isNaN(Number(ratingMin)) ? Number(ratingMin) : null,
          rating_max: ratingMax && !Number.isNaN(Number(ratingMax)) ? Number(ratingMax) : null,
          // Only filter by notes when explicitly enabled; otherwise keep it unscoped.
          has_notes: Boolean(s.hasNotes) ? true : null
        };
      };

      const call = async (apply: boolean) => {
        const baseUrl = this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
        const payload = {
          apply,
          confirm: apply ? String(confirmText || '') : '',
          filters: buildFilters(),
          reset_user_meta: resetMeta,
          reset_user_notes: resetUserNotes,
          reset_cached_notes: resetCachedNotes
        };

        try {
          const resp = await requestUrl({
            url: `${baseUrl}/danger/reset`,
            method: 'POST',
            body: JSON.stringify(payload),
            headers: { 'Content-Type': 'application/json' }
          });
          out.setText(JSON.stringify(resp.json, null, 2));
          new Notice(apply ? 'Danger reset applied.' : 'Preview loaded.');
        } catch (e: any) {
          out.setText(String(e?.message ?? e));
          new Notice(`Danger reset failed: ${String(e?.message ?? e)}`);
        }
      };

      new Setting(el)
        .setName('Preview')
        .setDesc('Shows how many rows would be deleted (dry run).')
        .addButton((btn) => btn.setButtonText('Preview').setCta().onClick(() => void call(false)));

      new Setting(el)
        .setName('Apply')
        .setDesc('Actually deletes rows. Requires typing RESET above.')
        .addButton((btn) =>
          btn
            .setButtonText('Apply')
            .setWarning()
            .onClick(() => {
              if (String(confirmText || '').trim() !== 'RESET') {
                new Notice("Type RESET to apply.");
                return;
              }
              void call(true);
            })
        );
    }

    // ── Advanced tab ───────────────────────────────────────────────────────
    {
      const el = panels.advanced;
      el.createEl('h3', { text: 'Advanced' });

      new Setting(el)
        .setName('Search limit')
        .setDesc('Max results returned per page in the table.')
        .addText((text) =>
          text
            .setPlaceholder('50')
            .setValue(String(this.plugin.settings.searchLimit))
            .onChange(async (value) => {
              const n = Number(value);
              this.plugin.settings.searchLimit =
                Number.isFinite(n) && n > 0 ? Math.floor(n) : DEFAULT_SETTINGS.searchLimit;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Debounce (ms)')
        .setDesc('Delay after typing before querying the API.')
        .addText((text) =>
          text
            .setPlaceholder('250')
            .setValue(String(this.plugin.settings.debounceMs))
            .onChange(async (value) => {
              const n = Number(value);
              this.plugin.settings.debounceMs =
                Number.isFinite(n) && n >= 0 ? Math.floor(n) : DEFAULT_SETTINGS.debounceMs;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Search modal: bookmarked only')
        .setDesc('When enabled, the search modal shows only bookmarked items.')
        .addToggle((toggle) =>
          toggle.setValue(this.plugin.settings.bookmarkedOnly).onChange(async (value) => {
            this.plugin.settings.bookmarkedOnly = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Open note after pin')
        .setDesc('After pinning an item, open the note in the editor.')
        .addToggle((toggle) =>
          toggle.setValue(this.plugin.settings.openAfterPin).onChange(async (value) => {
            this.plugin.settings.openAfterPin = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Open note after pin in split window')
        .setDesc('When enabled (and “Open note after pin” is on), the note opens in a split pane instead of reusing the current pane.')
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.openAfterPinSplit)).onChange(async (value) => {
            this.plugin.settings.openAfterPinSplit = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Split behavior (when split already exists)')
        .setDesc('Controls how subsequent pins behave: open as a new tab in the split pane, or replace the current tab in that split pane.')
        .addDropdown((dd) => {
          dd.addOption('new-tab', 'Open as new tab (recommended)');
          dd.addOption('replace', 'Replace current tab');
          dd.setValue((this.plugin.settings.openAfterPinSplitMode as any) || 'new-tab');
          dd.onChange(async (value) => {
            this.plugin.settings.openAfterPinSplitMode = (value === 'replace' ? 'replace' : 'new-tab') as any;
            await this.plugin.saveSettings();
          });
          dd.setDisabled(!Boolean(this.plugin.settings.openAfterPinSplit));
          return dd;
        });
    }
  }
}
