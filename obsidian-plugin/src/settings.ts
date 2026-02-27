import { App, Notice, PluginSettingTab, Setting, TFile, TFolder, normalizePath } from 'obsidian';
import type SxDbPlugin from './main';
import { WORKFLOW_STATUSES } from './libraryCore';
import { copyToClipboard } from './shared/clipboard';
import { clearMarkdownInFolder, collectMarkdownFiles, ensureFolder, slugFolderName } from './shared/vaultFs';
import { DEFAULT_LIBRARY_COLUMNS, DEFAULT_LIBRARY_COLUMN_ORDER } from './librarySchema';

export interface SxDbSettings {
  apiBaseUrl: string;
  activeSourceId: string;
  schemaIndexSafetyGuard: boolean;
  enforceProfileSourceAlignment: boolean;
  launcherProfileIndex: number;
  backendServerTarget: 'local' | 'cloud-session' | 'cloud-transaction';
  backendCommandShell: 'bash' | 'zsh' | 'sh' | 'powershell' | 'cmd';
  projectDocsPath: string;
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
  localPathlinkerGroup1: string;
  fetchQuery: string;
  fetchAuthorUniqueId: string; // legacy single-select (kept for backward compat)
  fetchAuthorUniqueIds: string[]; // preferred multi-select
  fetchStatuses: string[];

  // When enabled, do not create/overwrite notes whose frontmatter has media_missing: true.
  skipMissingMediaOnPull: boolean;
  
  // Autosave: when a user edits a note in the vault, automatically push it back to the DB.
  autoPushOnEdit: boolean;
  autoPushDebounceMs: number;
  /**
   * Compatibility option for migrations.
   * If true, auto-push also triggers for legacy split folders (bookmarks/authors) even when
   * vaultWriteStrategy is set to active-only.
   */
  autoPushLegacyFoldersInActiveOnly: boolean;

  // SX Library view UX
  libraryHoverVideoPreview: boolean;
  libraryHoverPreviewMuted: boolean;
  /**
   * Hover video size mode:
   * - scale: preserve TikTok-like base ratio and scale up/down by percentage.
   * - free: use explicit width/height values.
   */
  libraryHoverVideoResizeMode: 'scale' | 'free';
  libraryHoverVideoScalePct: number;
  libraryHoverPreviewWidth: number;
  libraryHoverPreviewHeight: number;
  libraryLinkCopyModifier: 'ctrl-cmd' | 'alt' | 'shift';
  libraryShowLinkChipActionButton: boolean;
  libraryLinkChipActionLabel: string;
  libraryLinkChipCommitOn: 'tab' | 'enter' | 'both';

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
   * - inline: open the note natively in a hover Obsidian leaf.
   * - split: open the note in a split tab (Obsidian-native view).
   * - popout: open the note in an Obsidian popout window leaf (Obsidian-native view)
   */
    libraryNotePeekEngine: 'inline' | 'split' | 'popout';
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

  // Cached source profile configs (synced from API → .env).
  profileConfigs: Record<number, {
    label: string;
    src_path: string;
    source_id: string;
    pathlinker_group: string;
    group_name: string;
    vault_name: string;
    vault_path: string;
    assets_path: string;
  }>;

  // Profiles tab scope behavior.
  // - false (default): show only profile(s) matching active source id
  // - true: troubleshooting override to show all profiles
  profilesShowAll: boolean;
}

