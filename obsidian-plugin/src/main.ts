import { App, Notice, Plugin, requestUrl, TFile, normalizePath } from 'obsidian';
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
import { copyToClipboard } from './shared/clipboard';
import { extractIdFromFrontmatter, extractUserMetaPayload } from './shared/frontmatterMeta';
import { PinByIdModal, SearchModal } from './modals';

export default class SxDbPlugin extends Plugin {
  settings: SxDbSettings = DEFAULT_SETTINGS;

  // Non-persisted UI hint for the settings tab implementation.
  uiActiveSettingsTabId: string | null = null;

  private _recentWrites: Map<string, number> = new Map();
  private _autoPushTimers: Map<string, number> = new Map();
  private _autoPushLegacyWarned: Set<string> = new Set();

  private getConfiguredSourceId(): string {
    const raw = String((this.settings as any).activeSourceId ?? '').trim();
    const cleaned = raw.replace(/[^a-zA-Z0-9._-]/g, '');
    return cleaned || 'default';
  }

  getActiveSourceId(): string {
    // Never silently rewrite source IDs. If the user picked assets_2, keep assets_2.
    return this.getConfiguredSourceId();
  }

  getPathlinkerGroupOverride(): string | null {
    // Per-profile PathLinker group (from cached profile configs, synced via Profiles tab).
    const idx = this.getConfiguredProfileIndex();
    if (idx != null) {
      const cached = (this.settings as any).profileConfigs?.[idx];
      if (cached?.pathlinker_group) {
        const cleaned = String(cached.pathlinker_group).replace(/[^a-zA-Z0-9._/-]/g, '').replace(/^\/+|\/+$/g, '');
        if (cleaned) return cleaned;
      }
    }
    // Legacy fallback: single-field setting from Data Flow tab.
    const raw = String((this.settings as any).localPathlinkerGroup1 ?? '').trim();
    if (!raw) return null;
    const cleaned = raw.replace(/[^a-zA-Z0-9._/-]/g, '').replace(/^\/+|\/+$/g, '');
    return cleaned || null;
  }

  getEffectiveSourceId(): string {
    const configured = this.getConfiguredSourceId();
    if (!Boolean((this.settings as any).enforceProfileSourceAlignment ?? true)) return configured;

    const configuredIdx = this.parseTrailingProfileIndex(configured);
    // Explicit indexed sources (e.g. assets_2) should win to avoid unintended
    // fallback to profile #1 when launcherProfileIndex is stale.
    if (configuredIdx != null) return configured;

    const profileIdx = this.getConfiguredProfileIndex();
    if (profileIdx == null) return configured;

    // In multi-profile mode, route only generic sources to profile-canonical source.
    if (configured === 'default' || /^assets$/i.test(configured)) {
      return `assets_${profileIdx}`;
    }

    return configured;
  }

  getRoutingDebugInfo(): {
    configuredSource: string;
    configuredProfile: number | null;
    configuredSourceIndex: number | null;
    effectiveSource: string;
    effectiveProfile: number | null;
    effectiveSourceIndex: number | null;
    alignmentEnabled: boolean;
    schemaGuardEnabled: boolean;
    mismatchDetected: boolean;
    effectiveSourceAdjusted: boolean;
  } {
    const configuredSource = this.getConfiguredSourceId();
    const configuredProfile = this.getConfiguredProfileIndex();
    const configuredSourceIndex = this.parseTrailingProfileIndex(configuredSource);
    const effectiveSource = this.getEffectiveSourceId();
    const effectiveProfile = this.getEffectiveProfileIndex();
    const effectiveSourceIndex = this.parseTrailingProfileIndex(effectiveSource);

    const mismatchDetected = configuredProfile != null
      && configuredSourceIndex != null
      && configuredSourceIndex !== configuredProfile;

    return {
      configuredSource,
      configuredProfile,
      configuredSourceIndex,
      effectiveSource,
      effectiveProfile,
      effectiveSourceIndex,
      alignmentEnabled: Boolean((this.settings as any).enforceProfileSourceAlignment ?? true),
      schemaGuardEnabled: Boolean((this.settings as any).schemaIndexSafetyGuard ?? true),
      mismatchDetected,
      effectiveSourceAdjusted: configuredSource !== effectiveSource
    };
  }

