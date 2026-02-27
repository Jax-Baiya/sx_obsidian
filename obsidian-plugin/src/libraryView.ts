import {
  ItemView,
  MarkdownRenderer,
  Notice,
  requestUrl,
  WorkspaceLeaf,
  WorkspaceWindowInitData,
  normalizePath,
  parseYaml,
  TFile,
  TFolder
} from 'obsidian';
import type SxDbPlugin from './main';
import { mergeMarkdownPreservingUserEdits } from './markdownMerge';
import { openPinnedFile } from './leafUtils';
import {
  applyCellSingleSelection,
  applyColumnSingleSelection,
  applyRowSingleSelection,
  applySelectAllToggle,
  cellSelectionKey,
  choosePrimaryWorkflowStatus,
  clearSingleSelectionState,
  computeHoverVideoSizePx,
  formatLinkChipLabel,
  getWorkflowStatuses,
  hasAnyVisibleColumns,
  normalizeTagsValue as normalizeTagsValueCore,
  parseLinksValue as parseLinksValueCore,
  sanitizeColumnOrder,
  sanitizeColumnWidths,
  shouldCommitLinkChipOnKey as shouldCommitLinkChipOnKeyCore,
  validateHttpUrlLike
} from './libraryCore';
import type { ApiAuthor, ApiItem, ApiNote } from './libraryTypes';
import { DEFAULT_LIBRARY_COLUMNS } from './librarySchema';
import {
  clearMarkdownInFolder as clearMarkdownInFolderShared,
  collectMarkdownFiles as collectMarkdownFilesShared,
  ensureFolder as ensureFolderShared
} from './shared/vaultFs';
import { openProtocolOrUrl as openProtocolOrUrlShared, shouldCopyLinkOnClickWithMode } from './shared/linkRouting';
import { copyToClipboard as copyToClipboardShared } from './shared/clipboard';
import {
  buildPeekPrelude as buildPeekPreludeShared,
  extractFrontmatter as extractFrontmatterShared,
  normalizeYamlValue as normalizeYamlValueShared
} from './shared/notePreview';
import {
  hasHoverEditorInstalled as hasHoverEditorInstalledShared,
  hoverEditorCommandId as hoverEditorCommandIdShared
} from './shared/hoverEditor';
import {
  findVaultNotesForId as findVaultNotesForIdShared,
  openVaultNoteForId as openVaultNoteForIdShared
} from './shared/vaultNotes';
import { applySelectionClasses } from './shared/selectionUi';
import { positionFloatingVideo } from './shared/hoverVideo';
import { applyFreezePanesLayout, applyStickyOffsets } from './shared/tableLayout';

export const SXDB_LIBRARY_VIEW = 'sxdb-library-view';

export class LibraryView extends ItemView {
  plugin: SxDbPlugin;

  private rowHeights: Record<string, number> = {};
  private selectedCells = new Set<string>();
  private selectedRows = new Set<string>();
  private selectedCols = new Set<string>();
  private tableSelectedAll = false;

  private hoverVideoEl: HTMLVideoElement | null = null;
  private hoverVideoHideT: number | null = null;

  private onWindowResize?: () => void;

  // Table "freeze panes" (Google Sheets-like). Kept intentionally simple:
  // - freezeCols: 0 = none, 1 = ID, 2 = Thumb + ID (when visible)
  // - freezeFirstRow: first *data* row (not header)
  private freezeCols: 0 | 1 | 2 = 0;
  private freezeFirstRow: boolean = false;

  private pageLimit(): number {
    // Backend currently allows up to 2000 on /items, but fetching too many rows
    // makes the UI sluggish. Clamp to a sane maximum.
    const raw = Number(this.plugin.settings.searchLimit ?? 50);
    const n = Number.isFinite(raw) ? Math.floor(raw) : 50;
    return Math.max(10, Math.min(1000, n));
  }


  // Experimental: Obsidian leaf embedded inside the inline Note Peek window.
  private notePeekLeafOrigParent: Node | null = null;
  private notePeekLeafOrigNextSibling: ChildNode | null = null;
  private notePeekInlineLeaf: WorkspaceLeaf | null = null;
  private notePeekEl: HTMLDivElement | null = null;
  private notePeekHeaderEl: HTMLDivElement | null = null;
  private notePeekBodyEl: HTMLDivElement | null = null;
  private notePeekState:
    | { x: number; y: number; w: number; h: number; id: string; filePath: string }
    | null = null;
  private notePeekMode: 'source' | 'preview' = 'preview';

  private notePeekEngine(): 'inline' | 'split' | 'popout' {
    const v = String((this.plugin.settings as any).libraryNotePeekEngine || 'inline');
    if (v === 'split' || v === 'popout') return v;
    return 'inline';
  }



  private isLeafValid(leaf: WorkspaceLeaf | null | undefined): leaf is WorkspaceLeaf {
    if (!leaf) return false;
    try {
      const anyLeaf: any = leaf as any;
      if (!anyLeaf.parent) return false;
      const el: HTMLElement | null | undefined = anyLeaf?.view?.containerEl;
      if (el && el.isConnected === false) return false;
      return true;
    } catch {
      return false;
    }
  }

  private getStoredNotePeekPopoutLeaf(): WorkspaceLeaf | null {
    return ((this.plugin as any)._sxdbNotePeekPopoutLeaf as WorkspaceLeaf | null) ?? null;
  }

  private setStoredNotePeekPopoutLeaf(leaf: WorkspaceLeaf | null): void {
    (this.plugin as any)._sxdbNotePeekPopoutLeaf = leaf;
  }

  private async openFileInNotePeekPopout(file: TFile): Promise<void> {
    const ws = this.app.workspace;
    let leaf = this.getStoredNotePeekPopoutLeaf();
    if (!this.isLeafValid(leaf)) leaf = null;

    if (!leaf) {
      const w = Math.max(320, Number(this.plugin.settings.libraryNotePeekWidth ?? 520));
      const h = Math.max(260, Number(this.plugin.settings.libraryNotePeekHeight ?? 640));
      const data: WorkspaceWindowInitData = {
        size: { width: Math.floor(w), height: Math.floor(h) }
      };
      // Popout leaf uses Obsidian's native Markdown view, including properties and view mode.
      leaf = ws.openPopoutLeaf(data);
      this.setStoredNotePeekPopoutLeaf(leaf);
    }

    await leaf.openFile(file);
  }

  // Ctrl/Cmd-hover markdown preview popover (custom, so it reliably shows _db notes)
  private hoverMdState:
    | {
        id: string;
        filePath: string;
        anchorEl: HTMLElement | null;
        onAnchor: boolean;
        onPopover: boolean;
        token: number;
      }
    | null = null;
  private hoverMdEl: HTMLDivElement | null = null;

  private readonly DEFAULT_COLUMNS: Record<string, boolean> = {
    ...DEFAULT_LIBRARY_COLUMNS,
    caption: false
  };

  private columnOrder: string[] = [];
  private columnWidths: Record<string, number> = {};

  private hoverEditorCommandId(): string {
    return hoverEditorCommandIdShared();
  }

  private hasHoverEditorInstalled(): boolean {
    return hasHoverEditorInstalledShared(this.app);
  }

  private openProtocolOrUrl(link: string): void {
    openProtocolOrUrlShared(this.app, link);
  }

  private shouldCopyLinkOnClick(evt: MouseEvent): boolean {
    const mode = String((this.plugin.settings as any).libraryLinkCopyModifier || 'ctrl-cmd');
    return shouldCopyLinkOnClickWithMode(mode, evt);
  }

  private parseLinksValue(v: unknown): string[] {
    return parseLinksValueCore(v);
  }

  private renderLinkPills(container: HTMLElement, urls: string[]): void {
    container.empty();
    if (!urls.length) {
      container.style.display = 'none';
      return;
    }

    container.style.display = 'flex';
    for (const u of urls) {
      const label = formatLinkChipLabel(u);

      const a = container.createEl('a', {
        text: label,
        href: u,
        cls: 'sxdb-meta-linkpill'
      });
      a.setAttr('title', u);
      a.setAttr('target', '_blank');
      a.setAttr('rel', 'noopener noreferrer');
      a.addEventListener('click', (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        if (this.shouldCopyLinkOnClick(evt as MouseEvent)) {
          void this.copyToClipboard(u).then((ok) => {
            if (ok) new Notice('Copied link.');
          });
          return;
        }
        this.openProtocolOrUrl(u);
      });
    }
  }

  private bindRenderedMetadataLinkBehavior(container: HTMLElement): void {
    container.addEventListener('click', (evt) => {
      const t = evt.target as HTMLElement | null;
      if (!t) return;
      const a = t.closest('a[href]') as HTMLAnchorElement | null;
      if (!a) return;
      const href = String(a.getAttribute('href') || '').trim();
      if (!href) return;
      if (!/^(https?:\/\/|sxopen:|sxreveal:)/i.test(href)) return;

      evt.preventDefault();
      evt.stopPropagation();

      if (this.shouldCopyLinkOnClick(evt as MouseEvent)) {
        void this.copyToClipboard(href).then((ok) => {
          if (ok) new Notice('Copied link.');
        });
        return;
      }

      this.openProtocolOrUrl(href);
    });
  }

  private shouldCommitLinkChipOnKey(evt: KeyboardEvent): boolean {
    const mode = String((this.plugin.settings as any).libraryLinkChipCommitOn || 'tab');
    return shouldCommitLinkChipOnKeyCore(evt.key, mode);
  }

  private validateUrlLike(v: string): boolean {
    return validateHttpUrlLike(v);
  }

  private cellKey(rowId: string, colKey: string): string {
    return cellSelectionKey(rowId, colKey);
  }

  private clearSelectionState(): void {
    clearSingleSelectionState(this.selectedCells, this.selectedRows, this.selectedCols);
    this.tableSelectedAll = false;
  }

  private updateSelectionClasses(table: HTMLTableElement): void {
    applySelectionClasses(table, this.selectedCells, this.selectedRows, this.selectedCols, this.tableSelectedAll);
  }

  private clearHoverVideoHideTimer(): void {
    if (this.hoverVideoHideT != null) {
      window.clearTimeout(this.hoverVideoHideT);
      this.hoverVideoHideT = null;
    }
  }

  private hideHoverVideo(): void {
    this.clearHoverVideoHideTimer();
    if (!this.hoverVideoEl) return;
    try {
      this.hoverVideoEl.pause();
    } catch {
      // ignore
    }
    this.hoverVideoEl.style.display = 'none';
  }

  private scheduleHideHoverVideo(delayMs: number = 120): void {
    this.clearHoverVideoHideTimer();
    this.hoverVideoHideT = window.setTimeout(() => {
      this.hoverVideoHideT = null;
      this.hideHoverVideo();
    }, Math.max(0, delayMs));
  }

  private ensureHoverVideoElement(): HTMLVideoElement {
    if (this.hoverVideoEl?.isConnected) return this.hoverVideoEl;

    if (this.hoverVideoEl) {
      try {
        this.hoverVideoEl.remove();
      } catch {
        // ignore
      }
    }

    const video = document.createElement('video');
    video.className = 'sxdb-lib-hovervideo sxdb-lib-hovervideo-floating';
    video.loop = true;
    video.playsInline = true;
    video.preload = 'metadata';
    video.controls = true;
    video.style.display = 'none';
    video.addEventListener('mouseenter', () => this.clearHoverVideoHideTimer());
    video.addEventListener('mouseleave', () => this.scheduleHideHoverVideo(80));
    document.body.appendChild(video);

    this.hoverVideoEl = video;
    return video;
  }

  private positionHoverVideo(anchorEl: HTMLElement, video: HTMLVideoElement): void {
    const { w, h } = this.getHoverVideoSizePx();
    positionFloatingVideo(anchorEl, video, w, h);
  }

  private getHoverVideoSizePx(): { w: number; h: number } {
    return computeHoverVideoSizePx({
      mode: (this.plugin.settings as any).libraryHoverVideoResizeMode,
      scalePct: (this.plugin.settings as any).libraryHoverVideoScalePct,
      width: this.plugin.settings.libraryHoverPreviewWidth,
      height: this.plugin.settings.libraryHoverPreviewHeight
    });
  }

  private async showHoverVideoForItem(id: string, anchorEl: HTMLElement): Promise<void> {
    if (!this.plugin.settings.libraryHoverVideoPreview) return;
    const video = this.ensureHoverVideoElement();
    this.clearHoverVideoHideTimer();

    const src = this.apiUrl(`/media/video/${encodeURIComponent(id)}`);
    if (video.src !== src) video.src = src;
    video.muted = Boolean(this.plugin.settings.libraryHoverPreviewMuted);

    this.positionHoverVideo(anchorEl, video);
    video.style.display = 'block';

    try {
      await video.play();
    } catch {
      // Autoplay may be blocked; controls allow manual play.
    }
  }

  private async ensureFolder(folderPath: string): Promise<TFolder> {
    return ensureFolderShared(this.app, folderPath);
  }

  private collectMarkdownFiles(folder: TFolder): TFile[] {
    return collectMarkdownFilesShared(folder);
  }

  private async clearFolderMarkdown(folderPath: string): Promise<number> {
    return clearMarkdownInFolderShared(this.app, folderPath);
  }

  private q = '';
  private bookmarkedOnly = false;
  private bookmarkFrom = '';
  private bookmarkTo = '';
  private authorFilter = '';
  private statusFilters: Set<string> = new Set();
  private sortOrder: 'recent' | 'bookmarked' | 'author' | 'status' | 'rating' = 'bookmarked';
  private tagFilter = '';
  private captionFilter = '';
  private ratingMin = '';
  private ratingMax = '';
  private hasNotesOnly = false;
  private authorSearch = '';
  private offset = 0;
  private total = 0;
  private menuHidden = false;
  private lastMissingMediaNoticeKey = '';
  private lastMissingMediaNoticeTs = 0;

  private authors: ApiAuthor[] = [];
  private authorSel: HTMLSelectElement | null = null;
  private statusCbs: Record<string, HTMLInputElement> = {};

  private lastItems: ApiItem[] = [];
  private lastLimit: number = 50;

  private _statusEditorEl: HTMLDivElement | null = null;

  private workflowStatuses(): string[] {
    return getWorkflowStatuses();
  }

  private choosePrimaryStatus(statuses: string[]): string | null {
    return choosePrimaryWorkflowStatus(statuses);
  }

  private closeStatusEditor(): void {
    if (!this._statusEditorEl) return;
    try {
      this._statusEditorEl.remove();
    } catch {
      // ignore
    }
    this._statusEditorEl = null;
  }

  private openStatusEditor(anchor: HTMLElement, current: string[], onChange: (next: string[]) => void): void {
    this.closeStatusEditor();

    const panel = document.createElement('div') as HTMLDivElement;
    panel.className = 'sxdb-statuseditor';
    document.body.appendChild(panel);
    this._statusEditorEl = panel;

    const rect = anchor.getBoundingClientRect();
    const x = Math.min(window.innerWidth - 260, Math.max(8, Math.floor(rect.left)));
    const y = Math.min(window.innerHeight - 260, Math.max(8, Math.floor(rect.bottom + 6)));
    panel.style.left = `${x}px`;
    panel.style.top = `${y}px`;

    panel.createEl('div', { text: 'Status', cls: 'sxdb-statuseditor-title' });
    panel.createEl('div', { text: 'Multi-select. (Tip: Clear to unset.)', cls: 'sxdb-statuseditor-sub' });

    const set = new Set((current || []).map((s) => String(s).trim()).filter(Boolean));
    const list = panel.createDiv({ cls: 'sxdb-statuseditor-list' });
    for (const s of this.workflowStatuses()) {
      const row = list.createEl('label', { cls: 'sxdb-statuseditor-row' });
      const cb = row.createEl('input', { type: 'checkbox' });
      cb.checked = set.has(s);
      row.createSpan({ text: s });
      cb.addEventListener('change', () => {
        if (cb.checked) set.add(s);
        else set.delete(s);
        onChange(Array.from(set));
      });
    }

    const actions = panel.createDiv({ cls: 'sxdb-statuseditor-actions' });
    const clear = actions.createEl('button', { text: 'Clear' });
    const close = actions.createEl('button', { text: 'Close' });
    clear.addEventListener('click', () => {
      set.clear();
      onChange([]);
      // reflect UI
      const inputs = list.querySelectorAll('input[type="checkbox"]') as NodeListOf<HTMLInputElement>;
      inputs.forEach((i) => (i.checked = false));
    });
    close.addEventListener('click', () => this.closeStatusEditor());

    const onDoc = (evt: MouseEvent) => {
      const t = evt.target as any;
      if (!t) return;
      if (panel.contains(t)) return;
      if (anchor.contains(t)) return;
      this.closeStatusEditor();
      document.removeEventListener('mousedown', onDoc, true);
      document.removeEventListener('keydown', onKey);
    };
    const onKey = (evt: KeyboardEvent) => {
      if (evt.key === 'Escape') {
        this.closeStatusEditor();
        document.removeEventListener('mousedown', onDoc, true);
        document.removeEventListener('keydown', onKey);
      }
    };

    window.setTimeout(() => {
      document.addEventListener('mousedown', onDoc, true);
      document.addEventListener('keydown', onKey);
    }, 0);
  }