export const DEFAULT_SETTINGS: SxDbSettings = {
  apiBaseUrl: 'http://127.0.0.1:8123',
  activeSourceId: 'default',
  schemaIndexSafetyGuard: true,
  enforceProfileSourceAlignment: true,
  launcherProfileIndex: 1,
  backendServerTarget: 'local',
  backendCommandShell: 'bash',
  projectDocsPath: 'docs/USAGE.md',
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
  localPathlinkerGroup1: '',
  fetchQuery: '',
  fetchAuthorUniqueId: '',
  fetchAuthorUniqueIds: [],
  fetchStatuses: [],

  skipMissingMediaOnPull: true,

  autoPushOnEdit: true,
  autoPushDebounceMs: 1200,
  autoPushLegacyFoldersInActiveOnly: false,

  libraryHoverVideoPreview: true,
  // Default: unmuted (requested), but note some systems may still block autoplay with sound.
  libraryHoverPreviewMuted: false,
  libraryHoverVideoResizeMode: 'scale',
  libraryHoverVideoScalePct: 100,
  // Default: portrait hover preview (roughly 9:16), “mini TikTok” sized.
  libraryHoverPreviewWidth: 240,
  libraryHoverPreviewHeight: 426,
  libraryLinkCopyModifier: 'ctrl-cmd',
  libraryShowLinkChipActionButton: true,
  libraryLinkChipActionLabel: 'Chipify',
  libraryLinkChipCommitOn: 'tab',

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

  libraryColumns: { ...DEFAULT_LIBRARY_COLUMNS },

  libraryColumnOrder: [...DEFAULT_LIBRARY_COLUMN_ORDER],
  libraryColumnWidths: {},
  profilesShowAll: false,
  profileConfigs: {}
};

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
      { id: 'database', label: 'Database' },
      { id: 'profiles', label: 'Profiles' },
      { id: 'dataflow', label: 'Data Flow' },
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
    const initial = tabs.some((t) => t.id === requested) ? requested : 'database';
    activate(initial);

    // ── Database tab: connection + schema/profile + backend launch ─────────
    {
      const el = panels.database;
      el.createEl('h3', { text: 'Database & Schema' });
      el.createEl('p', {
        text:
          'All DB/schema/profile controls are centralized here to reduce cross-profile mistakes. The schema-index safety guard blocks writes when source/profile indexes don’t match.'
      });

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

      const CUSTOM_SOURCE_OPTION = '__custom__';
      const sourceChoices = new Set<string>([String((this.plugin.settings as any).activeSourceId || 'default') || 'default']);
      const profileChoices = new Set<number>([Math.max(1, Number((this.plugin.settings as any).launcherProfileIndex || 1))]);
      let activeProfileSelect: HTMLSelectElement | null = null;
      let routingBadgeEl: HTMLDivElement | null = null;

      const sanitizeSourceId = (raw: string): string => {
        const cleaned = String(raw || '')
          .trim()
          .replace(/[^a-zA-Z0-9._-]/g, '');
        return cleaned || 'default';
      };

      const parseTrailingProfileIndex = (value: string): number | null => {
        const s = String(value || '').trim().toLowerCase();
        if (!s) return null;
        const m = s.match(/(?:^|[_-])(?:p)?(\d{1,2})$/);
        if (!m) return null;
        const n = Number(m[1]);
        if (!Number.isFinite(n) || n < 1) return null;
        return Math.floor(n);
      };

      const refreshRoutingBadge = () => {
        if (!routingBadgeEl) return;
        const routing = (this.plugin as any).getRoutingDebugInfo?.() || {};

        const configuredProfile = Number(routing?.configuredProfile ?? (this.plugin.settings as any).launcherProfileIndex ?? 1);
        const configuredSource = sanitizeSourceId(String(routing?.configuredSource || (this.plugin.settings as any).activeSourceId || 'default'));
        const effectiveProfile = Number(routing?.effectiveProfile ?? configuredProfile);
        const effectiveSource = sanitizeSourceId(String(routing?.effectiveSource || configuredSource));

        const guardOn = Boolean((this.plugin.settings as any).schemaIndexSafetyGuard ?? true);
        const alignOn = Boolean((this.plugin.settings as any).enforceProfileSourceAlignment ?? true);
        const mismatch = Boolean(routing?.mismatchDetected ?? false);

        const status = mismatch ? '⚠ mismatch' : '✅ affirmed';
        routingBadgeEl.removeClass('is-affirmed', 'is-warning');
        if (mismatch) routingBadgeEl.addClass('is-warning');
        else routingBadgeEl.addClass('is-affirmed');
        routingBadgeEl.setText(
          `${status} · configured #${Math.max(1, configuredProfile)} → ${configuredSource} · effective #${Math.max(1, effectiveProfile)} → ${effectiveSource} · guard ${guardOn ? 'ON' : 'OFF'} · alignment ${alignOn ? 'ON' : 'OFF'}`
        );
      };

      const profileSourceId = (idx: number): string => {
        const n = Math.max(1, Math.floor(Number(idx) || 1));
        const cached = (this.plugin.settings as any).profileConfigs?.[n];
        const sid = sanitizeSourceId(String(cached?.source_id || `assets_${n}`));
        return sid;
      };

      const refreshActiveProfileControl = () => {
        if (!activeProfileSelect) return;

        const current = Math.max(1, Number((this.plugin.settings as any).launcherProfileIndex || 1));
        profileChoices.add(current);

        // Add cached profile indexes when available.
        const cached = (this.plugin.settings as any).profileConfigs || {};
        for (const k of Object.keys(cached)) {
          const n = Number(k);
          if (Number.isFinite(n) && n >= 1) profileChoices.add(Math.floor(n));
        }

        const sorted = Array.from(profileChoices).sort((a, b) => a - b);
        activeProfileSelect.empty();
        for (const idx of sorted) {
          const sid = profileSourceId(idx);
          const label = String((this.plugin.settings as any).profileConfigs?.[idx]?.label || '').trim();
          const text = `#${idx} → ${sid}${label ? ` (${label})` : ''}`;
          activeProfileSelect.createEl('option', { value: String(idx), text });
        }

        activeProfileSelect.value = String(current);
        if (!activeProfileSelect.value && activeProfileSelect.options.length) {
          activeProfileSelect.value = activeProfileSelect.options[0].value;
        }
      };

      const applyUnifiedProfileSelection = async (idx: number, opts?: { notify?: boolean }) => {
        const n = Math.max(1, Math.floor(Number(idx) || 1));
        const sid = profileSourceId(n);

        (this.plugin.settings as any).launcherProfileIndex = n;
        (this.plugin.settings as any).activeSourceId = sid;
        // Reinforce safety invariants whenever user confirms active profile.
        (this.plugin.settings as any).enforceProfileSourceAlignment = true;
        (this.plugin.settings as any).schemaIndexSafetyGuard = true;

        profileChoices.add(n);
        sourceChoices.add(sid);

        await this.plugin.saveSettings();
        refreshActiveProfileControl();
        refreshRoutingBadge();

        if (opts?.notify) {
          new Notice(`Active profile confirmed: #${n} (${sid})`);
        }
      };

      new Setting(el)
        .setName('Active source profile (single control)')
        .setDesc('Primary selector. Choosing a profile automatically sets Profile index + Active source ID and re-enables schema safety guard + profile/source alignment.')
        .addDropdown((dd) => {
          activeProfileSelect = (dd as any).selectEl as HTMLSelectElement;
          refreshActiveProfileControl();
          dd.onChange(async (value) => {
            const idx = Number(value);
            if (!Number.isFinite(idx) || idx < 1) return;
            await applyUnifiedProfileSelection(Math.floor(idx));
          });
        })
        .addButton((btn) =>
          btn.setButtonText('Affirm now').setCta().onClick(async () => {
            const idx = Math.max(1, Number((this.plugin.settings as any).launcherProfileIndex || 1));
            await applyUnifiedProfileSelection(idx, { notify: true });
          })
        )
        .addButton((btn) =>
          btn.setButtonText('Reload profiles').onClick(async () => {
            try {
              const resp = await (this.plugin as any).apiRequest({ path: '/pipeline/profiles' });
              const data = resp.json as { profiles?: Array<{ index: number; source_id?: string; label?: string; src_path?: string; pathlinker_group?: string; group_name?: string; vault_name?: string; vault_path?: string; assets_path?: string }> };
              const rows = Array.isArray(data?.profiles) ? data.profiles : [];
              const cache: Record<number, any> = { ...(this.plugin.settings.profileConfigs || {}) };
              for (const p of rows) {
                const idx = Number(p?.index);
                if (!Number.isFinite(idx) || idx < 1) continue;
                profileChoices.add(Math.floor(idx));
                const existing = cache[Math.floor(idx)] || {};
                cache[Math.floor(idx)] = {
                  ...existing,
                  label: String(p?.label || existing.label || `profile_${Math.floor(idx)}`),
                  src_path: String(p?.src_path || existing.src_path || ''),
                  source_id: sanitizeSourceId(String(p?.source_id || existing.source_id || `assets_${Math.floor(idx)}`)),
                  pathlinker_group: String(p?.pathlinker_group || existing.pathlinker_group || ''),
                  group_name: String(p?.group_name || existing.group_name || ''),
                  vault_name: String(p?.vault_name || existing.vault_name || ''),
                  vault_path: String(p?.vault_path || existing.vault_path || ''),
                  assets_path: String(p?.assets_path || existing.assets_path || '')
                };
              }
              this.plugin.settings.profileConfigs = cache;
              await this.plugin.saveSettings();
              refreshActiveProfileControl();
              refreshRoutingBadge();
              new Notice(`Profiles reloaded (${rows.length}).`);
            } catch (e: any) {
              new Notice(`Reload profiles failed: ${String(e?.message ?? e)}`);
            }
          })
        );

      routingBadgeEl = el.createDiv({ cls: 'sxdb-source-routing-badge' });
      refreshRoutingBadge();
      refreshActiveProfileControl();

      el.createEl('h4', { text: 'Source registry' });
      el.createEl('p', {
        text: 'Manage backend sources and switch active source without manually typing IDs.'
      });

      const sourceWrap = el.createDiv({ cls: 'sxdb-source-picker sxdb-source-picker-card' });
      sourceWrap.createEl('div', {
        cls: 'sxdb-source-muted',
        text: 'Tip: pick a source below and set it active, or add a new source with a custom ID.'
      });
      const sourceRow = sourceWrap.createDiv({ cls: 'sxdb-source-row' });
      const sourceSel = sourceRow.createEl('select');
      sourceSel.style.minWidth = '260px';
      const reloadBtn = sourceRow.createEl('button', { text: 'Reload' });
      const activateBtn = sourceRow.createEl('button', { text: 'Set active' });
      const removeBtn = sourceRow.createEl('button', { text: 'Delete' });

      const createRow = sourceWrap.createDiv({ cls: 'sxdb-source-row sxdb-source-grid' });
      const idInput = createRow.createEl('input', { type: 'text', placeholder: 'source id' });
      const labelInput = createRow.createEl('input', { type: 'text', placeholder: 'label (optional)' });
      const addBtn = createRow.createEl('button', { text: 'Add source' });
      const makeDefaultBtn = createRow.createEl('button', { text: 'Set backend default' });

      let selectedSourceId = String((this.plugin.settings as any).activeSourceId || 'default');

      const loadSources = async () => {
        sourceSel.empty();
        sourceChoices.clear();
        try {
          const resp = await (this.plugin as any).apiRequest({ path: '/sources' });
          const data = resp.json as {
            sources?: Array<{ id: string; label?: string | null; is_default?: number | boolean }>;
            default_source_id?: string;
          };
          const rows = Array.isArray(data?.sources) ? data.sources : [];

          if (!rows.length) {
            const fallback = sanitizeSourceId(this.plugin.getActiveSourceId());
            sourceChoices.add(fallback);
            sourceSel.createEl('option', { value: fallback, text: fallback });
            sourceSel.value = fallback;
            selectedSourceId = sourceSel.value;
            refreshRoutingBadge();
            return;
          }

          for (const s of rows) {
            const sid = String(s?.id || '').trim();
            if (!sid) continue;
            sourceChoices.add(sid);
            const label = String(s?.label || '').trim();
            const isDef = Boolean(Number(s?.is_default || 0));
            const text = `${sid}${label && label !== sid ? ` — ${label}` : ''}${isDef ? '  (default)' : ''}`;
            sourceSel.createEl('option', { value: sid, text });
          }

          const desired = sanitizeSourceId(String((this.plugin.settings as any).activeSourceId || data?.default_source_id || 'default'));
          sourceChoices.add(desired);
          sourceSel.value = desired;
          if (!sourceSel.value && sourceSel.options.length) sourceSel.value = sourceSel.options[0].value;
          selectedSourceId = sourceSel.value || desired;
          refreshRoutingBadge();
        } catch {
          const fallback = sanitizeSourceId(this.plugin.getActiveSourceId());
          sourceChoices.add(fallback);
          sourceSel.createEl('option', { value: fallback, text: fallback });
          sourceSel.value = fallback;
          selectedSourceId = sourceSel.value;
          refreshRoutingBadge();
        }
      };

      sourceSel.addEventListener('change', () => {
        selectedSourceId = String(sourceSel.value || '').trim() || 'default';
      });

      reloadBtn.addEventListener('click', () => {
        void loadSources();
      });

      activateBtn.addEventListener('click', async () => {
        const sid = String(selectedSourceId || sourceSel.value || '').trim();
        if (!sid) return;
        const clean = sanitizeSourceId(sid);
        (this.plugin.settings as any).activeSourceId = clean;
        const sourceIdx = parseTrailingProfileIndex(clean);
        if (sourceIdx != null) {
          (this.plugin.settings as any).launcherProfileIndex = sourceIdx;
          profileChoices.add(sourceIdx);
        }
        sourceChoices.add(clean);
        await this.plugin.saveSettings();
        refreshActiveProfileControl();
        refreshRoutingBadge();
        new Notice(`Active source set: ${clean}${sourceIdx != null ? ` (profile #${sourceIdx})` : ''}`);
      });

      removeBtn.addEventListener('click', async () => {
        const sid = String(selectedSourceId || sourceSel.value || '').trim();
        if (!sid) return;
        try {
          await (this.plugin as any).apiRequest({ path: `/sources/${encodeURIComponent(sid)}`, method: 'DELETE' });
          if (String((this.plugin.settings as any).activeSourceId || '') === sid) {
            (this.plugin.settings as any).activeSourceId = 'default';
            await this.plugin.saveSettings();
          }
          await loadSources();
          new Notice(`Deleted source: ${sid}`);
        } catch (e: any) {
          new Notice(`Delete failed: ${String(e?.message ?? e)}`);
        }
      });

      addBtn.addEventListener('click', async () => {
        const rawId = String(idInput.value || '').trim();
        if (!rawId) {
          new Notice('Source id is required.');
          return;
        }
        const sid = sanitizeSourceId(rawId);
        const label = String(labelInput.value || '').trim();
        try {
          await (this.plugin as any).apiRequest({
            path: '/sources',
            method: 'POST',
            body: JSON.stringify({ id: sid, label: label || sid, enabled: true }),
            headers: { 'Content-Type': 'application/json' }
          });
          idInput.value = '';
          labelInput.value = '';
          await loadSources();
          sourceSel.value = sid;
          selectedSourceId = sid;
          sourceChoices.add(sid);
          refreshRoutingBadge();
          new Notice(`Source added: ${sid}`);
        } catch (e: any) {
          new Notice(`Add source failed: ${String(e?.message ?? e)}`);
        }
      });

      makeDefaultBtn.addEventListener('click', async () => {
        const sid = String(selectedSourceId || sourceSel.value || '').trim();
        if (!sid) return;
        try {
          await (this.plugin as any).apiRequest({ path: `/sources/${encodeURIComponent(sid)}/activate`, method: 'POST' });
          await loadSources();
          new Notice(`Backend default source set: ${sid}`);
        } catch (e: any) {
          new Notice(`Set default failed: ${String(e?.message ?? e)}`);
        }
      });

      void loadSources();

      new Setting(el)
        .setName('Test connection')
        .setDesc('Checks /health and prints database stats from /stats.')
        .addButton((btn) =>
          btn.setButtonText('Test').setCta().onClick(async () => {
            try {
              const health = await (this.plugin as any).apiRequest({ path: '/health' });
              const stats = await (this.plugin as any).apiRequest({ path: '/stats' });
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
            window.open((this.plugin as any).apiUrl('/docs'));
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

    // ── Profiles tab: per-source PathLinker / vault / DB config ────────────
    {
      const el = panels.profiles;
      el.createEl('h3', { text: 'Source Profiles' });
      el.createEl('p', {
        text: 'Each source profile maps to a vault, PathLinker group, and database configuration. Changes are saved back to the backend .env file.',
        cls: 'setting-item-description'
      });

      const sanitizeSourceId = (raw: string): string => {
        const cleaned = String(raw || '')
          .trim()
          .replace(/[^a-zA-Z0-9._-]/g, '');
        return cleaned || 'default';
      };

      const getActiveSourceForProfiles = (): string => {
        const effective = (this.plugin as any).getEffectiveSourceId?.();
        const explicit = String((this.plugin.settings as any).activeSourceId || 'default');
        return sanitizeSourceId(String(effective || explicit || 'default'));
      };

      const profilesHost = el.createDiv({ cls: 'sxdb-profiles-host' });
      const statusBar = el.createDiv({ cls: 'sxdb-profiles-status' });

      new Setting(el)
        .setName('Show all profiles')
        .setDesc('Troubleshooting override. Default behavior shows only profile(s) matching the active source from Database settings.')
        .addToggle((toggle) =>
          toggle.setValue(Boolean((this.plugin.settings as any).profilesShowAll)).onChange(async (value) => {
            (this.plugin.settings as any).profilesShowAll = value;
            await this.plugin.saveSettings();
            void loadProfiles();
          })
        );

      const renderProfileCard = (
        host: HTMLElement,
        profile: any,
        onSave: (idx: number, updates: Record<string, string>) => Promise<void>
      ) => {
        const card = host.createDiv({ cls: 'sxdb-profile-card' });

        // ── Header ──
        const header = card.createDiv({ cls: 'sxdb-profile-header' });
        header.createEl('span', {
          text: `#${profile.index}`,
          cls: 'sxdb-profile-badge'
        });
        header.createEl('span', {
          text: String(profile.label || `Profile ${profile.index}`),
          cls: 'sxdb-profile-title'
        });
        header.createEl('span', {
          text: profile.source_id || '',
          cls: 'sxdb-profile-source-id'
        });

        // ── Editable fields ──
        const fields: Array<{
          key: string;
          label: string;
          desc: string;
          value: string;
          section: string;
        }> = [
          { key: 'label', label: 'Label', desc: 'Human-readable profile name', value: profile.label || '', section: 'source' },
          { key: 'src_path', label: 'Source path', desc: 'Root path where media is located (Linux/WSL)', value: profile.src_path || '', section: 'source' },
          { key: 'source_id', label: 'Source ID', desc: 'Unique source identifier (e.g. assets_1)', value: profile.source_id || '', section: 'source' },
          { key: 'assets_path', label: 'Assets path', desc: 'SchedulerX assets directory', value: profile.assets_path || '', section: 'source' },
          { key: 'pathlinker_group', label: 'PathLinker group', desc: 'group: prefix for wikilinks (e.g. alexnova/data)', value: profile.pathlinker_group || '', section: 'pathlinker' },
          { key: 'group_name', label: 'Group name', desc: 'Source root dir name used by external file linker', value: profile.group_name || '', section: 'pathlinker' },
          { key: 'vault_name', label: 'Vault name', desc: 'Obsidian vault name for this profile', value: profile.vault_name || '', section: 'vault' },
          { key: 'vault_path', label: 'Vault path', desc: 'Vault filesystem path', value: profile.vault_path || '', section: 'vault' },
        ];

        const pendingEdits: Record<string, string> = {};
        let currentSection = '';

        for (const f of fields) {
          if (f.section !== currentSection) {
            currentSection = f.section;
            const sectionLabel = {
              source: '📁 Source',
              pathlinker: '🔗 PathLinker',
              vault: '🏠 Vault'
            }[f.section] || f.section;
            card.createEl('div', { text: sectionLabel, cls: 'sxdb-profile-section-label' });
          }

          new Setting(card)
            .setName(f.label)
            .setDesc(f.desc)
            .addText((text) =>
              text
                .setPlaceholder(f.label)
                .setValue(f.value)
                .onChange((value) => {
                  pendingEdits[f.key] = value.trim();
                })
            );
        }

        // ── DB Profiles (read-only summary) ──
        const dbSection = card.createDiv({ cls: 'sxdb-profile-db-section' });
        dbSection.createEl('div', { text: '🗄️ Database Profiles', cls: 'sxdb-profile-section-label' });
        const dbProfiles = profile.db_profiles || {};
        for (const [mode, info] of Object.entries(dbProfiles) as [string, any][]) {
          if (mode === 'sql') continue;
          const row = dbSection.createDiv({ cls: 'sxdb-profile-db-row' });
          const statusDot = info?.configured ? '🟢' : '⚪';
          row.createEl('span', {
            text: `${statusDot} ${mode.charAt(0).toUpperCase() + mode.slice(1)}`,
            cls: 'sxdb-profile-db-mode'
          });
          row.createEl('span', {
            text: info?.alias || '(not configured)',
            cls: 'sxdb-profile-db-alias'
          });
        }

        // ── Save button ──
        const actions = card.createDiv({ cls: 'sxdb-profile-actions' });
        const saveBtn = actions.createEl('button', {
          text: 'Save to .env',
          cls: 'sxdb-profile-save-btn mod-cta'
        });
        const cardStatus = actions.createEl('span', {
          text: '',
          cls: 'sxdb-profile-save-status'
        });

        saveBtn.addEventListener('click', async () => {
          if (Object.keys(pendingEdits).length === 0) {
            cardStatus.setText('No changes to save');
            cardStatus.classList.add('sxdb-status-info');
            setTimeout(() => { cardStatus.setText(''); cardStatus.classList.remove('sxdb-status-info'); }, 2000);
            return;
          }
          saveBtn.disabled = true;
          cardStatus.setText('Saving…');
          try {
            await onSave(profile.index, pendingEdits);
            cardStatus.setText('✓ Saved');
            cardStatus.classList.add('sxdb-status-ok');
            // Clear pending
            for (const k of Object.keys(pendingEdits)) delete pendingEdits[k];
          } catch (e: any) {
            cardStatus.setText(`✗ ${e?.message || 'Save failed'}`);
            cardStatus.classList.add('sxdb-status-error');
          } finally {
            saveBtn.disabled = false;
            setTimeout(() => {
              cardStatus.setText('');
              cardStatus.classList.remove('sxdb-status-ok', 'sxdb-status-error', 'sxdb-status-info');
            }, 3000);
          }
        });
      };

      // ── Load profiles from API ──
      const loadProfiles = async () => {
        profilesHost.empty();
        statusBar.empty();
        statusBar.setText('Loading profiles…');

        try {
          const base = String(this.plugin.settings.apiBaseUrl || 'http://127.0.0.1:8123').replace(/\/+$/, '');
          const sourceId = (this.plugin as any).getEffectiveSourceId?.() || 'default';
          const profileIdx = String(Math.max(1, Number((this.plugin as any).getEffectiveProfileIndex?.() || 1)));
          const res = await fetch(`${base}/pipeline/profiles`, {
            headers: { 'X-SX-Source-ID': sourceId, 'X-SX-Profile-Index': profileIdx },
            signal: AbortSignal.timeout(8000)
          });
          if (!res.ok) throw new Error(`API returned ${res.status}`);
          const data = await res.json();
          const profiles: any[] = data.profiles || [];
          const activeSource = getActiveSourceForProfiles();
          const showAll = Boolean((this.plugin.settings as any).profilesShowAll);

          let shownProfiles = showAll
            ? profiles
            : profiles.filter((p) => sanitizeSourceId(String(p?.source_id || '')) === activeSource);

          // Safe fallback: if source mapping is missing, render all profiles rather than leaving UI blank.
          let fallbackToAll = false;
          if (!showAll && shownProfiles.length === 0 && profiles.length > 0) {
            shownProfiles = profiles;
            fallbackToAll = true;
          }

          const filterLabel = showAll
            ? 'show-all (override enabled)'
            : fallbackToAll
              ? 'active-only (fallback to all: no source mapping)'
              : 'active-only';
          statusBar.setText(
            `Active source: ${activeSource} · filter: ${filterLabel} · showing ${shownProfiles.length}/${profiles.length} profile(s) from ${data.env_path || '.env'}`
          );

          if (profiles.length === 0) {
            profilesHost.createEl('p', {
              text: 'No source profiles found. Add SRC_PATH_N entries to your .env file.',
              cls: 'sxdb-profiles-empty'
            });
            return;
          }

          // Cache profile configs locally
          const cache: Record<number, any> = {};
          for (const p of profiles) cache[p.index] = p;
          this.plugin.settings.profileConfigs = cache;
          await this.plugin.saveSettings();

          for (const p of shownProfiles) {
            renderProfileCard(profilesHost, p, async (idx, updates) => {
              const putRes = await fetch(`${base}/config/profiles/${idx}`, {
                method: 'PUT',
                headers: {
                  'Content-Type': 'application/json',
                  'X-SX-Source-ID': sourceId,
                  'X-SX-Profile-Index': profileIdx
                },
                body: JSON.stringify(updates),
                signal: AbortSignal.timeout(8000),
              });
              if (!putRes.ok) {
                const err = await putRes.json().catch(() => ({}));
                throw new Error(err.detail || `API returned ${putRes.status}`);
              }
              const result = await putRes.json();
              // Update local cache with the returned profile
              if (result.profile) {
                this.plugin.settings.profileConfigs[idx] = result.profile;
                await this.plugin.saveSettings();
              }
              new Notice(`Profile #${idx} saved to .env`);
            });
          }
        } catch (e: any) {
          statusBar.setText('');
          profilesHost.createEl('p', {
            text: `Failed to load profiles: ${e?.message || 'Unknown error'}. Is the API server running?`,
            cls: 'sxdb-profiles-error'
          });
        }
      };

      // Refresh button
      new Setting(el)
        .setName('Refresh')
        .setDesc('Reload profiles from the backend API')
        .addButton((btn) =>
          btn.setButtonText('↻ Reload').onClick(() => void loadProfiles())
        );

      void loadProfiles();
    }

    // ── Data Flow tab: fetch + sync/push semantics in one place ────────────
    {
      const el = panels.dataflow;
      el.createEl('h3', { text: 'Data Flow (Sync / Fetch / Push)' });
      el.createEl('h4', { text: 'Definitions' });
      el.createEl('p', {
        text:
          'Sync = overall two-way workflow. Fetch = DB → Vault note materialization. Push = Vault → DB persistence of your edited notes.'
      });
      el.createEl('p', {
        text:
          'This page groups all transfer controls together so behavior and safety settings stay coherent.'
      });
      el.createEl('h4', { text: 'Fetch (DB → Vault)' });
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
        .setName('PathLinker group fallback (legacy)')
        .setDesc(
          'Legacy fallback: used only when no per-profile PathLinker group is set in the Profiles tab. Prefer configuring this in Settings → Profiles.'
        )
        .addText((text) =>
          text
            .setPlaceholder('e.g. alexnova')
            .setValue(String(this.plugin.settings.localPathlinkerGroup1 || ''))
            .onChange(async (value) => {
              this.plugin.settings.localPathlinkerGroup1 = String(value || '').trim();
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
        const normalizeAuthors = (authorsRaw: Array<any>) => {
          return (authorsRaw || [])
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
        };

        try {
          const resp = await (this.plugin as any).apiRequest({
            path: '/authors',
            query: { limit: '2000', order: 'count' }
          });
          const data = resp.json as {
            authors: Array<{
              author_id?: string | null;
              author_unique_id?: string | null;
              author_name?: string | null;
              items_count?: number | null;
            }>;
          };
          const authors = normalizeAuthors(data?.authors ?? []);

          renderAuthors(authors, authorSearch.value);
          authorSearch.addEventListener('input', () => renderAuthors(authors, authorSearch.value));
        } catch (e1: any) {
          try {
            const resp2 = await (this.plugin as any).apiRequest({
              path: '/items',
              query: { limit: '2000', offset: '0', order: 'author' }
            });
            const data2 = resp2.json as {
              items: Array<{
                author_id?: string | null;
                author_unique_id?: string | null;
                author_name?: string | null;
              }>;
            };
            const counts = new Map<string, number>();
            const meta = new Map<string, { uid: string; aid: string; name: string }>();
            for (const it of data2?.items ?? []) {
              const uid = String(it.author_unique_id || '').trim();
              if (!uid) continue;
              const aid = String(it.author_id || '').trim();
              const name = String(it.author_name || '').trim();
              counts.set(uid, (counts.get(uid) || 0) + 1);
              if (!meta.has(uid)) meta.set(uid, { uid, aid, name });
            }
            const fallbackRaw = Array.from(meta.values()).map((m) => ({
              author_unique_id: m.uid,
              author_id: m.aid,
              author_name: m.name,
              items_count: counts.get(m.uid) || 0
            }));
            const authors = normalizeAuthors(fallbackRaw).sort((a, b) => a.label.localeCompare(b.label));
            renderAuthors(authors, authorSearch.value);
            authorSearch.addEventListener('input', () => renderAuthors(authors, authorSearch.value));
            new Notice('Loaded author list via /items fallback.');
          } catch (e2: any) {
            const msg = String(e2?.message || e1?.message || 'Unknown API error');
            authorList.createEl('em', { text: `Authors list unavailable (${msg}). You can still fetch without selecting authors.` });
          }
        }
      })();

      // Fetch action
      new Setting(el)
        .setName('DB → vault: fetch notes')
        .setDesc('Fetches notes from the API and writes them into your vault (destination depends on Vault write strategy).')
        .addButton((btn) =>
          btn.setButtonText('Fetch now').setCta().onClick(async () => {
            const batch = Math.max(10, this.plugin.settings.syncBatchSize ?? 200);
            const maxItems = Math.max(0, this.plugin.settings.syncMaxItems ?? 2000);
            const replace = Boolean(this.plugin.settings.syncReplaceOnPull);
            const strategy = String(this.plugin.settings.vaultWriteStrategy || 'split');

            const q = (this.plugin.settings.fetchQuery || '').trim();
            const statuses = Array.isArray(this.plugin.settings.fetchStatuses) ? this.plugin.settings.fetchStatuses : [];
            const force = Boolean(this.plugin.settings.fetchForceRegenerate);
            const pathlinkerGroup = String(this.plugin.settings.localPathlinkerGroup1 || '').trim();

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
                if (pathlinkerGroup) params.pathlinker_group = pathlinkerGroup;

                // Use explicit mode routing rather than just bookmarked_only.
                // - bookmarks: server-side filter
                // - authors/both: fetch and route client-side
                if (mode === 'bookmarks') params.bookmarked_only = 'true';
                else params.bookmarked_only = 'false';

                const resp = await (this.plugin as any).apiRequest({ path: '/notes', query: params });
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

    // ── Database tab (continued): server control ───────────────────────────
    {
      const el = panels.database;
      new Setting(el)
        .setName('Server target')
        .setDesc('Choose which backend profile to launch from the plugin.')
        .addDropdown((dd) => {
          dd.addOption('local', 'Local (LOCAL_N)');
          dd.addOption('cloud-session', 'Cloud (SESSION_N)');
          dd.addOption('cloud-transaction', 'Cloud (TRANSACTION_N)');
          dd.setValue(String((this.plugin.settings as any).backendServerTarget || 'local'));
          dd.onChange(async (v) => {
            (this.plugin.settings as any).backendServerTarget =
              v === 'cloud-session' || v === 'cloud-transaction' ? v : 'local';
            await this.plugin.saveSettings();
          });
        });

      new Setting(el)
        .setName('Command shell')
        .setDesc('Shell used to run backend control commands from the plugin.')
        .addDropdown((dd) => {
          dd.addOption('bash', 'bash');
          dd.addOption('zsh', 'zsh');
          dd.addOption('sh', 'sh');
          dd.addOption('powershell', 'PowerShell');
          dd.addOption('cmd', 'Command Prompt (cmd)');
          dd.setValue(String((this.plugin.settings as any).backendCommandShell || 'bash'));
          dd.onChange(async (v) => {
            (this.plugin.settings as any).backendCommandShell =
              v === 'zsh' || v === 'sh' || v === 'powershell' || v === 'cmd' ? v : 'bash';
            await this.plugin.saveSettings();
          });
        });

      el.createEl('h3', { text: 'Backend server control' });
      el.createEl('p', {
        text: 'Launch/update directly from the plugin using sxctl in your vault/workspace root.'
      });

      new Setting(el)
        .setName('Server lifecycle')
        .setDesc('Start/stop/status for the selected server target.')
        .addButton((btn) =>
          btn.setButtonText('Start selected').setCta().onClick(() => {
            const pid = this.plugin.manifest?.id || 'sx-obsidian-db';
            (this.app as any).commands?.executeCommandById?.(`${pid}:sxdb-server-start-selected`);
          })
        )
        .addButton((btn) =>
          btn.setButtonText('Stop').onClick(() => {
            const pid = this.plugin.manifest?.id || 'sx-obsidian-db';
            (this.app as any).commands?.executeCommandById?.(`${pid}:sxdb-server-stop`);
          })
        )
        .addButton((btn) =>
          btn.setButtonText('Status').onClick(() => {
            const pid = this.plugin.manifest?.id || 'sx-obsidian-db';
            (this.app as any).commands?.executeCommandById?.(`${pid}:sxdb-server-status`);
          })
        );

      new Setting(el)
        .setName('Plugin maintenance')
        .setDesc('Build/update the plugin via sxctl.')
        .addButton((btn) =>
          btn.setButtonText('Update plugin').onClick(() => {
            const pid = this.plugin.manifest?.id || 'sx-obsidian-db';
            (this.app as any).commands?.executeCommandById?.(`${pid}:sxdb-plugin-update`);
          })
        );

      el.createEl('h3', { text: 'Project documentation' });

      new Setting(el)
        .setName('Project docs file')
        .setDesc('Vault-relative docs landing page to open from the plugin.')
        .addText((text) =>
          text
            .setPlaceholder('docs/USAGE.md')
            .setValue(String((this.plugin.settings as any).projectDocsPath || 'docs/USAGE.md'))
            .onChange(async (v) => {
              (this.plugin.settings as any).projectDocsPath = String(v || '').trim() || 'docs/USAGE.md';
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Open docs')
        .setDesc('Open project docs (not just API endpoints).')
        .addButton((btn) =>
          btn.setButtonText('Project docs').setCta().onClick(() => {
            const pid = this.plugin.manifest?.id || 'sx-obsidian-db';
            (this.app as any).commands?.executeCommandById?.(`${pid}:sxdb-open-project-docs`);
          })
        )
        .addButton((btn) =>
          btn.setButtonText('API docs').onClick(() => {
            window.open((this.plugin as any).apiUrl('/docs'));
          })
        );
    }

    // ── Data Flow tab (continued): sync/push controls ──────────────────────
    {
      const el = panels.dataflow;
      el.createEl('h3', { text: 'Sync / Push Controls' });
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
          'When enabled, edits you make to notes under _db folders are automatically pushed to SQLite (vault → DB), creating a backup that survives template re-syncs.'
        )
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.autoPushOnEdit)).onChange(async (value) => {
            this.plugin.settings.autoPushOnEdit = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Auto-push legacy folders in Active-only mode')
        .setDesc(
          'When Vault write strategy is Active-only, also auto-push edits made in legacy split folders (_db/bookmarks, _db/authors). Disable if you want strict canonical edits only.'
        )
        .addToggle((toggle) =>
          toggle
            .setValue(Boolean(this.plugin.settings.autoPushLegacyFoldersInActiveOnly))
            .onChange(async (value) => {
              this.plugin.settings.autoPushLegacyFoldersInActiveOnly = value;
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
                await (this.plugin as any).apiRequest({
                  path: `/items/${encodeURIComponent(id)}/note-md`,
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

    // ── Views tab ─────────────────────────────────────────────────────────
    {
      const el = panels.views;
      el.createEl('h3', { text: 'Views' });
      el.createEl('p', { text: 'Customize SX Library view behavior and appearance.' });

      el.createEl('h4', { text: 'ID column' });
      new Setting(el)
        .setName('Table cell wrapping')
        .setDesc('Controls wrapping/overflow behavior across SX Library table cells (except action buttons).')
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
          dd.addOption('inline', 'Inline (Hover Obsidian leaf)');
          dd.addOption('split', 'Split tab (Obsidian leaf)');
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
        .setDesc('Choose either ratio-preserving scale (from TikTok-like default) or free width/height size.')
        .addDropdown((dd) => {
          dd.addOption('scale', 'Scale from TikTok default ratio');
          dd.addOption('free', 'Free width/height');
          dd.setValue((this.plugin.settings as any).libraryHoverVideoResizeMode || 'scale');
          dd.onChange(async (v) => {
            const next = v === 'free' ? 'free' : 'scale';
            (this.plugin.settings as any).libraryHoverVideoResizeMode = next;
            await this.plugin.saveSettings();
            this.display();
          });
        })
        .addText((text) =>
          text
            .setPlaceholder('scale %')
            .setValue(String((this.plugin.settings as any).libraryHoverVideoScalePct ?? 100))
            .onChange(async (v) => {
              const n = Number(v);
              (this.plugin.settings as any).libraryHoverVideoScalePct = Number.isFinite(n) ? Math.max(40, Math.min(300, Math.floor(n))) : 100;
              await this.plugin.saveSettings();
            })
        )
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

      new Setting(el)
        .setName('Metadata links: modifier-click copies URL')
        .setDesc('Direct click opens links. Hold this key while clicking a metadata URL to copy it instead.')
        .addDropdown((dd) => {
          dd.addOption('ctrl-cmd', 'Ctrl (Windows/Linux) / Cmd (macOS)');
          dd.addOption('alt', 'Alt / Option');
          dd.addOption('shift', 'Shift');
          dd.setValue(this.plugin.settings.libraryLinkCopyModifier || 'ctrl-cmd');
          dd.onChange(async (v) => {
            const next = v === 'alt' || v === 'shift' ? (v as any) : 'ctrl-cmd';
            this.plugin.settings.libraryLinkCopyModifier = next;
            await this.plugin.saveSettings();
          });
        });

      new Setting(el)
        .setName('Show smart-link action button')
        .setDesc('Shows the per-field action button next to URL inputs. Disable for a cleaner table UI.')
        .addToggle((toggle) =>
          toggle.setValue(Boolean(this.plugin.settings.libraryShowLinkChipActionButton ?? true)).onChange(async (value) => {
            this.plugin.settings.libraryShowLinkChipActionButton = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Smart-link action label')
        .setDesc('Button text shown next to metadata URL inputs to convert values into clickable chips.')
        .addText((text) =>
          text
            .setPlaceholder('Chipify')
            .setValue(this.plugin.settings.libraryLinkChipActionLabel || 'Chipify')
            .onChange(async (v) => {
              this.plugin.settings.libraryLinkChipActionLabel = String(v || '').trim() || 'Chipify';
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Smart-link commit key')
        .setDesc('Pressing this key in URL inputs converts current value into smart chips.')
        .addDropdown((dd) => {
          dd.addOption('tab', 'Tab');
          dd.addOption('enter', 'Enter');
          dd.addOption('both', 'Tab or Enter');
          dd.setValue(this.plugin.settings.libraryLinkChipCommitOn || 'tab');
          dd.onChange(async (v) => {
            const next = v === 'enter' || v === 'both' ? (v as any) : 'tab';
            this.plugin.settings.libraryLinkChipCommitOn = next;
            await this.plugin.saveSettings();
          });
        });

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
        const payload = {
          apply,
          confirm: apply ? String(confirmText || '') : '',
          filters: buildFilters(),
          reset_user_meta: resetMeta,
          reset_user_notes: resetUserNotes,
          reset_cached_notes: resetCachedNotes
        };

        try {
          const resp = await (this.plugin as any).apiRequest({
            path: '/danger/reset',
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

      el.createEl('h4', { text: 'Routing overrides (advanced)' });
      el.createEl('p', {
        text:
          'Most users should use “Active source profile (single control)” in Database. Use these only for troubleshooting or deliberate overrides.'
      });

      const sanitizeSourceIdAdvanced = (raw: string): string => {
        const cleaned = String(raw || '')
          .trim()
          .replace(/[^a-zA-Z0-9._-]/g, '');
        return cleaned || 'default';
      };

      new Setting(el)
        .setName('Active source ID (advanced override)')
        .setDesc('Manual override for request source routing. Single-profile selector will reset this to profile-canonical source when affirmed.')
        .addText((text) =>
          text
            .setPlaceholder('assets_1')
            .setValue(String((this.plugin.settings as any).activeSourceId || 'default'))
            .onChange(async (value) => {
              (this.plugin.settings as any).activeSourceId = sanitizeSourceIdAdvanced(value);
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Profile index (_N)')
        .setDesc('Manual override for routing/launch commands. Usually managed by the single profile control.')
        .addText((text) =>
          text
            .setPlaceholder('1')
            .setValue(String((this.plugin.settings as any).launcherProfileIndex ?? 1))
            .onChange(async (v) => {
              const n = Number(v);
              (this.plugin.settings as any).launcherProfileIndex = Number.isFinite(n) && n >= 1 ? Math.floor(n) : 1;
              await this.plugin.saveSettings();
            })
        );

      new Setting(el)
        .setName('Schema-index safety guard')
        .setDesc('Blocks writes if source/profile indexes conflict. Keep ON unless actively diagnosing behavior.')
        .addToggle((toggle) =>
          toggle.setValue(Boolean((this.plugin.settings as any).schemaIndexSafetyGuard)).onChange(async (value) => {
            (this.plugin.settings as any).schemaIndexSafetyGuard = value;
            await this.plugin.saveSettings();
          })
        );

      new Setting(el)
        .setName('Auto-align source to profile index')
        .setDesc('Keeps routing deterministic by deriving source from profile when needed. Recommended ON.')
        .addToggle((toggle) =>
          toggle.setValue(Boolean((this.plugin.settings as any).enforceProfileSourceAlignment ?? true)).onChange(async (value) => {
            (this.plugin.settings as any).enforceProfileSourceAlignment = value;
            await this.plugin.saveSettings();
          })
        );

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