  async affirmAlignedSchemaContext(): Promise<{ profileIndex: number; sourceId: string }> {
    const configuredProfile = this.getConfiguredProfileIndex();
    const profileIndex = configuredProfile != null ? configuredProfile : 1;
    const cached = (this.settings as any).profileConfigs?.[profileIndex];
    const fromProfile = String(cached?.source_id || '').trim();
    const fallback = `assets_${profileIndex}`;
    const sourceId = (fromProfile || fallback).replace(/[^a-zA-Z0-9._-]/g, '') || fallback;

    (this.settings as any).launcherProfileIndex = profileIndex;
    (this.settings as any).activeSourceId = sourceId;
    (this.settings as any).enforceProfileSourceAlignment = true;
    (this.settings as any).schemaIndexSafetyGuard = true;

    await this.saveSettings();
    return { profileIndex, sourceId };
  }

  private getConfiguredProfileIndex(): number | null {
    const profileIdxRaw = Number((this.settings as any).launcherProfileIndex ?? 0);
    return Number.isFinite(profileIdxRaw) && profileIdxRaw >= 1 ? Math.floor(profileIdxRaw) : null;
  }

  private getEffectiveProfileIndex(): number | null {
    const sourceId = this.getEffectiveSourceId();
    const sourceIdx = this.parseTrailingProfileIndex(sourceId);
    const profileIdx = this.getConfiguredProfileIndex();

    // Optional alignment mode: use source-derived index for headers/guards when possible.
    if (Boolean((this.settings as any).enforceProfileSourceAlignment ?? true)) {
      if (sourceIdx != null) return sourceIdx;
    }

    return profileIdx;
  }

  private parseTrailingProfileIndex(value: string): number | null {
    const s = String(value || '').trim().toLowerCase();
    if (!s) return null;
    const m = s.match(/(?:^|[_-])(?:p)?(\d{1,2})$/);
    if (!m) return null;
    const n = Number(m[1]);
    if (!Number.isFinite(n) || n < 1) return null;
    return Math.floor(n);
  }

  private assertSchemaIndexSafetyForWrite(method?: string): void {
    if (!Boolean((this.settings as any).schemaIndexSafetyGuard ?? true)) return;
    const verb = String(method || 'GET').trim().toUpperCase();
    if (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(verb)) return;

    const sourceId = this.getEffectiveSourceId();
    const sourceIdx = this.parseTrailingProfileIndex(sourceId);
    const profileIdx = this.getEffectiveProfileIndex();

    if (sourceIdx != null && profileIdx != null && sourceIdx !== profileIdx) {
      throw new Error(
        `Schema-index safety guard blocked write: effective source "${sourceId}" implies profile #${sourceIdx}, but effective profile is #${profileIdx}.`
      );
    }
  }

  private getWorkspaceRootPath(): string | null {
    try {
      const adapter: any = (this.app as any).vault?.adapter;
      const p = adapter?.getBasePath?.();
      if (typeof p === 'string' && p.trim()) return p.trim();
    } catch {
      // ignore
    }
    return null;
  }

  private buildServerAliasFromTarget(): string {
    const idx = Math.max(1, Number((this.settings as any).launcherProfileIndex || 1));
    const target = String((this.settings as any).backendServerTarget || 'local');
    if (target === 'cloud-session') return `SUPABASE_SESSION_${idx}`;
    if (target === 'cloud-transaction') return `SUPABASE_TRANS_${idx}`;
    return `LOCAL_${idx}`;
  }

  private getCommandShell(): 'bash' | 'zsh' | 'sh' | 'powershell' | 'cmd' {
    const raw = String((this.settings as any).backendCommandShell || 'bash').trim().toLowerCase();
    if (raw === 'zsh' || raw === 'sh' || raw === 'powershell' || raw === 'cmd') return raw;
    return 'bash';
  }