  private columns: Record<string, boolean> = {
    index: true,
    thumb: true,
    id: true,
    author: true,
    bookmarked: true,
    status: true,
    rating: true,
    tags: true,
    notes: true,
    product_link: false,
    author_links: false,
    platform_targets: false,
    post_url: false,
    published_time: false,
    workflow_log: false,
    actions: true
  };

  private normalizeColumnsState(): void {
    if (!hasAnyVisibleColumns(this.columns)) {
      // Repair corrupted settings where every column is hidden.
      this.columns = Object.assign({}, this.DEFAULT_COLUMNS);
      new Notice('SX Library: your saved column visibility hid everything — reset to defaults.');
      return;
    }
  }

  private persistLibraryColumnsDebounced(): void {
    window.clearTimeout((this as any)._persistColsT);
    (this as any)._persistColsT = window.setTimeout(() => {
      (this.plugin.settings as any).libraryColumns = Object.assign({}, (this.plugin.settings as any).libraryColumns ?? {}, this.columns);
      void this.plugin.saveSettings();
    }, 250);
  }

  private restoreLibraryColumnsFromSettings(): void {
    const cols = (this.plugin.settings as any).libraryColumns as any;
    if (!cols || typeof cols !== 'object') return;
    // only accept known keys
    for (const k of Object.keys(this.columns)) {
      if (typeof cols[k] === 'boolean') this.columns[k] = cols[k];
    }
    this.normalizeColumnsState();
  }

  private persistLibraryLayoutDebounced(): void {
    window.clearTimeout((this as any)._persistLayoutT);
    (this as any)._persistLayoutT = window.setTimeout(() => {
      (this.plugin.settings as any).libraryColumnOrder = Array.isArray(this.columnOrder) ? [...this.columnOrder] : [];
      (this.plugin.settings as any).libraryColumnWidths = Object.assign({}, this.columnWidths || {});
      void this.plugin.saveSettings();
    }, 250);
  }

  private restoreLibraryLayoutFromSettings(): void {
    const ord = (this.plugin.settings as any).libraryColumnOrder as any;
    if (Array.isArray(ord)) this.columnOrder = sanitizeColumnOrder(ord, Object.keys(this.DEFAULT_COLUMNS));
    const w = (this.plugin.settings as any).libraryColumnWidths as any;
    this.columnWidths = sanitizeColumnWidths(w);
  }

  private persistLibraryStateDebounced(): void {
    window.clearTimeout((this as any)._persistT);
    (this as any)._persistT = window.setTimeout(() => {
      const next = {
        q: this.q,
        bookmarkedOnly: this.bookmarkedOnly,
        bookmarkFrom: this.bookmarkFrom,
        bookmarkTo: this.bookmarkTo,
        authorFilter: this.authorFilter,
        statuses: Array.from(this.statusFilters),
        sortOrder: this.sortOrder,
        tag: this.tagFilter,
        caption: this.captionFilter,
        ratingMin: this.ratingMin,
        ratingMax: this.ratingMax,
        hasNotes: this.hasNotesOnly,
        authorSearch: this.authorSearch,
        menuHidden: this.menuHidden,

        freezeCols: this.freezeCols,
        freezeFirstRow: this.freezeFirstRow
      };

      (this.plugin.settings as any).libraryState = Object.assign({}, (this.plugin.settings as any).libraryState ?? {}, next);
      void this.plugin.saveSettings();
    }, 250);
  }

  private restoreLibraryStateFromSettings(): void {
    const s = (this.plugin.settings as any).libraryState as any;
    if (!s) return;
    if (typeof s.q === 'string') this.q = s.q;
    if (typeof s.bookmarkedOnly === 'boolean') this.bookmarkedOnly = s.bookmarkedOnly;
    if (typeof s.bookmarkFrom === 'string') this.bookmarkFrom = s.bookmarkFrom;
    if (typeof s.bookmarkTo === 'string') this.bookmarkTo = s.bookmarkTo;
    if (typeof s.authorFilter === 'string') this.authorFilter = s.authorFilter;
    if (Array.isArray(s.statuses)) this.statusFilters = new Set(s.statuses.filter((x: any) => typeof x === 'string'));
    if (typeof s.sortOrder === 'string') this.sortOrder = s.sortOrder;
    if (typeof s.tag === 'string') this.tagFilter = s.tag;
    if (typeof s.caption === 'string') this.captionFilter = s.caption;
    if (typeof s.ratingMin === 'string') this.ratingMin = s.ratingMin;
    if (typeof s.ratingMax === 'string') this.ratingMax = s.ratingMax;
    if (typeof s.hasNotes === 'boolean') this.hasNotesOnly = s.hasNotes;
    if (typeof s.authorSearch === 'string') this.authorSearch = s.authorSearch;
    if (typeof s.menuHidden === 'boolean') this.menuHidden = s.menuHidden;

    if (typeof s.freezeCols === 'number') {
      const n = Math.max(0, Math.min(2, Math.floor(s.freezeCols)));
      this.freezeCols = n as any;
    }
    if (typeof s.freezeFirstRow === 'boolean') this.freezeFirstRow = Boolean(s.freezeFirstRow);
  }

  constructor(leaf: WorkspaceLeaf, plugin: SxDbPlugin) {
    super(leaf);
    this.plugin = plugin;
    this.restoreLibraryStateFromSettings();
    this.restoreLibraryColumnsFromSettings();
    this.restoreLibraryLayoutFromSettings();
    this.normalizeColumnsState();
    this.lastLimit = this.pageLimit();
  }

  getViewType(): string {
    return SXDB_LIBRARY_VIEW;
  }

  getDisplayText(): string {
    return 'SX Library';
  }

  async onOpen(): Promise<void> {
    // Keep sticky offsets in sync with layout/theme changes.
    this.onWindowResize = () => this.updateStickyOffsets();
    window.addEventListener('resize', this.onWindowResize);

    this.render();
    await this.loadAuthors();
    await this.refresh();
  }

  async onClose(): Promise<void> {
    this.closeStatusEditor();
    this.closeHoverMarkdownPreview();

    this.closeNotePeek();

    if (this.onWindowResize) {
      window.removeEventListener('resize', this.onWindowResize);
      this.onWindowResize = undefined;
    }

    this.hideHoverVideo();
    if (this.hoverVideoEl) {
      try {
        this.hoverVideoEl.remove();
      } catch {
        // ignore
      }
    }
    this.hoverVideoEl = null;
  }

  private baseUrl(): string {
    return this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
  }

  private apiUrl(path: string, query: Record<string, string | number | boolean | null | undefined> = {}): string {
    const p: any = this.plugin as any;
    if (typeof p.apiUrl === 'function') return p.apiUrl(path, query);
    const base = this.baseUrl();
    const qp = new URLSearchParams();
    for (const [k, v] of Object.entries(query || {})) {
      if (v == null) continue;
      qp.set(k, String(v));
    }
    const qs = qp.toString();
    return qs ? `${base}${path}?${qs}` : `${base}${path}`;
  }

  private async apiRequest(args: {
    path: string;
    query?: Record<string, string | number | boolean | null | undefined>;
    method?: string;
    body?: string;
    headers?: Record<string, string>;
  }) {
    const p: any = this.plugin as any;
    if (typeof p.apiRequest === 'function') return p.apiRequest(args);
    return requestUrl({
      url: this.apiUrl(args.path, args.query || {}),
      method: args.method,
      body: args.body,
      headers: args.headers
    });
  }

  private async hydrateRoutingDebugLine(debugEl: HTMLDivElement, routing: any): Promise<void> {
    if (!debugEl?.isConnected) return;
    const base = String(debugEl.textContent || '').trim();
    const effectiveSource = String(routing?.effectiveSource || '').trim();
    const effectiveProfile = Number(routing?.effectiveProfile ?? 0);

    let schema = '';
    let vaultRoot = '';

    try {
      const h = await this.apiRequest({ path: '/health' });
      const j = h?.json as any;
      schema = String(j?.backend?.schema || '').trim();
    } catch {
      // optional debug enrichment only
    }

    try {
      const p = await this.apiRequest({ path: '/pipeline/profiles' });
      const j = p?.json as any;
      const profiles = Array.isArray(j?.profiles) ? j.profiles : [];
      let match = profiles.find((row: any) => String(row?.source_id || '').trim() === effectiveSource);
      if (!match && Number.isFinite(effectiveProfile) && effectiveProfile >= 1) {
        match = profiles.find((row: any) => Number(row?.index) === Math.floor(effectiveProfile));
      }
      vaultRoot = String(match?.src_path || '').trim();
    } catch {
      // optional debug enrichment only
    }

    if (!debugEl?.isConnected) return;

    const extras: string[] = [];
    if (schema) extras.push(`schema=${schema}`);
    if (vaultRoot) extras.push(`vault_root=${vaultRoot}`);
    if (extras.length) debugEl.setText(`${base} · ${extras.join(' · ')}`);

    const oldTitle = String(debugEl.getAttribute('title') || '').trim();
    const titleExtras: string[] = [];
    if (schema) titleExtras.push(`schema=${schema}`);
    if (vaultRoot) titleExtras.push(`vault_root=${vaultRoot}`);
    if (titleExtras.length) debugEl.setAttr('title', `${oldTitle}${oldTitle ? ' · ' : ''}${titleExtras.join(' · ')}`);
  }

  private updateStickyOffsets(): void {
    const root = this.contentEl as any as HTMLElement;
    applyStickyOffsets(root);
  }

  private applyFreezePanes(table: HTMLTableElement, visibleKeys: string[]): void {
    applyFreezePanesLayout(table, visibleKeys, this.freezeCols, this.freezeFirstRow, this.columnWidths);
  }

  private async copyToClipboard(text: string): Promise<boolean> {
    return copyToClipboardShared(String(text ?? ''));
  }

  private async findVaultNotesForId(id: string): Promise<TFile[]> {
    return findVaultNotesForIdShared(this.app, id, [
      this.plugin.settings.activeNotesDir,
      this.plugin.settings.bookmarksNotesDir,
      this.plugin.settings.authorsNotesDir
    ]);
  }

  private activePinnedPathForId(id: string): string {
    const safeId = String(id || '').trim();
    const activeDir = normalizePath(this.plugin.settings.activeNotesDir);
    return normalizePath(`${activeDir}/${safeId}.md`);
  }

  private isPinnedInActiveDir(id: string): boolean {
    const p = this.activePinnedPathForId(id);
    const af = this.app.vault.getAbstractFileByPath(p);
    return Boolean(af && af instanceof TFile);
  }








  private normalizeYamlValue(v: any): any {
    return normalizeYamlValueShared(v);
  }

  private normalizeTagsValue(v: any): string[] | null {
    return normalizeTagsValueCore(v);
  }

  private async normalizeTagsFrontmatterInFile(file: TFile, mdHint?: string): Promise<void> {
    try {
      const md = mdHint != null ? String(mdHint) : await this.app.vault.read(file);
      const { fm } = this.extractFrontmatter(md);
      if (!fm || typeof fm !== 'object') return;
      if (!Object.prototype.hasOwnProperty.call(fm, 'tags')) return;

      const next = this.normalizeTagsValue((fm as any).tags);
      const fmApi: any = (this.app as any).fileManager;
      if (!fmApi?.processFrontMatter) return;

      await fmApi.processFrontMatter(file, (front: any) => {
        if (!next) {
          try {
            delete front.tags;
          } catch {
            // ignore
          }
        } else {
          front.tags = next;
        }
      });
      this.plugin.markRecentlyWritten(file.path);
    } catch {
      // Best-effort only.
    }
  }

  private async updateVaultFrontmatterForId(id: string, patch: Record<string, any>): Promise<void> {
    const files = await this.findVaultNotesForId(id);
    if (!files.length) return;

    const fmPatch: Record<string, any> = {};
    for (const [k, v] of Object.entries(patch || {})) {
      if (k === 'tags') fmPatch[k] = this.normalizeTagsValue(v);
      else if (k === 'author_links') fmPatch[k] = this.parseLinksValue(v);
      else fmPatch[k] = this.normalizeYamlValue(v);
    }

    for (const f of files) {
      try {
        const fmApi: any = (this.app as any).fileManager;
        if (fmApi?.processFrontMatter) {
          await fmApi.processFrontMatter(f, (fm: any) => {
            for (const [k, v] of Object.entries(fmPatch)) {
              if (v == null || v === '') {
                try {
                  delete fm[k];
                } catch {
                  // ignore
                }
              } else {
                fm[k] = v;
              }
            }
          });
        }
        this.plugin.markRecentlyWritten(f.path);
      } catch {
        // Best-effort only.
      }
    }
  }

  private async findVaultNotesForAuthor(authorUniqueId?: string | null, authorName?: string | null): Promise<TFile[]> {
    const uid = String(authorUniqueId || '').trim();
    const name = String(authorName || '').trim();
    if (!uid && !name) return [];

    const roots = [
      normalizePath(this.plugin.settings.activeNotesDir),
      normalizePath(this.plugin.settings.bookmarksNotesDir),
      normalizePath(this.plugin.settings.authorsNotesDir)
    ].filter(Boolean);

    const out: TFile[] = [];
    const seen = new Set<string>();
    for (const f of this.app.vault.getFiles()) {
      if (f.extension !== 'md') continue;
      const p = normalizePath(f.path);
      if (!roots.some((r) => r && (p === r || p.startsWith(r + '/')))) continue;

      try {
        const md = await this.app.vault.read(f);
        const { fm } = this.extractFrontmatter(md);
        if (!fm || typeof fm !== 'object') continue;
        const fUid = String((fm as any).author_unique_id || '').trim();
        const fName = String((fm as any).author_name || '').trim();
        const match = (uid && fUid === uid) || (!uid && name && fName === name);
        if (!match) continue;
        if (seen.has(f.path)) continue;
        seen.add(f.path);
        out.push(f);
      } catch {
        // ignore parse/read failures
      }
    }

    return out;
  }

  private async updateVaultFrontmatterForAuthor(
    authorUniqueId: string | null | undefined,
    authorName: string | null | undefined,
    patch: Record<string, any>
  ): Promise<void> {
    const files = await this.findVaultNotesForAuthor(authorUniqueId, authorName);
    if (!files.length) return;

    const fmPatch: Record<string, any> = {};
    for (const [k, v] of Object.entries(patch || {})) {
      if (k === 'tags') fmPatch[k] = this.normalizeTagsValue(v);
      else if (k === 'author_links') fmPatch[k] = this.parseLinksValue(v);
      else fmPatch[k] = this.normalizeYamlValue(v);
    }

    const fmApi: any = (this.app as any).fileManager;
    if (!fmApi?.processFrontMatter) return;

    for (const f of files) {
      try {
        await fmApi.processFrontMatter(f, (fm: any) => {
          for (const [k, v] of Object.entries(fmPatch)) {
            if (v == null || v === '') {
              try {
                delete fm[k];
              } catch {
                // ignore
              }
            } else {
              fm[k] = v;
            }
          }
        });
        this.plugin.markRecentlyWritten(f.path);
      } catch {
        // best-effort
      }
    }
  }

