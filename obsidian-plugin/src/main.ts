import { App, Modal, Notice, Plugin, requestUrl, TFile, normalizePath, parseYaml } from 'obsidian';
import { DEFAULT_SETTINGS, SxDbSettingTab, type SxDbSettings } from './settings';
import { LibraryView, SXDB_LIBRARY_VIEW } from './libraryView';
import {
  sxConsolidateLegacyNotesToActiveDir,
  sxFetchNotes,
  sxOpenApiDocs,
  sxPinById,
  sxPreviewVideoById,
  sxPushNotes,
  sxTestConnection
} from './actions';

type SearchRow = {
  id: string;
  author_unique_id?: string;
  author_name?: string;
  snippet?: string;
  bookmarked?: number;
};

class SearchModal extends Modal {
  plugin: SxDbPlugin;
  inputEl!: HTMLInputElement;
  resultsEl!: HTMLDivElement;
  timer: number | null = null;

  constructor(app: App, plugin: SxDbPlugin) {
    super(app);
    this.plugin = plugin;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();

    contentEl.createEl('h2', { text: 'SX Library Search' });

    this.inputEl = contentEl.createEl('input', {
      type: 'text',
      placeholder: 'Search caption / author / id…'
    });
    this.inputEl.style.width = '100%';

    this.resultsEl = contentEl.createDiv({ cls: 'sxdb-results' });

    this.inputEl.addEventListener('input', () => {
      if (this.timer) window.clearTimeout(this.timer);
      const delay = Math.max(0, this.plugin.settings.debounceMs ?? 250);
      this.timer = window.setTimeout(() => void this.refresh(), delay);
    });

    void this.refresh();
  }

  async refresh(): Promise<void> {
    const q = (this.inputEl?.value ?? '').trim();
    this.resultsEl.empty();

    const baseUrl = this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
    const limit = Math.max(1, this.plugin.settings.searchLimit ?? 50);
    const bookmarkedOnly = Boolean(this.plugin.settings.bookmarkedOnly);

    try {
      const url = `${baseUrl}/search?q=${encodeURIComponent(q)}&limit=${encodeURIComponent(String(limit))}&offset=0`;
      const resp = await requestUrl({ url });
      const data = resp.json as { results: SearchRow[] };

      const rows = (data.results ?? []).filter((r) => (bookmarkedOnly ? Boolean(r.bookmarked) : true));

      for (const row of rows) {
        const el = this.resultsEl.createDiv({ cls: 'sxdb-row' });
        el.setAttr('role', 'button');
        el.setAttr('tabindex', '0');

        const left = el.createDiv({ cls: 'sxdb-left' });
        left.createDiv({ cls: 'sxdb-id', text: row.id });

        const meta = left.createDiv({ cls: 'sxdb-meta' });
        const isBookmarked = Boolean(row.bookmarked);
        meta.createSpan({ cls: 'sxdb-bm', text: isBookmarked ? '★' : ' ' });
        meta.createSpan({ cls: 'sxdb-author', text: row.author_unique_id ?? row.author_name ?? '' });

        el.createDiv({ cls: 'sxdb-snippet', text: row.snippet ?? '' });

        el.addEventListener('click', () => {
          void this.pin(row.id);
        });

        el.addEventListener('keydown', (evt: KeyboardEvent) => {
          if (evt.key === 'Enter') void this.pin(row.id);
        });
      }

      if (!rows.length) {
        this.resultsEl.createEl('em', { text: 'No results.' });
      }
    } catch (e: any) {
      this.resultsEl.createEl('pre', { text: String(e?.message ?? e) });
    }
  }

  async pin(id: string): Promise<void> {
    await sxPinById(this.plugin, id);
  }
}

class PinByIdModal extends Modal {
  plugin: SxDbPlugin;
  inputEl!: HTMLInputElement;