  private quotePosix(v: string): string {
    return `'${String(v).replace(/'/g, `'\\''`)}'`;
  }

  private primeCommandForShell(command: string, cwd: string, shell: 'bash' | 'zsh' | 'sh' | 'powershell' | 'cmd'): string {
    if (shell === 'powershell') {
      const root = String(cwd).replace(/'/g, "''");
      return [
        `$env:PATH='${root};${root}\\.venv\\Scripts;'+$env:PATH`,
        `$env:SXDB_ROOT='${root}'`,
        `function global:sxdb { & '${root}\\sxctl.sh' @args }`,
        command
      ].join('; ');
    }

    if (shell === 'cmd') {
      const root = String(cwd).replace(/"/g, '');
      return [
        `set "PATH=${root};${root}\\.venv\\Scripts;%PATH%"`,
        `set "SXDB_ROOT=${root}"`,
        `doskey sxdb=${root}\\sxctl.sh $*`,
        command
      ].join(' && ');
    }

    const qRoot = this.quotePosix(cwd);
    return [
      `export PATH=${qRoot}/.venv/bin:${qRoot}:$PATH`,
      `export SXDB_ROOT=${qRoot}`,
      `sxdb(){ ${qRoot}/sxctl.sh "$@"; }`,
      command
    ].join('; ');
  }

  private shellInvocation(command: string, cwd: string): { shellExe: string; args: string[] } {
    const shell = this.getCommandShell();
    const primed = this.primeCommandForShell(command, cwd, shell);
    const isWin = String((globalThis as any)?.process?.platform || '').toLowerCase() === 'win32';

    if (shell === 'powershell') {
      return {
        shellExe: 'powershell.exe',
        args: ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', primed]
      };
    }
    if (shell === 'cmd') {
      return {
        shellExe: 'cmd.exe',
        args: ['/d', '/s', '/c', primed]
      };
    }
    if (shell === 'zsh') return { shellExe: 'zsh', args: ['-lc', primed] };
    if (shell === 'sh') return { shellExe: 'sh', args: ['-c', primed] };
    if (isWin) {
      // On Windows desktop, a "bash" preference should run inside WSL
      // rather than falling back to cmd/powershell semantics.
      return { shellExe: 'wsl.exe', args: ['bash', '-lc', primed] };
    }
    return { shellExe: 'bash', args: ['-lc', primed] };
  }

  private async runShellCommand(command: string, opts?: { background?: boolean }): Promise<void> {
    const cwd = this.getWorkspaceRootPath();
    if (!cwd) throw new Error('Cannot resolve workspace/vault root path for command execution.');

    const req: any = (window as any).require;
    if (!req) throw new Error('Desktop runtime shell integration is unavailable.');
    const childProcess = req('child_process');
    if (!childProcess?.spawn) throw new Error('child_process.spawn is unavailable.');
    const invocation = this.shellInvocation(command, cwd);

    const isBg = Boolean(opts?.background);
    if (isBg) {
      const child = childProcess.spawn(invocation.shellExe, invocation.args, {
        cwd,
        detached: true,
        stdio: 'ignore'
      });
      child.unref();
      return;
    }

    await new Promise<void>((resolve, reject) => {
      const child = childProcess.spawn(invocation.shellExe, invocation.args, {
        cwd,
        stdio: 'pipe'
      });
      let stderr = '';
      child.stderr?.on?.('data', (buf: any) => {
        stderr += String(buf ?? '');
      });
      child.on('error', (e: any) => reject(e));
      child.on('close', (code: number) => {
        if (code === 0) resolve();
        else reject(new Error(stderr.trim() || `Command failed with exit code ${code}`));
      });
    });
  }

  private async startSelectedServerFromPlugin(): Promise<void> {
    const idx = Math.max(1, Number((this.settings as any).launcherProfileIndex || 1));
    const alias = this.buildServerAliasFromTarget();
    const cmd = `SXCTL_NONINTERACTIVE=1 SXCTL_PROFILE_INDEX=${idx} SXCTL_DB_BACKEND=postgres_primary SXCTL_DB_PROFILE=${alias} sxdb api serve-bg`;
    await this.runShellCommand(cmd, { background: true });
  }

  private async stopServerFromPlugin(): Promise<void> {
    await this.runShellCommand('sxdb api stop');
  }

  private async serverStatusFromPlugin(): Promise<void> {
    await this.runShellCommand('sxdb api server-status');
  }

  private async updatePluginFromPlugin(): Promise<void> {
    const idx = Math.max(1, Number((this.settings as any).launcherProfileIndex || 1));
    const cmd = `SXCTL_NONINTERACTIVE=1 SXCTL_PROFILE_INDEX=${idx} sxdb plugin update`;
    await this.runShellCommand(cmd);
  }

  private async openProjectDocsFromPlugin(): Promise<void> {
    const preferred = String((this.settings as any).projectDocsPath || 'docs/USAGE.md').trim() || 'docs/USAGE.md';
    const candidates = [preferred, 'docs/README.md', 'README.md'];
    for (const p of candidates) {
      const af = this.app.vault.getAbstractFileByPath(normalizePath(p));
      if (af && af instanceof TFile) {
        await this.app.workspace.getLeaf(true).openFile(af);
        return;
      }
    }
    new Notice('Project docs file not found in this vault. Try setting “Project docs file” in plugin settings.');
  }

  apiUrl(path: string, query: Record<string, string | number | boolean | null | undefined> = {}): string {
    const baseUrl = this.settings.apiBaseUrl.replace(/\/$/, '');
    const p = String(path || '').startsWith('/') ? String(path || '') : `/${String(path || '')}`;
    const params = new URLSearchParams();

    for (const [k, v] of Object.entries(query || {})) {
      if (v == null) continue;
      params.set(k, String(v));
    }

    if (!params.has('source_id')) {
      params.set('source_id', this.getEffectiveSourceId());
    }

    const qs = params.toString();
    return qs ? `${baseUrl}${p}?${qs}` : `${baseUrl}${p}`;
  }

  async apiRequest(args: {
    path: string;
    query?: Record<string, string | number | boolean | null | undefined>;
    method?: string;
    body?: string;
    headers?: Record<string, string>;
  }) {
    this.assertSchemaIndexSafetyForWrite(args.method);

    const headers: Record<string, string> = {
      ...(args.headers || {}),
      'X-SX-Source-ID': this.getEffectiveSourceId(),
      'X-SX-Profile-Index': String(Math.max(1, Number(this.getEffectiveProfileIndex() || 1)))
    };

    return requestUrl({
      url: this.apiUrl(args.path, args.query || {}),
      method: args.method,
      body: args.body,
      headers
    });
  }

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
    const md = await this.app.vault.read(file);
    const text = String(md ?? '').trim();
    if (!text) return;

    // Best-effort: derive id from frontmatter.id or filename.
    const id = extractIdFromFrontmatter(text, file.basename);
    if (!id) return;

    // Push markdown first (this creates the durable backup).
    await this.apiRequest({
      path: `/items/${encodeURIComponent(id)}/note-md`,
      method: 'PUT',
      body: JSON.stringify({ markdown: text, template_version: 'user' }),
      headers: { 'Content-Type': 'application/json' }
    });

    // Optional meta extraction (rating/status/tags/notes) from YAML for redundancy.
    const payload = extractUserMetaPayload(text);
    if (payload) {
      await this.apiRequest({
        path: `/items/${encodeURIComponent(id)}/meta`,
        method: 'PUT',
        body: JSON.stringify(payload),
        headers: { 'Content-Type': 'application/json' }
      });
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
      callback: () => this.openPluginSettings('database')
    });
    this.addCommand({
      id: 'sxdb-open-settings-config',
      name: 'SX: Open settings → Config tab',
      callback: () => this.openPluginSettings('database')
    });
    this.addCommand({
      id: 'sxdb-open-settings-sync',
      name: 'SX: Open settings → Sync tab',
      callback: () => this.openPluginSettings('dataflow')
    });
    this.addCommand({
      id: 'sxdb-open-settings-fetch',
      name: 'SX: Open settings → Fetch tab',
      callback: () => this.openPluginSettings('dataflow')
    });
    this.addCommand({
      id: 'sxdb-open-settings-backend',
      name: 'SX: Open settings → Backend tab',
      callback: () => this.openPluginSettings('database')
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

    this.addCommand({
      id: 'sxdb-server-start-selected',
      name: 'SX: Start selected backend server',
      callback: async () => {
        try {
          await this.startSelectedServerFromPlugin();
          new Notice('Server launch requested in background (via sxctl).');
        } catch (e: any) {
          new Notice(`Server start failed: ${String(e?.message ?? e)}`);
        }
      }
    });

    this.addCommand({
      id: 'sxdb-server-stop',
      name: 'SX: Stop backend server',
      callback: async () => {
        try {
          await this.stopServerFromPlugin();
          new Notice('Server stop command completed.');
        } catch (e: any) {
          new Notice(`Server stop failed: ${String(e?.message ?? e)}`);
        }
      }
    });

    this.addCommand({
      id: 'sxdb-server-status',
      name: 'SX: Backend server status',
      callback: async () => {
        try {
          await this.serverStatusFromPlugin();
          new Notice('Server status command completed.');
        } catch (e: any) {
          new Notice(`Server status failed: ${String(e?.message ?? e)}`);
        }
      }
    });

    this.addCommand({
      id: 'sxdb-plugin-update',
      name: 'SX: Update plugin (build + install)',
      callback: async () => {
        try {
          await this.updatePluginFromPlugin();
          new Notice('Plugin update completed.');
        } catch (e: any) {
          new Notice(`Plugin update failed: ${String(e?.message ?? e)}`);
        }
      }
    });

    this.addCommand({
      id: 'sxdb-open-project-docs',
      name: 'SX: Open project docs hub',
      callback: async () => {
        await this.openProjectDocsFromPlugin();
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
        if (strategy === 'active-only' && folderClass === 'legacy' && !this.settings.autoPushLegacyFoldersInActiveOnly) {
          // Strict mode: skip legacy folders. Warn once per file path per session to keep it quiet.
          const p = normalizePath(af.path);
          if (!this._autoPushLegacyWarned.has(p)) {
            this._autoPushLegacyWarned.add(p);
            new Notice(
              'Auto-push skipped: legacy _db note edited while “Vault write strategy” is Active-only. Enable “Auto-push legacy folders in Active-only mode”, or run Consolidate.'
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