  private triggerObsidianHoverPreview(evt: MouseEvent, file: TFile, targetEl: HTMLElement): void {
    try {
      const ws: any = this.app.workspace as any;
      const sourcePath = this.app.workspace.getActiveFile()?.path ?? '';
      // Best-effort: Obsidian's internal hover preview event.
      ws?.trigger?.('hover-link', {
        event: evt,
        source: 'sxdb-library',
        // Use the view instance as hoverParent so native Page Preview / Hover Editor can persist state.
        hoverParent: this as any,
        targetEl,
        // Passing a vault path generally resolves reliably via getFirstLinkpathDest.
        linktext: file.path,
        sourcePath
      });
    } catch {
      // ignore
    }
  }

  private closeHoverMarkdownPreview(): void {
    this.hoverMdState = null;
    if (!this.hoverMdEl) return;
    try {
      this.hoverMdEl.remove();
    } catch {
      // ignore
    }
    this.hoverMdEl = null;
  }

  private setHoverMarkdownAnchor(anchorEl: HTMLElement, onAnchor: boolean): void {
    const row = anchorEl.closest('tr[data-row-id]') as HTMLTableRowElement | null;
    const id = String(row?.getAttribute('data-row-id') || '').trim();
    if (!id) return;

    if (!onAnchor) {
      if (this.hoverMdState && this.hoverMdState.id === id) {
        this.hoverMdState.onAnchor = false;
        const token = this.hoverMdState.token;
        window.setTimeout(() => {
          if (!this.hoverMdState || this.hoverMdState.token !== token) return;
          if (this.hoverMdState.onAnchor || this.hoverMdState.onPopover) return;
          this.closeHoverMarkdownPreview();
        }, 140);
      }
      return;
    }

    const engine = String((this.plugin.settings as any).libraryIdCtrlHoverPreviewEngine || 'auto');
    const preferNative = engine === 'native' || (engine === 'auto' && this.hasHoverEditorInstalled());
    if (preferNative) return;

    const token = Date.now();
    const existing = this.hoverMdState;
    if (existing && existing.id === id) {
      existing.anchorEl = anchorEl;
      existing.onAnchor = true;
      existing.token = token;
      return;
    }

    this.hoverMdState = {
      id,
      filePath: '',
      anchorEl,
      onAnchor: true,
      onPopover: false,
      token
    };

    void this.openHoverMarkdownPreviewForId(id, anchorEl, token);
  }

  private async openHoverMarkdownPreviewForId(id: string, anchorEl: HTMLElement, token: number): Promise<void> {
    const files = await this.findVaultNotesForId(id);
    const file = files[0];
    if (!file) return;
    if (!this.hoverMdState || this.hoverMdState.token !== token || this.hoverMdState.id !== id) return;

    const state = this.hoverMdState;
    state.filePath = file.path;

    this.closeHoverMarkdownPreview();
    this.hoverMdState = state;

    const el = document.createElement('div') as HTMLDivElement;
    el.className = 'sxdb-hovermd';

    const aw = Math.max(320, Number((this.plugin.settings as any).libraryNotePeekWidth ?? 420));
    const ah = Math.max(220, Number((this.plugin.settings as any).libraryNotePeekHeight ?? 360));
    const r = anchorEl.getBoundingClientRect();
    const x = Math.max(8, Math.min(window.innerWidth - aw - 8, Math.floor(r.right + 10)));
    const y = Math.max(8, Math.min(window.innerHeight - ah - 8, Math.floor(r.top - 8)));

    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
    el.style.width = `${aw}px`;
    el.style.height = `${ah}px`;

    const header = el.createDiv({ cls: 'sxdb-hovermd-header' });
    header.createDiv({ cls: 'sxdb-hovermd-title', text: `Preview · ${id}` });
    const btns = header.createDiv({ cls: 'sxdb-hovermd-btns' });
    const openBtn = btns.createEl('button', { text: 'Open' });
    const closeBtn = btns.createEl('button', { text: '×' });
    const body = el.createDiv({ cls: 'sxdb-hovermd-body' });

    el.addEventListener('mouseenter', () => {
      if (!this.hoverMdState) return;
      this.hoverMdState.onPopover = true;
    });
    el.addEventListener('mouseleave', () => {
      if (!this.hoverMdState) return;
      this.hoverMdState.onPopover = false;
      const t = this.hoverMdState.token;
      window.setTimeout(() => {
        if (!this.hoverMdState || this.hoverMdState.token !== t) return;
        if (this.hoverMdState.onAnchor || this.hoverMdState.onPopover) return;
        this.closeHoverMarkdownPreview();
      }, 140);
    });

    openBtn.addEventListener('click', async () => {
      await this.openVaultNoteForId(id);
      this.closeHoverMarkdownPreview();
    });
    closeBtn.addEventListener('click', () => this.closeHoverMarkdownPreview());

    try {
      const md = await this.app.vault.read(file);
      const parsed = this.extractFrontmatter(md);
      const prelude = this.buildPeekPrelude(parsed.fm);
      await MarkdownRenderer.render(this.app, `${prelude}${parsed.body}`, body, file.path, this);
      this.bindRenderedMetadataLinkBehavior(body);
    } catch {
      body.createEl('pre', { text: 'Failed to render preview.' });
    }

    document.body.appendChild(el);
    this.hoverMdEl = el;
  }

  private closeNotePeek(): void {
    this.restoreInlineNotePeekLeaf();
    if (this.notePeekEl) {
      try {
        this.notePeekEl.remove();
      } catch {
        // ignore
      }
    }
    this.notePeekEl = null;
    this.notePeekHeaderEl = null;
    this.notePeekBodyEl = null;
    this.notePeekState = null;
  }

  private getStoredNotePeekInlineLeaf(): WorkspaceLeaf | null {
    return ((this.plugin as any)._sxdbNotePeekInlineLeaf as WorkspaceLeaf | null) ?? null;
  }

  private setStoredNotePeekInlineLeaf(leaf: WorkspaceLeaf | null): void {
    (this.plugin as any)._sxdbNotePeekInlineLeaf = leaf;
  }

  private getInlineLeafContainerEl(leaf: WorkspaceLeaf | null): HTMLElement | null {
    if (!leaf) return null;
    try {
      const viewEl = (leaf as any)?.view?.containerEl as HTMLElement | null | undefined;
      if (viewEl && viewEl instanceof HTMLElement) return viewEl;
      const leafEl = (leaf as any)?.containerEl as HTMLElement | null | undefined;
      if (leafEl && leafEl instanceof HTMLElement) return leafEl;
      return null;
    } catch {
      return null;
    }
  }

  private restoreInlineNotePeekLeaf(): void {
    const leaf = this.notePeekInlineLeaf;
    if (!leaf) return;

    const el = this.getInlineLeafContainerEl(leaf);
    if (!el || !el.isConnected) {
      this.notePeekInlineLeaf = null;
      this.setStoredNotePeekInlineLeaf(null);
      return;
    }

    if (this.notePeekLeafOrigParent) {
      try {
        this.notePeekLeafOrigParent.insertBefore(el, this.notePeekLeafOrigNextSibling);
      } catch {
        // ignore
      }
    }

    this.notePeekLeafOrigParent = null;
    this.notePeekLeafOrigNextSibling = null;
  }

  private async ensureInlineNotePeekLeaf(): Promise<WorkspaceLeaf> {
    let leaf = this.getStoredNotePeekInlineLeaf();
    if (!this.isLeafValid(leaf)) leaf = null;

    if (!leaf) {
      const ws: any = this.app.workspace as any;
      const created: WorkspaceLeaf | null = (ws.getLeaf?.('split') as WorkspaceLeaf | null) ?? null;
      leaf = created ?? this.app.workspace.getLeaf(true);
      this.setStoredNotePeekInlineLeaf(leaf);
    }

    this.notePeekInlineLeaf = leaf;
    return leaf;
  }

  private mountInlineNotePeekLeaf(leaf: WorkspaceLeaf): boolean {
    const host = this.notePeekBodyEl;
    if (!host) return false;

    const el = this.getInlineLeafContainerEl(leaf);
    if (!el) return false;

    const parent = el.parentNode;
    if (parent) {
      this.notePeekLeafOrigParent = parent;
      this.notePeekLeafOrigNextSibling = el.nextSibling;
    }

    host.empty();
    host.appendChild(el);
    this.notePeekEl?.addClass('sxdb-notepeek-hasleaf');
    return true;
  }

  private async setLeafMode(leaf: WorkspaceLeaf, mode: 'source' | 'preview'): Promise<void> {
    try {
      const view: any = (leaf as any)?.view;
      const next = mode === 'source' ? 'source' : 'preview';

      if (typeof view?.setMode === 'function') {
        const result = view.setMode(next);
        if (result && typeof (result as Promise<unknown>).then === 'function') {
          await result;
        }
        return;
      }

      if (typeof view?.toggleMode === 'function') {
        const current = String(typeof view?.getMode === 'function' ? view.getMode() : 'preview');
        if (current !== next) {
          const result = view.toggleMode();
          if (result && typeof (result as Promise<unknown>).then === 'function') {
            await result;
          }
        }
      }
    } catch {
      // best-effort
    }
  }

  private async openFileInRightSplit(file: TFile): Promise<void> {
    const prior = Boolean(this.plugin.settings.openAfterPinSplit);
    (this.plugin.settings as any).openAfterPinSplit = true;
    try {
      await openPinnedFile(this.plugin, file);
    } finally {
      (this.plugin.settings as any).openAfterPinSplit = prior;
    }
  }





  private ensureNotePeek(): void {
    if (this.notePeekEl) {
      // If the view re-rendered, `contentEl.empty()` can detach the element while our refs remain.
      // Recreate if the element is no longer in the DOM (or refs were partially cleared).
      const el = this.notePeekEl as any as HTMLElement;
      if (el?.isConnected && this.notePeekBodyEl && this.notePeekState) return;
      this.closeNotePeek();
    }

    const el = this.contentEl.createDiv({ cls: 'sxdb-notepeek' });
    const header = el.createDiv({ cls: 'sxdb-notepeek-header' });
    const title = header.createDiv({ cls: 'sxdb-notepeek-title', text: 'Note Peek' });
    const headerBtns = header.createDiv({ cls: 'sxdb-notepeek-btns' });
    const modeBtn = headerBtns.createEl('button', { text: this.notePeekMode === 'source' ? 'Preview' : 'Source' });
    const openBtn = headerBtns.createEl('button', { text: 'Open' });
    const closeBtn = headerBtns.createEl('button', { text: '×' });

    const body = el.createDiv({ cls: 'sxdb-notepeek-body' });
    body.createEl('em', { text: 'No note loaded.' });

    // Default position/size.
    const w = Math.max(280, Number(this.plugin.settings.libraryNotePeekWidth ?? 420));
    const h = Math.max(220, Number(this.plugin.settings.libraryNotePeekHeight ?? 520));
    const startX = Math.max(16, Math.floor(window.innerWidth - w - 32));
    const startY = 140;

    this.notePeekState = { x: startX, y: startY, w: Math.floor(w), h: Math.floor(h), id: '', filePath: '' };

    const apply = () => {
      if (!this.notePeekState) return;
      el.style.left = `${this.notePeekState.x}px`;
      el.style.top = `${this.notePeekState.y}px`;
      el.style.width = `${this.notePeekState.w}px`;
      el.style.height = `${this.notePeekState.h}px`;
    };

    apply();

    closeBtn.addEventListener('click', () => this.closeNotePeek());

    modeBtn.addEventListener('click', async () => {
      this.notePeekMode = this.notePeekMode === 'source' ? 'preview' : 'source';
      modeBtn.setText(this.notePeekMode === 'source' ? 'Preview' : 'Source');
      const id = this.notePeekState?.id;
      if (id) void this.openNotePeekForId(id);
    });

    openBtn.addEventListener('click', async () => {
      const fp = this.notePeekState?.filePath;
      if (!fp) return;
      const af = this.app.vault.getAbstractFileByPath(fp);
      if (af && af instanceof TFile) await this.app.workspace.getLeaf(true).openFile(af);
    });

    // Drag
    header.addEventListener('pointerdown', (evt: PointerEvent) => {
      const t = evt.target as HTMLElement | null;
      if (!t) return;
      if (t.tagName === 'BUTTON') return;
      if (!this.notePeekState) return;
      evt.preventDefault();
      const start = { x: evt.clientX, y: evt.clientY, ox: this.notePeekState.x, oy: this.notePeekState.y };
      const onMove = (e: PointerEvent) => {
        if (!this.notePeekState) return;
        let nx = Math.floor(start.ox + (e.clientX - start.x));
        let ny = Math.floor(start.oy + (e.clientY - start.y));
        // Light snapping to viewport edges
        const snap = 12;
        if (Math.abs(nx - 8) <= snap) nx = 8;
        if (Math.abs(ny - 8) <= snap) ny = 8;
        const maxX = Math.max(8, window.innerWidth - this.notePeekState.w - 8);
        const maxY = Math.max(8, window.innerHeight - this.notePeekState.h - 8);
        if (Math.abs(nx - maxX) <= snap) nx = maxX;
        if (Math.abs(ny - maxY) <= snap) ny = maxY;
        this.notePeekState.x = Math.max(8, Math.min(maxX, nx));
        this.notePeekState.y = Math.max(8, Math.min(maxY, ny));
        apply();
      };
      const onUp = () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
      };
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
    });