  constructor(app: App, plugin: SxDbPlugin) {
    super(app);
    this.plugin = plugin;
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();

    contentEl.createEl('h2', { text: 'Pin SX item by ID' });
    this.inputEl = contentEl.createEl('input', {
      type: 'text',
      placeholder: 'Enter video id (digits)…'
    });
    this.inputEl.style.width = '100%';

    const row = contentEl.createDiv({ cls: 'sxdb-modal-actions' });
    const btn = row.createEl('button', { text: 'Pin' });
    btn.addEventListener('click', () => {
      const id = (this.inputEl?.value ?? '').trim();
      void sxPinById(this.plugin, id);
      this.close();
    });

    this.inputEl.addEventListener('keydown', (evt: KeyboardEvent) => {
      if (evt.key === 'Enter') {
        const id = (this.inputEl?.value ?? '').trim();
        void sxPinById(this.plugin, id);
        this.close();
      }
    });

    window.setTimeout(() => this.inputEl?.focus(), 50);
  }
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export default class SxDbPlugin extends Plugin {
  settings: SxDbSettings = DEFAULT_SETTINGS;

  // Non-persisted UI hint for the settings tab implementation.
  uiActiveSettingsTabId: string | null = null;

  private _recentWrites: Map<string, number> = new Map();
  private _autoPushTimers: Map<string, number> = new Map();
  private _autoPushLegacyWarned: Set<string> = new Set();

  markRecentlyWritten(path: string): void {
    const p = normalizePath(path);
    this._recentWrites.set(p, Date.now());
  }

  private isRecentlyWritten(path: string): boolean {
    const p = normalizePath(path);
    const ts = this._recentWrites.get(p);
    if (!ts) return false;
    return Date.now() - ts < 2500;
  }

  private classifyDbFolder(filePath: string): 'active' | 'legacy' | null {
    const p = normalizePath(filePath);

    const activeRoot = normalizePath(this.settings.activeNotesDir);
    if (activeRoot && (p === activeRoot || p.startsWith(activeRoot + '/'))) return 'active';

    const bookmarksRoot = normalizePath(this.settings.bookmarksNotesDir);
    if (bookmarksRoot && (p === bookmarksRoot || p.startsWith(bookmarksRoot + '/'))) return 'legacy';

    const authorsRoot = normalizePath(this.settings.authorsNotesDir);
    if (authorsRoot && (p === authorsRoot || p.startsWith(authorsRoot + '/'))) return 'legacy';

    return null;
  }

  private async autoPushFile(file: TFile): Promise<void> {
    const baseUrl = this.settings.apiBaseUrl.replace(/\/$/, '');
    const md = await this.app.vault.read(file);
    const text = String(md ?? '').trim();
    if (!text) return;

    // Best-effort: derive id from frontmatter.id or filename.
    let id = file.basename;
    if (text.startsWith('---')) {
      const idx = text.indexOf('\n---', 3);
      if (idx !== -1) {
        const rawFm = text.slice(3, idx + 1);
        try {
          const fm = parseYaml(rawFm) as any;
          if (fm && typeof fm === 'object' && fm.id) id = String(fm.id).trim() || id;
        } catch {
          // ignore
        }
      }
    }
    id = String(id || '').trim();
    if (!id) return;

    // Push markdown first (this creates the durable backup).
    await requestUrl({
      url: `${baseUrl}/items/${encodeURIComponent(id)}/note-md`,
      method: 'PUT',
      body: JSON.stringify({ markdown: text, template_version: 'user' }),
      headers: { 'Content-Type': 'application/json' }
    });

    // Optional meta extraction (rating/status/tags/notes) from YAML for redundancy.
    if (text.startsWith('---')) {
      const idx = text.indexOf('\n---', 3);
      if (idx !== -1) {
        const rawFm = text.slice(3, idx + 1);
        try {
          const fm = parseYaml(rawFm) as any;
          if (fm && typeof fm === 'object') {
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

            const tagsVal = (fm as any).tags;
            const tagsStr = Array.isArray(tagsVal)
              ? tagsVal.map((t: any) => String(t).trim()).filter(Boolean).join(',')
              : toStringOrNull(tagsVal);

            const payload = {
              rating: fm.rating != null && String(fm.rating).trim() !== '' ? Number(fm.rating) : null,
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
              // Accept either platform_targets (preferred) or platform_target (legacy/singular)
              platform_targets: toJsonOrStringOrNull((fm as any).platform_targets ?? (fm as any).platform_target),
              workflow_log: toJsonOrStringOrNull((fm as any).workflow_log),
              post_url: toStringOrNull((fm as any).post_url),
              published_time: toStringOrNull((fm as any).published_time)
            };
            await requestUrl({
              url: `${baseUrl}/items/${encodeURIComponent(id)}/meta`,
              method: 'PUT',
              body: JSON.stringify(payload),
              headers: { 'Content-Type': 'application/json' }
            });
          }
        } catch {
          // ignore
        }
      }
    }
  }

  private async getOrOpenLibraryView(): Promise<LibraryView | null> {
    const leaves = this.app.workspace.getLeavesOfType(SXDB_LIBRARY_VIEW);
    if (leaves.length) {
      const view = leaves[0]?.view;
      return view instanceof LibraryView ? view : null;
    }
    const leaf = this.app.workspace.getLeaf(true);
    await leaf.setViewState({ type: SXDB_LIBRARY_VIEW, active: true });
    const view = leaf.view;
    return view instanceof LibraryView ? view : null;
  }

  private openPluginSettings(tabId?: string): void {
    if (tabId) this.uiActiveSettingsTabId = tabId;
    const setting = (this.app as any).setting;
    try {
      setting?.open?.();
      // In modern Obsidian, plugin settings tab IDs are the plugin id.
      setting?.openTabById?.(this.manifest?.id);
    } catch {
      // ignore
    }
  }

  async onload(): Promise<void> {
    await this.loadSettings();

    this.addSettingTab(new SxDbSettingTab(this.app, this));

    this.registerView(SXDB_LIBRARY_VIEW, (leaf) => new LibraryView(leaf, this));

    this.addCommand({
      id: 'sxdb-open-search',
      name: 'SX: Search library',
      callback: () => {
        new SearchModal(this.app, this).open();
      }
    });

    this.addCommand({
      id: 'sxdb-pin-by-id',
      name: 'SX: Pin item by ID…',
      callback: () => {
        new PinByIdModal(this.app, this).open();
      }
    });

    this.addCommand({
      id: 'sxdb-open-library-table',
      name: 'SX: Open library table',
      callback: async () => {
        const leaf = this.app.workspace.getLeaf(true);
        await leaf.setViewState({ type: SXDB_LIBRARY_VIEW, active: true });
      }
    });

    this.addCommand({
      id: 'sxdb-library-refresh',
      name: 'SX: Refresh library table',
      callback: async () => {
        const view = await this.getOrOpenLibraryView();
        if (!view) {
          new Notice('Library view is not available.');
          return;
        }
        await view.refresh();
      }
    });

    this.addCommand({
      id: 'sxdb-library-sync-selection',
      name: 'SX: Sync current library selection → vault',
      callback: async () => {
        const view = await this.getOrOpenLibraryView();
        if (!view) {
          new Notice('Library view is not available.');
          return;
        }
        await view.syncCurrentSelection();
      }
    });

    this.addCommand({
      id: 'sxdb-fetch-notes',
      name: 'SX: Fetch notes (DB → vault) using Fetch settings',
      callback: async () => {
        await sxFetchNotes(this);
      }
    });

    this.addCommand({
      id: 'sxdb-push-notes',
      name: 'SX: Push notes (vault → DB) from _db folders',
      callback: async () => {
        await sxPushNotes(this);
      }
    });

    this.addCommand({
      id: 'sxdb-consolidate-legacy-notes',
      name: 'SX: Consolidate legacy notes → active folder (dedupe)',
      callback: async () => {
        await sxConsolidateLegacyNotesToActiveDir(this);
      }
    });

    this.addCommand({
      id: 'sxdb-test-connection',
      name: 'SX: Test API connection',
      callback: async () => {
        await sxTestConnection(this);
      }
    });

    this.addCommand({
      id: 'sxdb-open-api-docs',
      name: 'SX: Open API docs',
      callback: () => {
        sxOpenApiDocs(this);
      }
    });

    this.addCommand({
      id: 'sxdb-preview-video-current',
      name: 'SX: Preview video for current note',
      callback: () => {
        const file = this.app.workspace.getActiveFile();
        if (!file) {
          new Notice('No active file.');
          return;
        }
        const cache = this.app.metadataCache.getFileCache(file);
        const fm = (cache as any)?.frontmatter ?? {};
        const id = String(fm?.id ?? file.basename ?? '').trim();
        sxPreviewVideoById(this, id);
      }
    });

    this.addCommand({
      id: 'sxdb-open-settings',
      name: 'SX: Open plugin settings',
      callback: () => {
        this.openPluginSettings();
      }
    });

    this.addCommand({
      id: 'sxdb-open-settings-connection',
      name: 'SX: Open settings → Connection tab',
      callback: () => this.openPluginSettings('connection')
    });
    this.addCommand({
      id: 'sxdb-open-settings-sync',
      name: 'SX: Open settings → Sync tab',
      callback: () => this.openPluginSettings('sync')
    });
    this.addCommand({
      id: 'sxdb-open-settings-fetch',
      name: 'SX: Open settings → Fetch tab',
      callback: () => this.openPluginSettings('fetch')
    });
    this.addCommand({
      id: 'sxdb-open-settings-backend',
      name: 'SX: Open settings → Backend tab',
      callback: () => this.openPluginSettings('backend')
    });

    this.addCommand({
      id: 'sxdb-open-settings-views',
      name: 'SX: Open settings → Views tab',
      callback: () => this.openPluginSettings('views')
    });
    this.addCommand({
      id: 'sxdb-open-settings-advanced',
      name: 'SX: Open settings → Advanced tab',
      callback: () => this.openPluginSettings('advanced')
    });

    this.addCommand({
      id: 'sxdb-copy-sxctl-serve',
      name: 'SX: Copy backend command (sxctl api serve)',
      callback: async () => {
        const ok = await copyToClipboard('./sxctl.sh api serve');
        new Notice(ok ? 'Copied.' : 'Copy failed (clipboard permissions).');
      }
    });

    this.addCommand({
      id: 'sxdb-copy-python-serve',
      name: 'SX: Copy backend command (python -m sx_db serve)',
      callback: async () => {
        const ok = await copyToClipboard('./.venv/bin/python -m sx_db serve');
        new Notice(ok ? 'Copied.' : 'Copy failed (clipboard permissions).');
      }
    });

    // Autosave: any edits under _db folders are auto-pushed to SQLite.
    this.registerEvent(
      this.app.vault.on('modify', (af) => {
        if (!this.settings.autoPushOnEdit) return;
        if (!(af instanceof TFile)) return;
        if (af.extension !== 'md') return;

        const folderClass = this.classifyDbFolder(af.path);
        if (!folderClass) return;

        const strategy = String(this.settings.vaultWriteStrategy || 'split');
        if (strategy === 'active-only' && folderClass === 'legacy') {
          // Avoid surprising background writes from legacy folders when the vault strategy is active-only.
          // Warn once per file path per session to keep it quiet.
          const p = normalizePath(af.path);
          if (!this._autoPushLegacyWarned.has(p)) {
            this._autoPushLegacyWarned.add(p);
            new Notice(
              'Auto-push skipped: you edited a legacy _db note (bookmarks/authors) while “Vault write strategy” is Active-only. Use the Consolidate command (or switch to Split) if you want edits here pushed to SQLite.'
            );
          }
          return;
        }

        if (this.isRecentlyWritten(af.path)) return;

        const key = normalizePath(af.path);
        const prev = this._autoPushTimers.get(key);
        if (prev) window.clearTimeout(prev);

        const delay = Math.max(250, Number(this.settings.autoPushDebounceMs ?? 1200));
        const t = window.setTimeout(() => {
          void this.autoPushFile(af).catch((e: any) => {
            // Keep failures quiet-ish; this should never block the editor.
            // eslint-disable-next-line no-console
            console.warn('[sx-obsidian-db] auto-push failed', af.path, e);
          });
          this._autoPushTimers.delete(key);
        }, delay);

        this._autoPushTimers.set(key, t);
      })
    );
  }

  async loadSettings(): Promise<void> {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }
}