    // Resize (bottom-right)
    const res = el.createDiv({ cls: 'sxdb-notepeek-resizer' });
    res.addEventListener('pointerdown', (evt: PointerEvent) => {
      if (!this.notePeekState) return;
      evt.preventDefault();
      evt.stopPropagation();
      const start = {
        x: evt.clientX,
        y: evt.clientY,
        w: this.notePeekState.w,
        h: this.notePeekState.h,
        ratio: this.notePeekState.w / Math.max(1, this.notePeekState.h)
      };
      const onMove = (e: PointerEvent) => {
        if (!this.notePeekState) return;
        const dw = e.clientX - start.x;
        const dh = e.clientY - start.y;
        let nw = Math.max(280, Math.floor(start.w + dw));
        let nh = Math.max(220, Math.floor(start.h + dh));
        // Aspect ratio lock if Shift is held while resizing
        if ((e as any).shiftKey) {
          nh = Math.max(220, Math.floor(nw / Math.max(0.1, start.ratio)));
        }
        this.notePeekState.w = nw;
        this.notePeekState.h = nh;
        // keep inside viewport
        this.notePeekState.x = Math.min(this.notePeekState.x, Math.max(8, window.innerWidth - nw - 8));
        this.notePeekState.y = Math.min(this.notePeekState.y, Math.max(8, window.innerHeight - nh - 8));
        apply();
      };
      const onUp = () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
      };
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
    });

    this.notePeekEl = el;
    this.notePeekHeaderEl = header;
    this.notePeekBodyEl = body;
  }

  private extractFrontmatter(md: string): { fm: Record<string, any> | null; body: string } {
    return extractFrontmatterShared(md);
  }

  private buildPeekPrelude(fm: Record<string, any> | null): string {
    return buildPeekPreludeShared(fm);
  }

  private async openNotePeekForId(id: string, evt?: MouseEvent): Promise<void> {
    if (!this.plugin.settings.libraryNotePeekEnabled) {
      new Notice('Pinned Note Peek is disabled in Settings → Views.');
      return;
    }

    const files = await this.findVaultNotesForId(id);
    const file = files[0];
    if (!file) {
      new Notice(`No vault note found for ${id}. Pin or Sync to create it.`);
      return;
    }

    const engine = this.notePeekEngine();
    
    if (engine === 'popout') {
      this.closeNotePeek();
      await this.openFileInNotePeekPopout(file);
      return;
    }
    if (engine === 'split') {
      this.closeNotePeek();
      // Experimental split behavior: force open into a right split leaf.
      await this.openFileInRightSplit(file);
      return;
    }

    // Inline mode: native Obsidian Markdown leaf mounted in SX draggable window.
    this.ensureNotePeek();
    if (!this.notePeekBodyEl || !this.notePeekState) {
      new Notice('Inline note peek could not be initialized.');
      return;
    }

    this.notePeekState.id = String(id);
    this.notePeekState.filePath = file.path;
    const title = this.notePeekEl?.querySelector('.sxdb-notepeek-title') as HTMLDivElement | null;
    if (title) title.setText(`Note Peek · ${id}`);

    try {
      const leaf = await this.ensureInlineNotePeekLeaf();
      await leaf.openFile(file);
      await this.setLeafMode(leaf, this.notePeekMode);
      const mounted = this.mountInlineNotePeekLeaf(leaf);
      if (!mounted) {
        throw new Error('Unable to mount native note leaf in inline preview window.');
      }
    } catch (e: any) {
      this.notePeekEl?.removeClass('sxdb-notepeek-hasleaf');
      this.notePeekBodyEl.empty();
      this.notePeekBodyEl.createEl('pre', { text: `Failed to render note: ${String(e?.message ?? e)}` });
    }

  }



  private async openVaultNoteForId(id: string): Promise<boolean> {
    return openVaultNoteForIdShared(
      this.app,
      id,
      this.plugin.settings.activeNotesDir,
      this.plugin.settings.bookmarksNotesDir,
      this.plugin.settings.authorsNotesDir
    );
  }

  private slugFolderName(s: string): string {
    const v = (s || '').trim().toLowerCase();
    const slug = v
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+/, '')
      .replace(/-+$/, '');
    return slug || 'unknown';
  }

  private async resolveActiveRoutingPaths(sourceId: string, profileIndex: number): Promise<{
    label: string;
    srcPath: string;
    vaultPath: string;
    assetsPath: string;
    candidateMediaRoots: string[];
  }> {
    const resp = await this.apiRequest({ path: '/pipeline/profiles' });
    const payload = (resp?.json || {}) as any;
    const profiles = Array.isArray(payload?.profiles) ? payload.profiles : [];

    let match = profiles.find((row: any) => String(row?.source_id || '').trim() === String(sourceId || '').trim());
    if (!match && Number.isFinite(profileIndex) && profileIndex >= 1) {
      const idx = Math.floor(profileIndex);
      match = profiles.find((row: any) => Number(row?.index) === idx);
    }

    const srcPath = String(match?.src_path || '').trim();
    const vaultPath = String(match?.vault_path || '').trim();
    const assetsPath = String(match?.assets_path || '').trim();
    const label = String(match?.label || '').trim();

    const candidateMediaRoots: string[] = [];
    if (srcPath) {
      const root = srcPath.replace(/[\\/]+$/, '');
      candidateMediaRoots.push(
        `${root}/_db/media_active`,
        `${root}/_db/media`,
        `${root}/media_active`,
        `${root}/media`,
        `${root}/data`
      );
    }

    return { label, srcPath, vaultPath, assetsPath, candidateMediaRoots };
  }

  private emitRoutingDiagnostics(
    trigger: 'refresh' | 'sync' | 'manual' | 'clear' | 'targeted-resync',
    ctx: { profileIndex: number; sourceId: string; schema: string },
    diag: { label: string; srcPath: string; vaultPath: string; assetsPath: string; candidateMediaRoots: string[] } | null
  ): void {
    const route = `source=${ctx.sourceId} profile=#${ctx.profileIndex}${ctx.schema ? ` schema=${ctx.schema}` : ''}`;
    if (!diag) {
      console.info(`[sxdb] ${trigger} routing: ${route}`);
      return;
    }

    const pathPart = `src=${diag.srcPath || '-'} vault=${diag.vaultPath || '-'}${diag.assetsPath ? ` assets=${diag.assetsPath}` : ''}`;
    const labelPart = diag.label ? ` label=${diag.label}` : '';
    const candidates = diag.candidateMediaRoots.length ? ` candidates=${diag.candidateMediaRoots.join(' | ')}` : '';
    console.info(`[sxdb] ${trigger} routing: ${route}${labelPart} ${pathPart}${candidates}`);

    if (trigger === 'manual' || trigger === 'clear' || trigger === 'targeted-resync') {
      new Notice(
        `Routing: ${route} · src=${diag.srcPath || '-'} · vault=${diag.vaultPath || '-'}${diag.assetsPath ? ` · assets=${diag.assetsPath}` : ''}`
      );
    }
  }

  private async ensureAlignedSchemaContext(trigger: 'refresh' | 'sync' | 'manual' | 'clear' | 'targeted-resync'): Promise<{ profileIndex: number; sourceId: string; schema: string }> {
    const p: any = this.plugin as any;
    if (typeof p.affirmAlignedSchemaContext !== 'function') {
      return {
        profileIndex: Math.max(1, Number((this.plugin.settings as any).launcherProfileIndex || 1)),
        sourceId: String((this.plugin.settings as any).activeSourceId || 'default'),
        schema: ''
      };
    }

    const aligned = await p.affirmAlignedSchemaContext();
    let schema = '';
    try {
      const health = await this.apiRequest({ path: '/health' });
      const data = (health?.json || {}) as any;
      const requestSource = String(data?.source_id || '').trim();
      schema = String(data?.backend?.schema || '').trim();

      if (requestSource && requestSource !== aligned.sourceId) {
        throw new Error(`source mismatch after affirm (expected ${aligned.sourceId}, got ${requestSource})`);
      }
    } catch (e: any) {
      throw new Error(`schema preflight failed: ${String(e?.message ?? e)}`);
    }

    const routed = {
      profileIndex: Math.max(1, Number(aligned.profileIndex || 1)),
      sourceId: String(aligned.sourceId || ''),
      schema,
    };

    let routingPaths: {
      label: string;
      srcPath: string;
      vaultPath: string;
      assetsPath: string;
      candidateMediaRoots: string[];
    } | null = null;
    try {
      routingPaths = await this.resolveActiveRoutingPaths(routed.sourceId, routed.profileIndex);
    } catch {
      routingPaths = null;
    }
    this.emitRoutingDiagnostics(trigger, routed, routingPaths);

    if (trigger === 'manual' || trigger === 'clear') {
      new Notice(
        `Schema context affirmed: profile #${aligned.profileIndex} → ${aligned.sourceId}${schema ? ` · ${schema}` : ''}`
      );
    }

    return routed;
  }

  private parseTrailingProfileIndex(value: unknown): number | null {
    const s = String(value ?? '').trim().toLowerCase();
    if (!s) return null;
    const m = s.match(/(?:^|[_-])(?:p)?(\d{1,2})$/);
    if (!m) return null;
    const n = Number(m[1]);
    if (!Number.isFinite(n) || n < 1) return null;
    return Math.floor(n);
  }

  private normalizeSourceId(value: unknown): string {
    const cleaned = String(value ?? '').trim().replace(/[^a-zA-Z0-9._-]/g, '');
    return cleaned || 'default';
  }

  private async targetedResyncAffectedNotes(): Promise<void> {
    const ctx = await this.ensureAlignedSchemaContext('targeted-resync');

    const activeRoot = normalizePath(this.plugin.settings.activeNotesDir);
    const root = this.app.vault.getAbstractFileByPath(activeRoot);
    if (!root || !(root instanceof TFolder)) {
      new Notice(`Active notes folder not found: ${activeRoot}`);
      return;
    }

    const files = this.collectMarkdownFiles(root);
    if (!files.length) {
      new Notice('No notes found in active folder.');
      return;
    }

    const affected: Array<{ file: TFile; id: string }> = [];
    for (const f of files) {
      try {
        const md = await this.app.vault.read(f);
        const { fm } = this.extractFrontmatter(md);
        const id = String((fm as any)?.id || f.basename || '').trim();
        if (!id) continue;
        // Targeted source-scoped refresh: rewrite every active-folder note id
        // against the currently affirmed source. This guarantees replacement of
        // misbound cached notes even when stale markers are absent.
        affected.push({ file: f, id });
      } catch {
        // Ignore individual parse/read issues.
      }
    }

    if (!affected.length) {
      new Notice(`No eligible notes found for targeted re-sync in ${activeRoot}.`);
      return;
    }

    let rewritten = 0;
    let deleted = 0;
    let failed = 0;
    const pathlinkerGroup = this.plugin.getPathlinkerGroupOverride();

    for (const row of affected) {
      try {
        const resp = await this.apiRequest({
          path: `/items/${encodeURIComponent(row.id)}/note`,
          query: {
            force: 'true',
            source_id: ctx.sourceId,
            ...(pathlinkerGroup ? { pathlinker_group: pathlinkerGroup } : {})
          }
        });
        const data = (resp?.json || {}) as { markdown?: string };
        const markdown = String(data?.markdown || '');
        if (!markdown.trim()) {
          failed += 1;
          continue;
        }

        await this.app.vault.modify(row.file, markdown);
        this.plugin.markRecentlyWritten(row.file.path);
        await this.normalizeTagsFrontmatterInFile(row.file, markdown);
        rewritten += 1;
      } catch (e: any) {
        const msg = String(e?.message ?? e);
        if (/404|Not found/i.test(msg)) {
          try {
            await this.app.vault.delete(row.file);
            deleted += 1;
          } catch {
            failed += 1;
          }
        } else {
          failed += 1;
        }
      }
    }

    new Notice(
      `Targeted source re-sync complete: source=${ctx.sourceId}${ctx.schema ? ` · schema=${ctx.schema}` : ''} · scanned ${files.length}, rewritten ${rewritten}, deleted ${deleted}, failed ${failed}.`
    );

    void this.refresh();
  }

  /** Command hook: materialize current table selection into vault (_db folders). */
  async syncCurrentSelection(): Promise<void> {
    await this.ensureAlignedSchemaContext('sync');

    const batch = Math.max(10, this.plugin.settings.syncBatchSize ?? 200);
    const maxItems = Math.max(0, this.plugin.settings.syncMaxItems ?? 2000);
    const replace = Boolean(this.plugin.settings.syncReplaceOnPull);
    const strategy = String(this.plugin.settings.vaultWriteStrategy || 'split');
    const force = Boolean(this.plugin.settings.fetchForceRegenerate);
    const pathlinkerGroup = this.plugin.getPathlinkerGroupOverride();

    const baseParams: Record<string, string> = {
      q: this.q,
      bookmarked_only: this.bookmarkedOnly ? 'true' : 'false',
      order: this.sortOrder
    };
    if (this.authorFilter) baseParams.author_unique_id = this.authorFilter;
    if (this.statusFilters.size) baseParams.status = Array.from(this.statusFilters).join(',');
    if (this.tagFilter.trim()) baseParams.tag = this.tagFilter.trim();
    if (this.captionFilter.trim()) baseParams.caption_q = this.captionFilter.trim();
    if (this.ratingMin.trim()) baseParams.rating_min = this.ratingMin.trim();
    if (this.ratingMax.trim()) baseParams.rating_max = this.ratingMax.trim();
    if (this.hasNotesOnly) baseParams.has_notes = 'true';
    let offset = 0;
    let written = 0;
    let total = 0;

    new Notice('Sync starting…');

    // Optional replacement: only safe when we know we will write into a single destination folder.
    if (replace) {
      try {
        if (strategy === 'active-only') {
          new Notice('Replace-on-pull is ignored for active-only strategy (to avoid deleting canonical notes).');
        } else if (this.bookmarkedOnly) {
          const destDir = normalizePath(this.plugin.settings.bookmarksNotesDir);
          await this.ensureFolder(destDir);
          const deleted = await this.clearFolderMarkdown(destDir);
          if (deleted) new Notice(`Cleared ${deleted} note(s) in ${destDir} before sync.`);
        } else {
          new Notice('Replace-on-pull is enabled, but current filters may write into multiple folders; skipping clear for safety.');
        }
      } catch (e: any) {
        // eslint-disable-next-line no-console
        console.warn('[sx-obsidian-db] clear before sync failed', e);
      }
    }

    while (true) {
      if (maxItems && written >= maxItems) {
        new Notice(`Sync stopped at safety cap (${maxItems}).`);
        break;
      }

      const limit = maxItems ? Math.min(batch, maxItems - written) : batch;
      const resp = await this.apiRequest({
        path: '/notes',
        query: {
          ...baseParams,
          ...(force ? { force: 'true' } : {}),
          ...(pathlinkerGroup ? { pathlinker_group: pathlinkerGroup } : {}),
          limit: String(limit),
          offset: String(offset)
        }
      });
      const data = resp.json as { notes: ApiNote[]; total: number; offset: number; limit: number };
      const notes = data.notes ?? [];
      total = data.total ?? total;

      if (!notes.length) break;

      for (const n of notes) {
        const id = n.id;
        const md = n.markdown;
        if (!md) continue;

        const activeDir = normalizePath(this.plugin.settings.activeNotesDir);
        const bookmarksDir = normalizePath(this.plugin.settings.bookmarksNotesDir);
        const authorDir = normalizePath(
          `${this.plugin.settings.authorsNotesDir}/${this.slugFolderName(String(n.author_unique_id ?? n.author_name ?? 'unknown'))}`
        );

        const destDirs =
          strategy === 'active-only'
            ? [activeDir]
            : n.bookmarked
              ? [bookmarksDir, authorDir]
              : [authorDir];

        for (const destDir of destDirs) {
          const targetPath = normalizePath(`${destDir}/${id}.md`);
          await this.ensureFolder(destDir);

          const existing = this.app.vault.getAbstractFileByPath(targetPath);
          let writtenMd = md;
          if (existing && existing instanceof TFile) {
            const prev = await this.app.vault.read(existing);
            const merged = mergeMarkdownPreservingUserEdits(prev, md);
            await this.app.vault.modify(existing, merged);
            writtenMd = merged;
          } else {
            await this.app.vault.create(targetPath, md);
          }
          this.plugin.markRecentlyWritten(targetPath);

          // If the note contains tags in frontmatter, normalize them to Obsidian's preferred YAML list format.
          const af = this.app.vault.getAbstractFileByPath(targetPath);
          if (af && af instanceof TFile) await this.normalizeTagsFrontmatterInFile(af, writtenMd);
        }

        written += 1;
      }

      offset += notes.length;
      if (notes.length < limit) break;
    }

    if (written === 0) {
      const activeFilters: string[] = [];
      if (this.q.trim()) activeFilters.push(`search=${this.q.trim()}`);
      if (this.bookmarkedOnly) activeFilters.push('bookmarked_only=true');
      if (this.authorFilter.trim()) activeFilters.push(`author=${this.authorFilter.trim()}`);
      if (this.statusFilters.size) activeFilters.push(`status=${Array.from(this.statusFilters).join(',')}`);
      if (this.tagFilter.trim()) activeFilters.push(`tag=${this.tagFilter.trim()}`);
      if (this.captionFilter.trim()) activeFilters.push('caption_q=*');
      if (this.ratingMin.trim()) activeFilters.push(`rating_min=${this.ratingMin.trim()}`);
      if (this.ratingMax.trim()) activeFilters.push(`rating_max=${this.ratingMax.trim()}`);
      if (this.hasNotesOnly) activeFilters.push('has_notes=true');

      if (activeFilters.length) {
        new Notice(
          `Sync complete: wrote 0 note(s). Current filters matched no rows (${activeFilters.join(' · ')}). Try Clear or reset Filters.`
        );
      } else {
        try {
          const probe = await this.apiRequest({
            path: '/items',
            query: {
              q: '',
              limit: '1',
              offset: '0',
              bookmarked_only: 'false',
              order: 'recent'
            }
          });
          const probeTotal = Number((probe?.json as any)?.total ?? 0);
          if (probeTotal > 0) {
            new Notice(
              'Sync complete: wrote 0 note(s). The source has data, but current selection is empty. Click Clear, then Sync again.'
            );
          } else {
            new Notice('Sync complete: wrote 0 note(s). Source currently has no rows. Re-import data for this source/profile.');
          }
        } catch {
          new Notice('Sync complete: wrote 0 note(s).');
        }
      }
    } else {
      new Notice(`Sync complete: wrote ${written} note(s).`);
    }

    // refresh current page (optional) so user sees updated counts/status etc.
    void this.refresh();
  }

  /** Command hook: refresh current table page from API using current filters. */
  async refresh(): Promise<void> {
    await this.ensureAlignedSchemaContext('refresh');

    const limit = this.pageLimit();

    const params: Record<string, string> = {
      q: this.q,
      limit: String(limit),
      offset: String(this.offset),
      bookmarked_only: this.bookmarkedOnly ? 'true' : 'false',
      order: this.sortOrder
    };
    if (this.authorFilter) params.author_unique_id = this.authorFilter;
    if (this.statusFilters.size) params.status = Array.from(this.statusFilters).join(',');
    if (this.tagFilter.trim()) params.tag = this.tagFilter.trim();
    if (this.captionFilter.trim()) params.caption_q = this.captionFilter.trim();
    if (this.ratingMin.trim()) params.rating_min = this.ratingMin.trim();
    if (this.ratingMax.trim()) params.rating_max = this.ratingMax.trim();
    if (this.hasNotesOnly) params.has_notes = 'true';

    try {
      const resp = await this.apiRequest({ path: '/items', query: params });
      const data = resp.json as { items: ApiItem[]; total: number; offset: number; limit: number };
      this.total = data.total ?? 0;
      this.offset = data.offset ?? 0;
      this.lastItems = data.items ?? [];
      this.lastLimit = limit;
      this.renderTable(this.lastItems, limit);
    } catch (e: any) {
      this.contentEl.createEl('pre', { text: String(e?.message ?? e) });
    }
  }

  private async loadAuthors(): Promise<void> {
    try {
      const resp = await this.apiRequest({ path: '/authors', query: { limit: '2000', offset: '0', order: 'count' } });
      const data = resp.json as { authors: ApiAuthor[] };
      this.authors = (data?.authors ?? []).filter((a) => a?.author_unique_id);
      this.populateAuthorSelect();
    } catch (e: any) {
      // Non-fatal; table view still works without author filtering.
      this.authors = [];
      this.populateAuthorSelect();
    }
  }

  private populateAuthorSelect(): void {
    if (!this.authorSel) return;

    this.authorSel.empty();
    this.authorSel.createEl('option', { value: '', text: 'All authors' });
    const search = (this.authorSearch || '').trim().toLowerCase();
    const authors = search
      ? this.authors.filter((a) => {
          const label = `${a.author_id ?? ''} ${a.author_unique_id ?? ''} ${a.author_name ?? ''} ${a.items_count}`.toLowerCase();
          return label.includes(search);
        })
      : this.authors;

    for (const a of authors) {
      const idPart = (a.author_id ?? '').trim() || a.author_unique_id;
      const namePart = (a.author_name ?? '').trim();
      const handlePart = a.author_unique_id && a.author_unique_id !== idPart ? `@${a.author_unique_id}` : '';
      const label = `${idPart}${namePart ? ` — ${namePart}` : ''}${handlePart ? ` (${handlePart})` : ''} · ${a.items_count}`;
      const opt = this.authorSel.createEl('option', { value: a.author_unique_id, text: label });
      if (this.authorFilter === a.author_unique_id) opt.selected = true;
    }
    this.authorSel.disabled = this.authors.length === 0;
  }

  private render(): void {
    const { contentEl } = this;
    contentEl.empty();

    contentEl.addClass('sxdb-lib-root');

    if (this.menuHidden) contentEl.addClass('sxdb-menu-hidden');
    else contentEl.removeClass('sxdb-menu-hidden');

    // Table wrapping mode (legacy setting name kept for compatibility)
    const idWrap = String(this.plugin.settings.libraryIdWrapMode || 'ellipsis');
    contentEl.setAttr('data-sxdb-idwrap', idWrap);

    // Apply hover preview sizing via CSS variables (so it updates without CSS edits).
    const { w, h } = this.getHoverVideoSizePx();
    contentEl.style.setProperty('--sxdb-hovervideo-width', `${Math.floor(w)}px`);
    contentEl.style.setProperty('--sxdb-hovervideo-height', `${Math.floor(h)}px`);

    const header = contentEl.createDiv({ cls: 'sxdb-lib-header' });
    header.createEl('h2', { text: 'SX Library (DB)' });
    const routing = (this.plugin as any).getRoutingDebugInfo?.();
    if (routing && typeof routing === 'object') {
      const configuredProfile = routing.configuredProfile != null ? String(routing.configuredProfile) : '—';
      const effectiveProfile = routing.effectiveProfile != null ? String(routing.effectiveProfile) : '—';
      const adjusted = Boolean(routing.effectiveSourceAdjusted);
      const mismatched = Boolean(routing.mismatchDetected);
      const marker = mismatched ? '⚠' : (adjusted ? '↺' : '•');
      const line = `source=${routing.configuredSource} · profile=${configuredProfile} · effective_source=${routing.effectiveSource} · effective_profile=${effectiveProfile}`;
      const debug = header.createDiv({ cls: 'sxdb-lib-routing-debug' });
      debug.setText(`${marker} ${line}`);
      if (mismatched) debug.addClass('is-warning');
      else if (adjusted) debug.addClass('is-adjusted');
      debug.setAttr(
        'title',
        `Alignment: ${routing.alignmentEnabled ? 'on' : 'off'} · Schema guard: ${routing.schemaGuardEnabled ? 'on' : 'off'} · source_idx=${routing.configuredSourceIndex ?? '—'} · effective_source_idx=${routing.effectiveSourceIndex ?? '—'}`
      );
      void this.hydrateRoutingDebugLine(debug, routing);
    }

    // Sheets-like top menubar (dropdowns live here so they appear above the table)
    const menubar = contentEl.createDiv({ cls: 'sxdb-lib-menubar' });
    const menuBtns = menubar.createDiv({ cls: 'sxdb-lib-menubar-btns' });
    const popoverHost = menubar.createDiv({ cls: 'sxdb-lib-menubar-popovers' });

    const toolbar = contentEl.createDiv({ cls: 'sxdb-lib-toolbarrow' });
    const controls = toolbar.createDiv({ cls: 'sxdb-lib-controls' });
    const actions = toolbar.createDiv({ cls: 'sxdb-lib-actions' });

    // Toolbar: show/hide menubar (Google Sheets-style)
    const menuToggleBtn = actions.createEl('button', { text: this.menuHidden ? 'Show menu' : 'Hide menu' });
    menuToggleBtn.addEventListener('click', () => {
      this.menuHidden = !this.menuHidden;
      if (this.menuHidden) contentEl.addClass('sxdb-menu-hidden');
      else contentEl.removeClass('sxdb-menu-hidden');
      menuToggleBtn.setText(this.menuHidden ? 'Show menu' : 'Hide menu');
      this.persistLibraryStateDebounced();

      window.setTimeout(() => this.updateStickyOffsets(), 0);
    });

    // Menubar: quick actions
    const refreshBtn = menuBtns.createEl('button', { text: 'Refresh', cls: 'sxdb-lib-menubtn' });
    refreshBtn.addEventListener('click', () => void this.refresh());

    const affirmBtn = menuBtns.createEl('button', { text: 'Affirm schema', cls: 'sxdb-lib-menubtn' });
    affirmBtn.addEventListener('click', () => {
      void this.ensureAlignedSchemaContext('manual').then(() => {
        void this.refresh();
      }).catch((e: any) => {
        new Notice(`Affirm schema failed: ${String(e?.message ?? e)}`);
      });
    });

    const syncTopBtn = menuBtns.createEl('button', { text: 'Sync', cls: 'sxdb-lib-menubtn' });
    syncTopBtn.addEventListener('click', () => {
      void this.syncCurrentSelection().catch((e: any) => {
        new Notice(`Sync failed: ${String(e?.message ?? e)}`);
      });
    });

    const clearTopBtn = menuBtns.createEl('button', { text: 'Clear', cls: 'sxdb-lib-menubtn' });
    clearTopBtn.addEventListener('click', () => {
      void this.ensureAlignedSchemaContext('clear').then(() => {
        this.q = '';
        this.bookmarkedOnly = false;
        this.bookmarkFrom = '';
        this.bookmarkTo = '';
        this.authorFilter = '';
        this.statusFilters.clear();
        this.sortOrder = 'bookmarked';
        this.tagFilter = '';
        this.captionFilter = '';
        this.ratingMin = '';
        this.ratingMax = '';
        this.hasNotesOnly = false;
        this.authorSearch = '';
        this.offset = 0;
        this.persistLibraryStateDebounced();
        this.render();
        void this.refresh();
      }).catch((e: any) => {
        new Notice(`Clear failed: ${String(e?.message ?? e)}`);
      });
    });

    const clearResyncTopBtn = menuBtns.createEl('button', { text: 'Clear + Re-sync', cls: 'sxdb-lib-menubtn' });
    clearResyncTopBtn.addEventListener('click', () => {
      void this.targetedResyncAffectedNotes().catch((e: any) => {
        new Notice(`Targeted re-sync failed: ${String(e?.message ?? e)}`);
      });
    });

    // Menubar: Data dropdown (currently holds Pin folder info)
    const dataTopBtn = menuBtns.createEl('button', { text: 'Data', cls: 'sxdb-lib-menubtn' });
    dataTopBtn.addEventListener('click', () => {
      const existing = popoverHost.querySelector('.sxdb-lib-datamenu') as HTMLDivElement | null;
      if (existing) {
        existing.remove();
        return;
      }

      popoverHost.empty();
      const panel = popoverHost.createDiv({ cls: 'sxdb-lib-viewmenu sxdb-lib-datamenu' });
      panel.createEl('div', { text: 'Data', cls: 'sxdb-lib-columns-title' });

      const pinDir = normalizePath(this.plugin.settings.activeNotesDir);
      panel.createEl('div', { text: 'Pin folder', cls: 'sxdb-lib-viewmenu-section' });
      const pinRow = panel.createDiv({ cls: 'sxdb-lib-toggle' });
      pinRow.createEl('code', { text: pinDir });
      const copyBtn = pinRow.createEl('button', { text: 'Copy' });
      copyBtn.addEventListener('click', () => {
        void this.copyToClipboard(pinDir).then((ok) => {
          if (ok) new Notice('Copied pin folder path');
        });
      });

      const closePanel = () => {
        try {
          panel.remove();
        } catch {
          // ignore
        }
        document.removeEventListener('mousedown', onDoc, true);
        document.removeEventListener('keydown', onKey);
      };

      const onDoc = (evt: MouseEvent) => {
        const t = evt.target as any;
        if (!t) return;
        if (panel.contains(t)) return;
        if (dataTopBtn.contains(t)) return;
        closePanel();
      };

      const onKey = (evt: KeyboardEvent) => {
        if (evt.key === 'Escape') closePanel();
      };

      window.setTimeout(() => {
        document.addEventListener('mousedown', onDoc, true);
        document.addEventListener('keydown', onKey);
      }, 0);
    });

    // Menubar: Filters dropdown (moves most controls out of the toolbar for a cleaner look)
    const filtersTopBtn = menuBtns.createEl('button', { text: 'Filters', cls: 'sxdb-lib-menubtn' });
    filtersTopBtn.addEventListener('click', () => {
      const existing = popoverHost.querySelector('.sxdb-lib-filtersmenu') as HTMLDivElement | null;
      if (existing) {
        existing.remove();
        // If the panel is closed, drop the select ref so future async author loads don't write to a dead element.
        this.authorSel = null;
        return;
      }

      popoverHost.empty();
      const panel = popoverHost.createDiv({ cls: 'sxdb-lib-filtersmenu' });
      panel.createEl('div', { text: 'Filters', cls: 'sxdb-lib-columns-title' });
      panel.createEl('div', { text: 'These settings affect both the table and Sync selection.', cls: 'sxdb-lib-columns-subtitle' });

      // Sort order
      const sortWrap = panel.createDiv({ cls: 'sxdb-lib-toggle' });
      sortWrap.createSpan({ text: 'Sort:' });
      const sortSel = sortWrap.createEl('select');
      const sortOptions: Array<{ value: LibraryView['sortOrder']; label: string }> = [
        { value: 'bookmarked', label: 'Bookmark date' },
        { value: 'recent', label: 'Recent' },
        { value: 'author', label: 'Author' },
        { value: 'status', label: 'Status' },
        { value: 'rating', label: 'Rating' }
      ];
      for (const opt of sortOptions) {
        const o = sortSel.createEl('option', { value: opt.value, text: opt.label });
        if (this.sortOrder === opt.value) o.selected = true;
      }
      sortSel.addEventListener('change', () => {
        const v = (sortSel.value || 'bookmarked') as LibraryView['sortOrder'];
        this.sortOrder = v;
        this.offset = 0;
        this.persistLibraryStateDebounced();
        void this.refresh();
      });

      // Tag filter
      const tagWrap = panel.createDiv({ cls: 'sxdb-lib-toggle' });
      tagWrap.createSpan({ text: 'Tag:' });
      const tagInput = tagWrap.createEl('input', { type: 'text', placeholder: 'e.g. skincare,vitamin-c' });
      tagInput.value = this.tagFilter;
      tagInput.addEventListener('input', () => {
        this.tagFilter = tagInput.value;
        this.offset = 0;
        this.persistLibraryStateDebounced();
        window.clearTimeout((this as any)._t2);
        (this as any)._t2 = window.setTimeout(() => void this.refresh(), Math.max(0, this.plugin.settings.debounceMs ?? 250));
      });

      // Caption-only search (more precise than global q; matches caption content)
      const capWrap = panel.createDiv({ cls: 'sxdb-lib-toggle' });
      capWrap.createSpan({ text: 'Caption:' });
      const capInput = capWrap.createEl('input', {
        type: 'text',
        placeholder: 'contains… (e.g. furniture, "mid century", -broken)'
      });
      capInput.value = this.captionFilter;
      capInput.addEventListener('input', () => {
        this.captionFilter = capInput.value;
        this.offset = 0;
        this.persistLibraryStateDebounced();
        window.clearTimeout((this as any)._tCap);
        (this as any)._tCap = window.setTimeout(() => void this.refresh(), Math.max(0, this.plugin.settings.debounceMs ?? 250));
      });

      // Rating filter
      const ratingWrap = panel.createDiv({ cls: 'sxdb-lib-toggle' });
      ratingWrap.createSpan({ text: 'Rating:' });
      const rMin = ratingWrap.createEl('input', { type: 'number' });
      rMin.placeholder = 'min';
      rMin.min = '0';
      rMin.max = '5';
      rMin.step = '1';
      rMin.value = this.ratingMin;
      rMin.style.width = '64px';
      const rMax = ratingWrap.createEl('input', { type: 'number' });
      rMax.placeholder = 'max';
      rMax.min = '0';
      rMax.max = '5';
      rMax.step = '1';
      rMax.value = this.ratingMax;
      rMax.style.width = '64px';

      const onRatingChange = () => {
        this.ratingMin = rMin.value;
        this.ratingMax = rMax.value;
        this.offset = 0;
        this.persistLibraryStateDebounced();
        void this.refresh();
      };
      rMin.addEventListener('change', onRatingChange);
      rMax.addEventListener('change', onRatingChange);

      // Has-notes filter
      const notesWrap = panel.createDiv({ cls: 'sxdb-lib-toggle' });
      const notesCb = notesWrap.createEl('input', { type: 'checkbox' });
      notesCb.checked = this.hasNotesOnly;
      notesCb.addEventListener('change', () => {
        this.hasNotesOnly = notesCb.checked;
        this.offset = 0;
        this.persistLibraryStateDebounced();
        void this.refresh();
      });
      notesWrap.createSpan({ text: 'Has notes' });

      // Author filter
      const authorWrap = panel.createDiv({ cls: 'sxdb-lib-toggle' });
      authorWrap.createSpan({ text: 'Author:' });
      const authorSearch = authorWrap.createEl('input', { type: 'text', placeholder: 'filter…' });
      authorSearch.value = this.authorSearch;
      authorSearch.style.width = '140px';
      authorSearch.addEventListener('input', () => {
        this.authorSearch = authorSearch.value;
        this.persistLibraryStateDebounced();
        this.populateAuthorSelect();
      });

      this.authorSel = authorWrap.createEl('select');
      this.authorSel.createEl('option', { value: '', text: this.authors.length ? 'All authors' : 'Loading…' });
      this.authorSel.addEventListener('change', () => {
        this.authorFilter = this.authorSel?.value ?? '';
        this.offset = 0;
        this.persistLibraryStateDebounced();
        void this.refresh();
      });
      this.populateAuthorSelect();

      const actionsRow = panel.createDiv({ cls: 'sxdb-lib-columns-actions' });
      const closeBtn = actionsRow.createEl('button', { text: 'Close' });
      closeBtn.addEventListener('click', () => {
        try {
          panel.remove();
        } catch {
          // ignore
        }
        this.authorSel = null;
      });

      const closePanel = () => {
        try {
          panel.remove();
        } catch {
          // ignore
        }
        this.authorSel = null;
        document.removeEventListener('mousedown', onDoc, true);
        document.removeEventListener('keydown', onKey);
      };

      const onDoc = (evt: MouseEvent) => {
        const t = evt.target as any;
        if (!t) return;
        if (panel.contains(t)) return;
        if (filtersTopBtn.contains(t)) return;
        closePanel();
      };

      const onKey = (evt: KeyboardEvent) => {
        if (evt.key === 'Escape') closePanel();
      };

      window.setTimeout(() => {
        document.addEventListener('mousedown', onDoc, true);
        document.addEventListener('keydown', onKey);
      }, 0);
    });

    // Menubar: Columns dropdown
    const colsTopBtn = menuBtns.createEl('button', { text: 'Columns', cls: 'sxdb-lib-menubtn' });
    colsTopBtn.addEventListener('click', () => {
      const existing = popoverHost.querySelector('.sxdb-lib-columns') as HTMLDivElement | null;
      if (existing) {
        existing.remove();
        return;
      }

      popoverHost.empty();
      const panel = popoverHost.createDiv({ cls: 'sxdb-lib-columns' });
      panel.createEl('div', { text: 'Columns', cls: 'sxdb-lib-columns-title' });

      const closePanel = () => {
        try {
          panel.remove();
        } catch {
          // ignore
        }
        document.removeEventListener('mousedown', onDoc, true);
        document.removeEventListener('keydown', onKey);
      };

      const onDoc = (evt: MouseEvent) => {
        const t = evt.target as any;
        if (!t) return;
        if (panel.contains(t)) return;
        if (colsTopBtn.contains(t)) return;
        closePanel();
      };

      const onKey = (evt: KeyboardEvent) => {
        if (evt.key === 'Escape') closePanel();
      };

      // Attach after the current click stack so we don't instantly close.
      window.setTimeout(() => {
        document.addEventListener('mousedown', onDoc, true);
        document.addEventListener('keydown', onKey);
      }, 0);

        panel.createEl('div', { text: 'Drag to reorder · Toggle to show/hide · Width is a number (px)', cls: 'sxdb-lib-columns-subtitle' });

        const defs: Array<{ key: keyof LibraryView['columns']; label: string }> = [
          { key: 'index', label: '#' },
          { key: 'thumb', label: 'Thumb' },
          { key: 'id', label: 'ID' },
          { key: 'author', label: 'Author' },
          { key: 'bookmarked', label: '★' },
          { key: 'caption', label: 'Caption' },
          { key: 'status', label: 'Status' },
          { key: 'rating', label: 'Rating' },
          { key: 'tags', label: 'Tags' },
          { key: 'notes', label: 'Notes' },
          { key: 'product_link', label: 'Product link' },
          { key: 'author_links', label: 'Author links' },
          { key: 'platform_targets', label: 'Platform targets' },
          { key: 'post_url', label: 'Post URL' },
          { key: 'published_time', label: 'Published time' },
          { key: 'workflow_log', label: 'Workflow log' },
          { key: 'actions', label: 'Actions' }
        ];

        const allKeys = defs.map((d) => d.key as string);
        const order: string[] = [];
        const seen = new Set<string>();
        for (const k of (Array.isArray(this.columnOrder) ? this.columnOrder : [])) {
          if (typeof k !== 'string') continue;
          if (!allKeys.includes(k)) continue;
          if (seen.has(k)) continue;
          seen.add(k);
          order.push(k);
        }
        for (const k of allKeys) {
          if (!seen.has(k)) order.push(k);
        }

        const list = panel.createDiv({ cls: 'sxdb-lib-columns-list' });

        const renderList = () => {
          list.empty();
          for (const key of order) {
            const def = defs.find((d) => d.key === (key as any));
            if (!def) continue;
            const row = list.createDiv({ cls: 'sxdb-lib-colopt' });
            row.setAttr('draggable', 'true');
            row.setAttr('data-colkey', def.key as string);

            const drag = row.createSpan({ text: '↕', cls: 'sxdb-lib-coldrag' });
            drag.setAttr('aria-label', 'Drag to reorder');

            const cb = row.createEl('input', { type: 'checkbox' });
            cb.checked = Boolean(this.columns[def.key]);
            cb.addEventListener('change', () => {
              // Prevent a state where every column becomes hidden.
              const nextVisibleCount = Object.keys(this.columns)
                .filter((k) => {
                  if (k === (def.key as string)) return cb.checked;
                  return Boolean(this.columns[k]);
                })
                .length;
              if (!nextVisibleCount) {
                cb.checked = true;
                new Notice('At least one column must remain visible.');
                return;
              }
              this.columns[def.key] = cb.checked;
              this.persistLibraryColumnsDebounced();
              this.renderTable(this.lastItems, this.lastLimit);
            });

            row.createSpan({ text: def.label, cls: 'sxdb-lib-colname' });

            const w = row.createEl('input', { type: 'number' });
            w.min = '40';
            w.step = '10';
            w.value = this.columnWidths[def.key as string] ? String(this.columnWidths[def.key as string]) : '';
            w.style.width = '72px';
            w.setAttr('aria-label', 'Column width (px)');
            w.addEventListener('change', () => {
              const n = Number(w.value);
              if (!Number.isFinite(n) || n <= 0) {
                delete this.columnWidths[def.key as string];
              } else {
                this.columnWidths[def.key as string] = Math.max(40, Math.floor(n));
              }
              this.persistLibraryLayoutDebounced();
              this.renderTable(this.lastItems, this.lastLimit);
            });

            row.addEventListener('dragstart', (evt) => {
              try {
                evt.dataTransfer?.setData('text/plain', def.key as string);
                evt.dataTransfer!.effectAllowed = 'move';
              } catch {
                // ignore
              }
            });
            row.addEventListener('dragover', (evt) => {
              evt.preventDefault();
              try {
                evt.dataTransfer!.dropEffect = 'move';
              } catch {
                // ignore
              }
            });
            row.addEventListener('drop', (evt) => {
              evt.preventDefault();
              const src = (() => {
                try {
                  return evt.dataTransfer?.getData('text/plain') || '';
                } catch {
                  return '';
                }
              })();
              const dst = def.key as string;
              if (!src || src === dst) return;
              const si = order.indexOf(src);
              const di = order.indexOf(dst);
              if (si === -1 || di === -1) return;
              order.splice(si, 1);
              const insertAt = si < di ? di - 1 : di;
              order.splice(insertAt, 0, src);
              this.columnOrder = [...order];
              this.persistLibraryLayoutDebounced();
              renderList();
              this.renderTable(this.lastItems, this.lastLimit);
            });
          }
        };

        renderList();

        const actionsRow = panel.createDiv({ cls: 'sxdb-lib-columns-actions' });

        const autoBtn = actionsRow.createEl('button', { text: 'Auto-fit' });
        autoBtn.addEventListener('click', () => {
          this.columnWidths = {};
          this.persistLibraryLayoutDebounced();
          renderList();
          this.renderTable(this.lastItems, this.lastLimit);
        });

        const resetColsBtn = actionsRow.createEl('button', { text: 'Reset columns' });
        resetColsBtn.addEventListener('click', () => {
          this.columns = Object.assign({}, this.DEFAULT_COLUMNS);
          this.persistLibraryColumnsDebounced();
          renderList();
          this.renderTable(this.lastItems, this.lastLimit);
        });

        const showAllBtn = actionsRow.createEl('button', { text: 'Show all' });
        showAllBtn.addEventListener('click', () => {
          for (const k of allKeys) this.columns[k] = true;
          this.persistLibraryColumnsDebounced();
          renderList();
          this.renderTable(this.lastItems, this.lastLimit);
        });

        const resetBtn = actionsRow.createEl('button', { text: 'Reset layout' });
        resetBtn.addEventListener('click', () => {
          this.columnOrder = defs.map((d) => d.key as string);
          this.columnWidths = {};
          this.persistLibraryLayoutDebounced();
          renderList();
          this.renderTable(this.lastItems, this.lastLimit);
        });

        const close = actionsRow.createEl('button', { text: 'Close' });
        close.addEventListener('click', () => panel.remove());
      });

      // Menubar: View dropdown (small UX toggles)
      const viewTopBtn = menuBtns.createEl('button', { text: 'View', cls: 'sxdb-lib-menubtn' });
      viewTopBtn.addEventListener('click', () => {
        const existing = popoverHost.querySelector('.sxdb-lib-viewmenu') as HTMLDivElement | null;
        if (existing) {
          existing.remove();
          return;
        }

        popoverHost.empty();
        const panel = popoverHost.createDiv({ cls: 'sxdb-lib-viewmenu' });
        panel.createEl('div', { text: 'View', cls: 'sxdb-lib-columns-title' });
        panel.createEl('div', { text: 'Cell wrapping', cls: 'sxdb-lib-viewmenu-section' });

        const modes: Array<{ id: 'ellipsis' | 'clip' | 'wrap'; label: string }> = [
          { id: 'ellipsis', label: 'Overflow: ellipsis' },
          { id: 'clip', label: 'Overflow: clip' },
          { id: 'wrap', label: 'Wrap' }
        ];
        const cur = String(this.plugin.settings.libraryIdWrapMode || 'ellipsis') as any;

        for (const m of modes) {
          const row = panel.createEl('label', { cls: 'sxdb-lib-viewmenu-row' });
          const rb = row.createEl('input', { type: 'radio' });
          rb.name = 'sxdb-idwrap';
          rb.checked = cur === m.id;
          row.createSpan({ text: m.label });
          rb.addEventListener('change', () => {
            if (!rb.checked) return;
            this.plugin.settings.libraryIdWrapMode = m.id;
            void this.plugin.saveSettings();
            this.contentEl.setAttr('data-sxdb-idwrap', m.id);
            this.renderTable(this.lastItems, this.lastLimit);
          });
        }

        panel.createEl('div', { text: 'Freeze panes', cls: 'sxdb-lib-viewmenu-section' });

        const freezeOpts: Array<{ v: 0 | 1 | 2; label: string }> = [
          { v: 0, label: 'No frozen columns' },
          { v: 1, label: 'Freeze ID column' },
          { v: 2, label: 'Freeze Thumb + ID columns' }
        ];

        for (const opt of freezeOpts) {
          const row = panel.createEl('label', { cls: 'sxdb-lib-viewmenu-row' });
          const rb = row.createEl('input', { type: 'radio' });
          rb.name = 'sxdb-freezecols';
          rb.checked = this.freezeCols === opt.v;
          row.createSpan({ text: opt.label });
          rb.addEventListener('change', () => {
            if (!rb.checked) return;
            this.freezeCols = opt.v;
            this.persistLibraryStateDebounced();
            this.renderTable(this.lastItems, this.lastLimit);
          });
        }

        const frRow = panel.createEl('label', { cls: 'sxdb-lib-viewmenu-row' });
        const frCb = frRow.createEl('input', { type: 'checkbox' });
        frCb.checked = Boolean(this.freezeFirstRow);
        frRow.createSpan({ text: 'Freeze first data row' });
        frCb.addEventListener('change', () => {
          this.freezeFirstRow = Boolean(frCb.checked);
          this.persistLibraryStateDebounced();
          this.renderTable(this.lastItems, this.lastLimit);
        });

        const closePanel = () => {
          try {
            panel.remove();
          } catch {
            // ignore
          }
          document.removeEventListener('mousedown', onDoc, true);
          document.removeEventListener('keydown', onKey);
        };

        const onDoc = (evt: MouseEvent) => {
          const t = evt.target as any;
          if (!t) return;
          if (panel.contains(t)) return;
          if (viewTopBtn.contains(t)) return;
          closePanel();
        };

        const onKey = (evt: KeyboardEvent) => {
          if (evt.key === 'Escape') closePanel();
        };

        window.setTimeout(() => {
          document.addEventListener('mousedown', onDoc, true);
          document.addEventListener('keydown', onKey);
        }, 0);
      });

    const qInput = controls.createEl('input', { type: 'text', placeholder: 'Search…' });
    qInput.value = this.q;
    qInput.addEventListener('input', () => {
      this.q = qInput.value.trim();
      this.offset = 0;
      this.persistLibraryStateDebounced();
      // small debounce
      window.clearTimeout((this as any)._t);
      (this as any)._t = window.setTimeout(() => void this.refresh(), Math.max(0, this.plugin.settings.debounceMs ?? 250));
    });

    const bmWrap = controls.createDiv({ cls: 'sxdb-lib-toggle' });
    const bm = bmWrap.createEl('input', { type: 'checkbox' });
    bm.checked = this.bookmarkedOnly;
    bm.addEventListener('change', () => {
      this.bookmarkedOnly = bm.checked;
      this.offset = 0;
      this.persistLibraryStateDebounced();
      this.render();
      void this.refresh();
    });
    bmWrap.createSpan({ text: 'Bookmarked only' });

    // Status filter (drives a “work queue” without generating notes)
    const statusWrap = controls.createDiv({ cls: 'sxdb-lib-toggle' });
    statusWrap.createSpan({ text: 'Status:' });
    const statusBox = statusWrap.createDiv({ cls: 'sxdb-status-box' });
    const statuses = ['raw', 'reviewing', 'reviewed', 'scheduling', 'scheduled', 'published', 'archived'];
    this.statusCbs = {};

    const anyBtn = statusWrap.createEl('button', { text: 'Any' });
    anyBtn.addEventListener('click', () => {
      this.statusFilters.clear();
      for (const k of Object.keys(this.statusCbs)) this.statusCbs[k].checked = false;
      this.offset = 0;
      this.persistLibraryStateDebounced();
      void this.refresh();
    });

    for (const s of statuses) {
      const label = statusBox.createEl('label', { cls: 'sxdb-status-opt' });
      const cb = label.createEl('input', { type: 'checkbox' });
      cb.checked = this.statusFilters.has(s);
      label.createSpan({ text: s });
      this.statusCbs[s] = cb;
      cb.addEventListener('change', () => {
        if (cb.checked) this.statusFilters.add(s);
        else this.statusFilters.delete(s);
        this.offset = 0;
        this.persistLibraryStateDebounced();
        void this.refresh();
      });
    }

    const pager = contentEl.createDiv({ cls: 'sxdb-lib-pager' });
    const prevBtn = pager.createEl('button', { text: 'Prev' });
    const nextBtn = pager.createEl('button', { text: 'Next' });
    const pageInfo = pager.createDiv({ cls: 'sxdb-lib-pageinfo' });

    prevBtn.addEventListener('click', () => {
      const limit = this.pageLimit();
      this.offset = Math.max(0, this.offset - limit);
      void this.refresh();
    });
    nextBtn.addEventListener('click', () => {
      const limit = this.pageLimit();
      this.offset = Math.min(this.total, this.offset + limit);
      void this.refresh();
    });

    (this as any)._pageInfoEl = pageInfo;

    contentEl.createDiv({ cls: 'sxdb-lib-tablewrap' });

    // Populate select once render has created it (in case loadAuthors finished earlier)
    this.populateAuthorSelect();

    window.setTimeout(() => this.updateStickyOffsets(), 0);
  }

  private renderTable(items: ApiItem[], limit: number): void {
    const wrap = this.contentEl.querySelector('.sxdb-lib-tablewrap') as HTMLDivElement;
    wrap.empty();

    // Ensure hover preview sizing reflects latest settings (settings may change while view is open).
    const { w, h } = this.getHoverVideoSizePx();
    this.contentEl.style.setProperty('--sxdb-hovervideo-width', `${Math.floor(w)}px`);
    this.contentEl.style.setProperty('--sxdb-hovervideo-height', `${Math.floor(h)}px`);

    const pageInfo = (this as any)._pageInfoEl as HTMLDivElement | undefined;
    if (pageInfo) {
      const start = this.total ? this.offset + 1 : 0;
      const end = Math.min(this.total, this.offset + limit);
      pageInfo.setText(`${start}–${end} of ${this.total}`);
    }

    const table = wrap.createEl('table', { cls: 'sxdb-lib-table' });
    wrap.addEventListener('scroll', () => this.scheduleHideHoverVideo(0), { passive: true });

    const defs: Array<{ key: string; label: string }> = [
      { key: 'index', label: '#' },
      { key: 'thumb', label: 'Thumb' },
      { key: 'id', label: 'ID' },
      { key: 'author', label: 'Author' },
      { key: 'bookmarked', label: '★' },
      { key: 'caption', label: 'Caption' },
      { key: 'status', label: 'Status' },
      { key: 'rating', label: 'Rating' },
      { key: 'tags', label: 'Tags' },
      { key: 'notes', label: 'Notes' },
      { key: 'product_link', label: 'Product link' },
      { key: 'author_links', label: 'Author links' },
      { key: 'platform_targets', label: 'Platform targets' },
      { key: 'post_url', label: 'Post URL' },
      { key: 'published_time', label: 'Published time' },
      { key: 'workflow_log', label: 'Workflow log' },
      { key: 'actions', label: 'Actions' }
    ];

    const allKeys = defs.map((d) => d.key);
    const order = sanitizeColumnOrder(this.columnOrder, allKeys);

    this.columnOrder = [...order];

    const visibleDefs = order
      .map((k) => defs.find((d) => d.key === k))
      .filter(Boolean)
      .filter((d) => Boolean(this.columns[(d as any).key])) as Array<{ key: string; label: string }>;

    if (!visibleDefs.length) {
      // Repair: user settings hid all columns (or got corrupted).
      this.columns = Object.assign({}, this.DEFAULT_COLUMNS);
      this.persistLibraryColumnsDebounced();
      new Notice('SX Library: no visible columns — reset to defaults.');
      return this.renderTable(items, limit);
    }

    const thead = table.createEl('thead');
    const trh = thead.createEl('tr');

    // Sticky offsets depend on actual rendered heights; compute after DOM exists.
    window.setTimeout(() => this.updateStickyOffsets(), 0);

    const applyWidth = (key: string, px: number | null) => {
      const sel = `[data-col="${key}"]`;
      const els = table.querySelectorAll(sel) as any;
      els.forEach((el: HTMLElement) => {
        if (!px) {
          el.style.removeProperty('width');
          el.style.removeProperty('minWidth');
          el.style.removeProperty('maxWidth');
          return;
        }
        const w = `${px}px`;
        el.style.width = w;
        el.style.minWidth = w;
        el.style.maxWidth = w;
      });
    };

    const visibleKeys = visibleDefs.map((d) => d.key);

    const startResize = (evt: MouseEvent, key: string, th: HTMLTableCellElement) => {
      evt.preventDefault();
      evt.stopPropagation();
      const startX = evt.clientX;
      const startW = this.columnWidths[key] || Math.floor(th.getBoundingClientRect().width);

      const onMove = (e: MouseEvent) => {
        const next = Math.max(40, Math.floor(startW + (e.clientX - startX)));
        this.columnWidths[key] = next;
        applyWidth(key, next);

        // Keep frozen column offsets in sync while resizing.
        window.requestAnimationFrame(() => this.applyFreezePanes(table, visibleKeys));
      };

      const onUp = () => {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        this.persistLibraryLayoutDebounced();
      };

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    };

    for (const c of visibleDefs) {
      const th = trh.createEl('th', { text: c.label });
      th.setAttr('data-col', c.key);

      th.addEventListener('click', (evt) => {
        const t = evt.target as HTMLElement | null;
        if (t?.closest('.sxdb-col-resizer')) return;
        evt.preventDefault();
        evt.stopPropagation();

        if (c.key === 'index') {
          this.tableSelectedAll = applySelectAllToggle(
            this.selectedCells,
            this.selectedRows,
            this.selectedCols,
            this.tableSelectedAll
          );
          this.updateSelectionClasses(table);
          return;
        }

        this.tableSelectedAll = applyColumnSingleSelection(
          this.selectedCells,
          this.selectedRows,
          this.selectedCols,
          this.tableSelectedAll,
          c.key
        );
        this.updateSelectionClasses(table);
      });

      const width = this.columnWidths[c.key];
      if (width) applyWidth(c.key, width);
      const handle = th.createDiv({ cls: 'sxdb-col-resizer' });
      handle.addEventListener('mousedown', (evt) => startResize(evt as any, c.key, th));
    }

    const tbody = table.createEl('tbody');

    const parseLinkFromNoteFrontmatter = (md: string, kind: 'open' | 'reveal'): string => {
      const text = String(md ?? '');
      if (!text.startsWith('---')) return '';
      const idx = text.indexOf('\n---', 3);
      if (idx === -1) return '';
      const rawFm = text.slice(3, idx + 1);
      try {
        const fm = parseYaml(rawFm) as any;
        return kind === 'open' ? String(fm?.sxopen_video ?? '') : String(fm?.sxreveal_video ?? '');
      } catch {
        return '';
      }
    };

    const missingThumbIds = new Set<string>();
    const notifyMissingThumbs = () => {
      const count = missingThumbIds.size;
      if (!count) return;

      const sorted = Array.from(missingThumbIds).sort();
      const key = `${this.offset}:${this.total}:${sorted.join('|')}`;
      const now = Date.now();
      if (this.lastMissingMediaNoticeKey === key && now - this.lastMissingMediaNoticeTs < 20000) return;

      this.lastMissingMediaNoticeKey = key;
      this.lastMissingMediaNoticeTs = now;

      const sample = sorted.slice(0, 4).join(', ');
      const more = count > 4 ? ` (+${count - 4} more)` : '';
      new Notice(`Media not found for ${count} item(s) on this page: ${sample}${more}`);
    };

    const markThumbMissing = (id: string, td: HTMLTableCellElement, badge: HTMLDivElement, reason: string) => {
      td.addClass('sxdb-lib-thumb-missing-state');
      badge.style.display = 'inline-flex';
      badge.setAttr('title', reason);
      missingThumbIds.add(id);
      notifyMissingThumbs();
    };

    const clearThumbMissing = (id: string, td: HTMLTableCellElement, badge: HTMLDivElement) => {
      td.removeClass('sxdb-lib-thumb-missing-state');
      badge.style.display = 'none';
      missingThumbIds.delete(id);
    };

    for (const [rowIdx, it] of items.entries()) {
      const tr = tbody.createEl('tr');
      tr.setAttr('data-row-id', it.id);
      const h = this.rowHeights[it.id];
      if (h && Number.isFinite(h) && h > 28) tr.style.height = `${Math.floor(h)}px`;

      const meta = it.meta ?? {};
      const markInvalid = (el: HTMLInputElement | null, bad: boolean) => {
        if (!el) return;
        if (bad) el.addClass('sxdb-invalid');
        else el.removeClass('sxdb-invalid');
      };
      const normalizeLinksInput = (input: HTMLInputElement | null, pills: HTMLDivElement | null) => {
        if (!input) return;
        const next = this.parseLinksValue(input.value).join(', ');
        input.value = next;
        if (pills) this.renderLinkPills(pills, this.parseLinksValue(next));
      };

      // status is now edited via a multi-select popover; see status column renderer.
      let rating: HTMLInputElement | null = null;
      let tags: HTMLInputElement | null = null;
      let notes: HTMLInputElement | null = null;
      let productLink: HTMLInputElement | null = null;
      let authorLinks: HTMLInputElement | null = null;
      let platformTargets: HTMLInputElement | null = null;
      let postUrl: HTMLInputElement | null = null;
      let publishedTime: HTMLInputElement | null = null;
      let workflowLog: HTMLInputElement | null = null;

      let productLinkPills: HTMLDivElement | null = null;
      let authorLinksPills: HTMLDivElement | null = null;
      let postUrlPills: HTMLDivElement | null = null;

      let previewBtn: HTMLButtonElement | null = null;
      let openLocalBtn: HTMLButtonElement | null = null;
      let revealLocalBtn: HTMLButtonElement | null = null;
      let pinBtn: HTMLButtonElement | null = null;
      let unpinBtn: HTMLButtonElement | null = null;

      for (const c of visibleDefs) {
        if (c.key === 'index') {
          const td = tr.createEl('td', { cls: 'sxdb-lib-index' });
          td.setAttr('data-col', 'index');
          td.setText(String(this.offset + rowIdx + 1));

          td.addEventListener('click', (evt) => {
            evt.preventDefault();
            evt.stopPropagation();
            this.tableSelectedAll = applyRowSingleSelection(
              this.selectedCells,
              this.selectedRows,
              this.selectedCols,
              this.tableSelectedAll,
              it.id
            );
            this.updateSelectionClasses(table);
          });

          const rowRes = td.createDiv({ cls: 'sxdb-row-resizer' });
          rowRes.addEventListener('mousedown', (evt) => {
            evt.preventDefault();
            evt.stopPropagation();
            const startY = evt.clientY;
            const startH = Math.max(28, Math.floor(tr.getBoundingClientRect().height || 28));
            const onMove = (e: MouseEvent) => {
              const next = Math.max(28, Math.floor(startH + (e.clientY - startY)));
              this.rowHeights[it.id] = next;
              tr.style.height = `${next}px`;
            };
            const onUp = () => {
              document.removeEventListener('mousemove', onMove);
              document.removeEventListener('mouseup', onUp);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
          });
          continue;
        }

        if (c.key === 'thumb') {
          const td = tr.createEl('td', { cls: 'sxdb-lib-thumb' });
          td.setAttr('data-col', 'thumb');
          td.setAttr('data-row-id', it.id);
          const img = td.createEl('img');
          const missingBadge = td.createDiv({
            cls: 'sxdb-lib-thumb-missing',
            text: 'Media not found'
          });
          missingBadge.style.display = 'none';
          img.loading = 'lazy';
          if (it.cover_path) {
            img.src = this.apiUrl(`/media/cover/${encodeURIComponent(it.id)}`);
            img.addEventListener('load', () => {
              clearThumbMissing(it.id, td, missingBadge);
            });
            img.addEventListener('error', () => {
              img.style.display = 'none';
              markThumbMissing(
                it.id,
                td,
                missingBadge,
                'Record exists, but thumbnail media file was not found on disk.'
              );
            });
          } else {
            img.style.display = 'none';
            markThumbMissing(
              it.id,
              td,
              missingBadge,
              'Record exists, but no thumbnail path is stored for this item.'
            );
          }

          if (this.plugin.settings.libraryHoverVideoPreview) {
            td.addEventListener('mouseenter', () => void this.showHoverVideoForItem(it.id, td));
            td.addEventListener('mouseleave', () => this.scheduleHideHoverVideo(120));
          }
          continue;
        }

        if (c.key === 'id') {
          const td = tr.createEl('td', { cls: 'sxdb-lib-id' });
          td.setAttr('data-col', 'id');

          const wrap = td.createDiv({ cls: 'sxdb-lib-idcell' });
          const btn = wrap.createEl('button', { text: it.id, cls: 'sxdb-lib-idbtn' });
          let lastHoverPreviewAt = 0;

          // Maintain anchor tracking for the custom hover preview.
          btn.addEventListener('mouseenter', () => this.setHoverMarkdownAnchor(btn, true));
          btn.addEventListener('mouseleave', () => this.setHoverMarkdownAnchor(btn, false));
          btn.addEventListener('click', (evt) => {
            // Shift+click opens pinned peek for fast review.
            if ((evt as any)?.shiftKey) {
              void this.openNotePeekForId(it.id, evt);
              return;
            }
            void this.openVaultNoteForId(it.id).then((ok) => {
              if (!ok) new Notice(`No vault note found for ${it.id}. Pin or Sync to create it.`);
            });
          });

          // Ctrl/Cmd + hover: Obsidian classic hover preview (best-effort)
          const tryHover = (evt: MouseEvent) => {
            if (!this.plugin.settings.libraryIdCtrlHoverPreview) return;
            const want = Boolean((evt as any).ctrlKey) || Boolean((evt as any).metaKey);
            if (!want) return;
            const now = Date.now();
            if (now - lastHoverPreviewAt < 800) return;
            lastHoverPreviewAt = now;

            void this.findVaultNotesForId(it.id).then((files) => {
              const f = files[0];
              if (!f) return;
              this.triggerObsidianHoverPreview(evt, f, btn);
            });
          };
          btn.addEventListener('mouseenter', (evt) => tryHover(evt as MouseEvent));
          btn.addEventListener('mousemove', (evt) => tryHover(evt as MouseEvent));

          const copyBtn = wrap.createEl('button', { text: 'Copy', cls: 'sxdb-lib-idcopy' });
          copyBtn.addEventListener('click', async (evt) => {
            evt.preventDefault();
            evt.stopPropagation();
            const ok = await this.copyToClipboard(it.id);
            new Notice(ok ? 'Copied ID.' : 'Copy failed (clipboard permissions).');
          });

          if (this.plugin.settings.libraryNotePeekEnabled) {
            const peekBtn = wrap.createEl('button', { text: 'Peek', cls: 'sxdb-lib-idpeek' });
            peekBtn.addEventListener('click', (evt) => {
              evt.preventDefault();
              evt.stopPropagation();
              void this.openNotePeekForId(it.id, evt);
            });
          }
          continue;
        }

        if (c.key === 'author') {
          const td = tr.createEl('td', { text: it.author_unique_id ?? it.author_name ?? '' });
          td.setAttr('data-col', 'author');
          continue;
        }

        if (c.key === 'caption') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'caption');
          const full = String(it.caption ?? '').trim();
          // Render a compact snippet; full caption is accessible via hover.
          const snippet = full.length > 220 ? `${full.slice(0, 220).trim()}…` : full;
          const div = td.createDiv({ cls: 'sxdb-lib-caption' });
          div.setText(snippet || '');
          if (full) div.setAttr('title', full);
          continue;
        }

        if (c.key === 'bookmarked') {
          const td = tr.createEl('td', { text: it.bookmarked ? '★' : '' });
          td.setAttr('data-col', 'bookmarked');
          continue;
        }

        if (c.key === 'status') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'status');
          const statuses = Array.isArray((meta as any).statuses)
            ? ((meta as any).statuses as any[]).map((x) => String(x).trim()).filter(Boolean)
            : (meta.status ? [String(meta.status).trim()].filter(Boolean) : []);

          const pillWrap = td.createDiv({ cls: 'sxdb-statuscell' });
          const label = pillWrap.createDiv({ cls: 'sxdb-statuscell-label' });
          label.setText(statuses.length ? statuses.join(', ') : '—');

          const editBtn = pillWrap.createEl('button', { text: 'Edit', cls: 'sxdb-statuscell-edit' });
          editBtn.addEventListener('click', () => {
            const now = Array.isArray((meta as any).statuses)
              ? ((meta as any).statuses as any[]).map((x) => String(x).trim()).filter(Boolean)
              : (meta.status ? [String(meta.status).trim()].filter(Boolean) : []);

            this.openStatusEditor(editBtn, now, (next) => {
              const clean = (next || []).map((s) => String(s).trim()).filter(Boolean);
              (meta as any).statuses = clean;
              meta.status = this.choosePrimaryStatus(clean);
              label.setText(clean.length ? clean.join(', ') : '—');
              void saveMeta();
            });
          });
          continue;
        }

        if (c.key === 'rating') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'rating');
          rating = td.createEl('input', { type: 'number' });
          rating.min = '0';
          rating.max = '5';
          rating.step = '1';
          rating.value = meta.rating != null ? String(meta.rating) : '';
          rating.style.width = '64px';
          continue;
        }

        if (c.key === 'tags') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'tags');
          tags = td.createEl('input', { type: 'text' });
          tags.value = meta.tags ?? '';
          continue;
        }

        if (c.key === 'notes') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'notes');
          notes = td.createEl('input', { type: 'text' });
          notes.value = meta.notes ?? '';
          continue;
        }

        if (c.key === 'product_link') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'product_link');
          productLink = td.createEl('input', { type: 'text' });
          productLink.placeholder = 'https://…';
          productLink.value = meta.product_link ?? '';
          productLinkPills = td.createDiv({ cls: 'sxdb-meta-linkpills' });
          if ((this.plugin.settings as any).libraryShowLinkChipActionButton !== false) {
            const chipBtn = td.createEl('button', {
              text: this.plugin.settings.libraryLinkChipActionLabel || 'Chipify',
              cls: 'sxdb-link-chip-action'
            });
            chipBtn.addEventListener('click', (evt) => {
              evt.preventDefault();
              evt.stopPropagation();
              normalizeLinksInput(productLink, productLinkPills);
              void saveMeta();
            });
          }
          this.renderLinkPills(productLinkPills, this.parseLinksValue(productLink.value));
          productLink.addEventListener('input', () => {
            const links = this.parseLinksValue(productLink?.value ?? '');
            markInvalid(productLink, links.some((u) => !this.validateUrlLike(u)));
            if (productLinkPills) this.renderLinkPills(productLinkPills, links);
          });
          productLink.addEventListener('keydown', (evt) => {
            if (!this.shouldCommitLinkChipOnKey(evt)) return;
            evt.preventDefault();
            normalizeLinksInput(productLink, productLinkPills);
            void saveMeta();
          });
          continue;
        }

        if (c.key === 'author_links') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'author_links');
          authorLinks = td.createEl('input', { type: 'text' });
          authorLinks.placeholder = 'https://a.com, https://b.com';
          authorLinks.value = this.parseLinksValue((meta as any).author_links).join(', ');
          authorLinksPills = td.createDiv({ cls: 'sxdb-meta-linkpills' });
          if ((this.plugin.settings as any).libraryShowLinkChipActionButton !== false) {
            const chipBtn = td.createEl('button', {
              text: this.plugin.settings.libraryLinkChipActionLabel || 'Chipify',
              cls: 'sxdb-link-chip-action'
            });
            chipBtn.addEventListener('click', (evt) => {
              evt.preventDefault();
              evt.stopPropagation();
              normalizeLinksInput(authorLinks, authorLinksPills);
              void saveMeta();
            });
          }
          this.renderLinkPills(authorLinksPills, this.parseLinksValue(authorLinks.value));
          authorLinks.addEventListener('input', () => {
            const links = this.parseLinksValue(authorLinks?.value ?? '');
            markInvalid(authorLinks, links.some((u) => !this.validateUrlLike(u)));
            if (authorLinksPills) this.renderLinkPills(authorLinksPills, links);
          });
          authorLinks.addEventListener('keydown', (evt) => {
            if (!this.shouldCommitLinkChipOnKey(evt)) return;
            evt.preventDefault();
            normalizeLinksInput(authorLinks, authorLinksPills);
            void saveMeta();
          });
          continue;
        }

        if (c.key === 'platform_targets') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'platform_targets');
          platformTargets = td.createEl('input', { type: 'text' });
          platformTargets.placeholder = 'e.g. tiktok,ig,youtube';
          platformTargets.value = meta.platform_targets ?? '';
          continue;
        }

        if (c.key === 'post_url') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'post_url');
          postUrl = td.createEl('input', { type: 'text' });
          postUrl.placeholder = 'https://…';
          postUrl.value = meta.post_url ?? '';
          postUrlPills = td.createDiv({ cls: 'sxdb-meta-linkpills' });
          if ((this.plugin.settings as any).libraryShowLinkChipActionButton !== false) {
            const chipBtn = td.createEl('button', {
              text: this.plugin.settings.libraryLinkChipActionLabel || 'Chipify',
              cls: 'sxdb-link-chip-action'
            });
            chipBtn.addEventListener('click', (evt) => {
              evt.preventDefault();
              evt.stopPropagation();
              normalizeLinksInput(postUrl, postUrlPills);
              void saveMeta();
            });
          }
          this.renderLinkPills(postUrlPills, this.parseLinksValue(postUrl.value));
          postUrl.addEventListener('input', () => {
            const links = this.parseLinksValue(postUrl?.value ?? '');
            markInvalid(postUrl, links.some((u) => !this.validateUrlLike(u)));
            if (postUrlPills) this.renderLinkPills(postUrlPills, links);
          });
          postUrl.addEventListener('keydown', (evt) => {
            if (!this.shouldCommitLinkChipOnKey(evt)) return;
            evt.preventDefault();
            normalizeLinksInput(postUrl, postUrlPills);
            void saveMeta();
          });
          continue;
        }

        if (c.key === 'published_time') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'published_time');
          publishedTime = td.createEl('input', { type: 'text' });
          publishedTime.placeholder = 'YYYY-MM-DD…';
          publishedTime.value = meta.published_time ?? '';
          continue;
        }

        if (c.key === 'workflow_log') {
          const td = tr.createEl('td');
          td.setAttr('data-col', 'workflow_log');
          workflowLog = td.createEl('input', { type: 'text' });
          workflowLog.placeholder = '[...]';
          workflowLog.value = meta.workflow_log ?? '';
          continue;
        }

        if (c.key === 'actions') {
          const td = tr.createEl('td', { cls: 'sxdb-lib-actions-cell' });
          td.setAttr('data-col', 'actions');
          previewBtn = td.createEl('button', { text: 'Preview' });
          openLocalBtn = td.createEl('button', { text: 'Open' });
          revealLocalBtn = td.createEl('button', { text: 'Reveal' });
          pinBtn = td.createEl('button', { text: 'Pin' });
          unpinBtn = td.createEl('button', { text: 'Unpin' });
          continue;
        }
      }

      tr.querySelectorAll('td').forEach((cell) => {
        const td = cell as HTMLTableCellElement;
        const col = String(td.getAttr('data-col') || '').trim();
        if (!col || col === 'index') return;

        td.addEventListener('click', (evt) => {
          const target = evt.target as HTMLElement | null;
          if (target?.closest('input,button,a,textarea,select,video,.sxdb-row-resizer')) return;
          evt.preventDefault();
          evt.stopPropagation();
          this.tableSelectedAll = applyCellSingleSelection(
            this.selectedCells,
            this.selectedRows,
            this.selectedCols,
            this.tableSelectedAll,
            it.id,
            col
          );
          this.updateSelectionClasses(table);
        });
      });

      const pinnedTargetPath = this.activePinnedPathForId(it.id);
      const updatePinnedUi = () => {
        const af = this.app.vault.getAbstractFileByPath(pinnedTargetPath);
        const pinned = Boolean(af && af instanceof TFile);
        if (pinBtn) {
          if (pinned) pinBtn.addClass('sxdb-pin-active');
          else pinBtn.removeClass('sxdb-pin-active');
          pinBtn.setText(pinned ? 'Pinned' : 'Pin');
          pinBtn.setAttr('aria-pressed', pinned ? 'true' : 'false');
        }
        if (unpinBtn) {
          unpinBtn.disabled = !pinned;
        }
      };
      updatePinnedUi();

      const saveMeta = async () => {
        const ratingNum = rating?.value ? Number(rating.value) : null;
        const ratingInvalid = ratingNum != null && (!Number.isFinite(ratingNum) || ratingNum < 0 || ratingNum > 5 || Math.floor(ratingNum) !== ratingNum);
        markInvalid(rating, ratingInvalid);

        const productLinks = this.parseLinksValue(productLink?.value ?? '');
        const authorLinksValue = this.parseLinksValue(authorLinks?.value ?? '');
        const postLinks = this.parseLinksValue(postUrl?.value ?? '');
        const badProduct = productLinks.some((u) => !this.validateUrlLike(u));
        const badAuthor = authorLinksValue.some((u) => !this.validateUrlLike(u));
        const badPost = postLinks.some((u) => !this.validateUrlLike(u));
        markInvalid(productLink, badProduct);
        markInvalid(authorLinks, badAuthor);
        markInvalid(postUrl, badPost);
        if (ratingInvalid || badProduct || badAuthor || badPost) {
          new Notice('Please fix invalid fields (rating must be 0-5; links must be valid URLs).');
          return;
        }

        const payload: any = {
          status: meta.status ?? null,
          statuses: Array.isArray((meta as any).statuses) ? (meta as any).statuses : (meta.status ? [meta.status] : null),
          rating: meta.rating ?? null,
          tags: meta.tags ?? null,
          notes: meta.notes ?? null,
          product_link: meta.product_link ?? null,
          author_links: this.parseLinksValue((meta as any).author_links),
          platform_targets: meta.platform_targets ?? null,
          workflow_log: meta.workflow_log ?? null,
          post_url: meta.post_url ?? null,
          published_time: meta.published_time ?? null
        };

        // statusSel removed (multi-choice status editor writes into meta.status/meta.statuses)
        if (rating) payload.rating = ratingNum;
        if (tags) payload.tags = tags.value.trim() || null;
        if (notes) payload.notes = notes.value.trim() || null;
        if (productLink) payload.product_link = productLinks[0] ?? (productLink.value.trim() || null);
        if (authorLinks) payload.author_links = authorLinksValue;
        if (platformTargets) payload.platform_targets = platformTargets.value.trim() || null;
        if (workflowLog) payload.workflow_log = workflowLog.value.trim() || null;
        if (postUrl) payload.post_url = postLinks[0] ?? (postUrl.value.trim() || null);
        if (publishedTime) payload.published_time = publishedTime.value.trim() || null;

        try {
          await this.apiRequest({
            path: `/items/${encodeURIComponent(it.id)}/meta`,
            method: 'PUT',
            body: JSON.stringify(payload),
            headers: { 'Content-Type': 'application/json' }
          });

          // Keep the vault note frontmatter in sync (best-effort, updates any matching _db notes).
          const fmPatch = Object.assign({}, payload);
          // Write YAML `status` as an array (multi-choice)
          const ss = Array.isArray(payload.statuses) ? payload.statuses : (payload.status ? [payload.status] : []);
          fmPatch.status = ss.length ? ss : null;
          delete fmPatch.statuses;
          await this.updateVaultFrontmatterForId(it.id, fmPatch);

          // Author links are author-scoped: mirror across all local notes with the same author.
          if (Object.prototype.hasOwnProperty.call(payload, 'author_links')) {
            await this.updateVaultFrontmatterForAuthor(it.author_unique_id, it.author_name, {
              author_links: payload.author_links
            });
          }
        } catch (e: any) {
          new Notice(`Failed saving meta for ${it.id}: ${String(e?.message ?? e)}`);
        }
      };

      // status changes are persisted immediately by the status editor
      rating?.addEventListener('change', () => void saveMeta());
      tags?.addEventListener('change', () => void saveMeta());
      notes?.addEventListener('change', () => void saveMeta());
      productLink?.addEventListener('change', () => void saveMeta());
      authorLinks?.addEventListener('change', () => void saveMeta());
      platformTargets?.addEventListener('change', () => void saveMeta());
      workflowLog?.addEventListener('change', () => void saveMeta());
      postUrl?.addEventListener('change', () => void saveMeta());
      publishedTime?.addEventListener('change', () => void saveMeta());

      previewBtn?.addEventListener('click', () => {
        const url = this.apiUrl(`/media/video/${encodeURIComponent(it.id)}`);
        window.open(url);
      });

      const openOrReveal = async (kind: 'open' | 'reveal') => {
        try {
          // Prefer dedicated endpoint that computes links from canonical paths.
          const linksResp = await this.apiRequest({ path: `/items/${encodeURIComponent(it.id)}/links` });
          const links = linksResp.json as any;
          const link = kind === 'open' ? String(links?.sxopen_video ?? '') : String(links?.sxreveal_video ?? '');
          if (link) {
            this.openProtocolOrUrl(link);
            return;
          }
        } catch {
          // Fall back to note frontmatter parsing below.
        }

        try {
          const resp = await this.apiRequest({ path: `/items/${encodeURIComponent(it.id)}/note` });
          const md = (resp.json as any)?.markdown as string;
          if (!md) throw new Error('API returned no markdown');
          const link = parseLinkFromNoteFrontmatter(md, kind);
          if (!link) {
            new Notice('No sxopen/sxreveal link found (and /links endpoint returned empty).');
            return;
          }
          this.openProtocolOrUrl(link);
        } catch (e: any) {
          new Notice(`Failed to ${kind} ${it.id}: ${String(e?.message ?? e)}`);
        }
      };

      openLocalBtn?.addEventListener('click', () => void openOrReveal('open'));
      revealLocalBtn?.addEventListener('click', () => void openOrReveal('reveal'));

      pinBtn?.addEventListener('click', async () => {
        try {
          const resp = await this.apiRequest({ path: `/items/${encodeURIComponent(it.id)}/note` });
          const md = (resp.json as any)?.markdown as string;
          if (!md) throw new Error('API returned no markdown');

          const activeDir = normalizePath(this.plugin.settings.activeNotesDir);
          const targetPath = normalizePath(`${activeDir}/${it.id}.md`);
          await this.app.vault.createFolder(activeDir).catch(() => void 0);

          const existing = this.app.vault.getAbstractFileByPath(targetPath);
          if (existing && existing instanceof TFile) {
            const prev = await this.app.vault.read(existing);
            const merged = mergeMarkdownPreservingUserEdits(prev, md);
            await this.app.vault.modify(existing, merged);
          } else {
            await this.app.vault.create(targetPath, md);
          }
          this.plugin.markRecentlyWritten(targetPath);

          if (this.plugin.settings.openAfterPin) {
            const file = this.app.vault.getAbstractFileByPath(targetPath);
            if (file && file instanceof TFile) {
              await openPinnedFile(this.plugin, file);
            }
          }

          new Notice(`Pinned ${it.id} → ${targetPath}`);

          // Ensure frontmatter respects our normalization rules (esp. tags) after writing.
          await this.updateVaultFrontmatterForId(it.id, { tags: meta.tags ?? null });
          updatePinnedUi();
        } catch (e: any) {
          new Notice(`Failed to pin ${it.id}: ${String(e?.message ?? e)}`);
        }
      });

      unpinBtn?.addEventListener('click', async () => {
        const activeDir = normalizePath(this.plugin.settings.activeNotesDir);
        const targetPath = normalizePath(`${activeDir}/${it.id}.md`);
        const existing = this.app.vault.getAbstractFileByPath(targetPath);
        if (!existing || !(existing instanceof TFile)) {
          new Notice(`Not pinned: ${targetPath}`);
          return;
        }
        try {
          await this.app.vault.delete(existing);
          new Notice(`Unpinned ${it.id} (deleted ${targetPath})`);
          updatePinnedUi();
        } catch (e: any) {
          new Notice(`Failed to unpin ${it.id}: ${String(e?.message ?? e)}`);
        }
      });
    }

    // Apply any remembered widths to all cells after the body has been created.
    for (const [k, v] of Object.entries(this.columnWidths || {})) {
      const n = Number(v);
      if (Number.isFinite(n) && n > 0) applyWidth(k, Math.floor(n));
    }

    // Apply freeze panes (sticky columns/rows) after the table is populated.
    window.requestAnimationFrame(() => this.applyFreezePanes(table, visibleKeys));
    this.updateSelectionClasses(table);

    if (missingThumbIds.size > 0) notifyMissingThumbs();
  }
}
