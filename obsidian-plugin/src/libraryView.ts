import {
  ItemView,
  MarkdownRenderer,
  Notice,
  requestUrl,
  WorkspaceLeaf,
  WorkspaceWindowInitData,
  normalizePath,
  parseYaml,
  TAbstractFile,
  TFile,
  TFolder
} from 'obsidian';
import type SxDbPlugin from './main';
import { mergeMarkdownPreservingUserEdits } from './markdownMerge';
import { openPinnedFile } from './leafUtils';

type ApiItem = {
  id: string;
  author_id?: string;
  author_unique_id?: string;
  author_name?: string;
  caption?: string;
  bookmarked?: number;
  cover_path?: string;
  video_path?: string;
  updated_at?: string;
  meta?: {
    rating?: number | null;
    status?: string | null;
    statuses?: string[] | null;
    tags?: string | null;
    notes?: string | null;
    product_link?: string | null;
    platform_targets?: string | null;
    workflow_log?: string | null;
    post_url?: string | null;
    published_time?: string | null;
    updated_at?: string | null;
  };
};

type ApiAuthor = {
  author_id?: string | null;
  author_unique_id: string;
  author_name?: string | null;
  items_count: number;
  bookmarked_count: number;
};

type ApiNote = {
  id: string;
  bookmarked: boolean;
  author_unique_id?: string | null;
  author_name?: string | null;
  markdown: string;
};

export const SXDB_LIBRARY_VIEW = 'sxdb-library-view';

export class LibraryView extends ItemView {
  plugin: SxDbPlugin;

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

  private notePeekEl: HTMLDivElement | null = null;
  private notePeekHeaderEl: HTMLDivElement | null = null;
  private notePeekBodyEl: HTMLDivElement | null = null;
  private notePeekState: { x: number; y: number; w: number; h: number; id: string; filePath: string } | null = null;
  private notePeekMode: 'preview' | 'source' = 'preview';

  // Experimental: Obsidian leaf embedded inside the inline Note Peek window.
  private notePeekLeaf: WorkspaceLeaf | null = null;
  private notePeekLeafContainer: HTMLElement | null = null;
  private notePeekLeafOrigParent: HTMLElement | null = null;
  private notePeekLeafOrigNextSibling: ChildNode | null = null;

  private notePeekEngine(): 'inline' | 'inline-leaf' | 'hover-editor' | 'popout' {
    const v = String((this.plugin.settings as any).libraryNotePeekEngine || 'inline');
    if (v === 'inline-leaf' || v === 'hover-editor' || v === 'popout') return v;
    return 'inline';
  }

  private cleanupInlineLeaf(): void {
    // Best-effort restoration/detach so we don't leave orphaned DOM or empty tabs.
    const leaf: any = this.notePeekLeaf as any;
    const container = this.notePeekLeafContainer;

    try {
      if (container && this.notePeekLeafOrigParent) {
        // Put it back where it came from.
        const parent = this.notePeekLeafOrigParent;
        const next = this.notePeekLeafOrigNextSibling;
        if (next && next.parentNode === parent) parent.insertBefore(container, next);
        else parent.appendChild(container);
      }
    } catch {
      // ignore
    }

    try {
      leaf?.detach?.();
    } catch {
      // ignore
    }

    try {
      this.notePeekEl?.removeClass('sxdb-notepeek-hasleaf');
    } catch {
      // ignore
    }

    this.notePeekLeaf = null;
    this.notePeekLeafContainer = null;
    this.notePeekLeafOrigParent = null;
    this.notePeekLeafOrigNextSibling = null;
  }

  private async ensureInlineLeafHost(): Promise<WorkspaceLeaf | null> {
    if (!this.notePeekBodyEl) return null;

    // Reuse if still valid.
    if (this.notePeekLeaf && this.isLeafValid(this.notePeekLeaf) && this.notePeekLeafContainer?.isConnected) {
      return this.notePeekLeaf;
    }

    // Clean any stale refs.
    this.cleanupInlineLeaf();

    // Create a fresh leaf. NOTE: Obsidian does not provide a supported public API
    // to mount a leaf inside an arbitrary div. This is experimental and best-effort.
    const leaf = this.app.workspace.getLeaf(true);
    // Prefer the leaf container (includes wrappers). Fall back to view.containerEl.
    const containerEl: HTMLElement | null | undefined = (leaf as any)?.containerEl ?? (leaf as any)?.view?.containerEl;
    if (!containerEl) {
      try {
        (leaf as any)?.detach?.();
      } catch {
        // ignore
      }
      return null;
    }

    // Remember original DOM position so we can restore.
    this.notePeekLeafOrigParent = containerEl.parentElement;
    this.notePeekLeafOrigNextSibling = containerEl.nextSibling as any;

    // Move into Note Peek body.
    try {
      this.notePeekBodyEl.empty();
      this.notePeekBodyEl.appendChild(containerEl);
      this.notePeekEl?.addClass('sxdb-notepeek-hasleaf');

      // Best-effort: ensure the embedded view fills the window.
      containerEl.style.width = '100%';
      containerEl.style.height = '100%';
      window.setTimeout(() => {
        try {
          (leaf as any)?.view?.onResize?.();
        } catch {
          // ignore
        }
      }, 0);
    } catch {
      // If we can't mount it, detach the leaf and fall back.
      try {
        (leaf as any)?.detach?.();
      } catch {
        // ignore
      }
      this.notePeekEl?.removeClass('sxdb-notepeek-hasleaf');
      return null;
    }

    this.notePeekLeaf = leaf;
    this.notePeekLeafContainer = containerEl;
    return leaf;
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
  private hoverMdEl: HTMLDivElement | null = null;
  private hoverMdTitleEl: HTMLDivElement | null = null;
  private hoverMdBodyEl: HTMLDivElement | null = null;
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
  private hoverMdHideT: number | null = null;
  private hoverMdOnDocMouseDown?: (evt: MouseEvent) => void;
  private hoverMdOnKeyDown?: (evt: KeyboardEvent) => void;
  private hoverMdOnKeyUp?: (evt: KeyboardEvent) => void;
  private hoverMdOnScroll?: () => void;

  private readonly DEFAULT_COLUMNS: Record<string, boolean> = {
    thumb: true,
    id: true,
    author: true,
    bookmarked: true,
    caption: false,
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
  };

  private columnOrder: string[] = [];
  private columnWidths: Record<string, number> = {};

  private openExternalUrl(url: string): boolean {
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

  private hoverEditorCommandId(): string {
    return 'obsidian-hover-editor:open-current-file-in-new-popover';
  }

  private hasHoverEditorInstalled(): boolean {
    try {
      const cmds = (this.app as any).commands?.commands as Record<string, any> | undefined;
      return Boolean(cmds && cmds[this.hoverEditorCommandId()]);
    } catch {
      return false;
    }
  }

  private async openFileInHoverEditor(file: TFile): Promise<void> {
    const cmdId = this.hoverEditorCommandId();
    const commands: any = (this.app as any).commands;
    if (!commands?.executeCommandById) {
      new Notice('Cannot open in Hover Editor: command API unavailable.');
      return;
    }
    if (!this.hasHoverEditorInstalled()) {
      new Notice('Hover Editor plugin is not installed/enabled.');
      return;
    }

    // Hover Editor's command opens the *current* file in a new popover.
    // We'll temporarily open the file in a leaf, run the command, then restore.
    const ws: any = this.app.workspace as any;
    const prevLeaf = ws.activeLeaf as any;
    const prevFile = this.app.workspace.getActiveFile();

    const tempLeaf = this.app.workspace.getLeaf(true);
    try {
      await tempLeaf.openFile(file);
      try {
        ws.setActiveLeaf?.(tempLeaf, false, true);
      } catch {
        // ignore
      }
      await commands.executeCommandById(cmdId);
    } finally {
      // Close the temporary leaf if possible to avoid clutter.
      try {
        (tempLeaf as any)?.detach?.();
      } catch {
        // ignore
      }
      // Restore previous focus/file.
      try {
        if (prevLeaf) ws.setActiveLeaf?.(prevLeaf, false, true);
      } catch {
        // ignore
      }
      if (prevFile) {
        // Best-effort: if focus restoration didn't restore the file, re-open it.
        try {
          const activeNow = this.app.workspace.getActiveFile();
          if (activeNow?.path !== prevFile.path && prevLeaf?.openFile) await prevLeaf.openFile(prevFile);
        } catch {
          // ignore
        }
      }
    }
  }

  private openProtocolOrUrl(link: string): void {
    const raw = String(link || '').trim();
    if (!raw) return;

    // Custom protocol handlers must be opened as *external URLs*, not file paths.
    if (/^(sxopen|sxreveal):/i.test(raw)) {
      try {
        if (!this.openExternalUrl(raw)) window.open(raw);
      } catch {
        window.open(raw);
      }
      return;
    }

    // Normal URLs.
    if (/^https?:\/\//i.test(raw)) {
      try {
        if (!this.openExternalUrl(raw)) window.open(raw);
      } catch {
        window.open(raw);
      }
      return;
    }

    // File path fallback.
    try {
      (this.app as any).openWithDefaultApp?.(raw);
    } catch {
      window.open(raw);
    }
  }

  private async ensureFolder(folderPath: string): Promise<TFolder> {
    const existing = this.app.vault.getAbstractFileByPath(folderPath);
    if (existing && existing instanceof TFolder) return existing;
    await this.app.vault.createFolder(folderPath).catch(() => void 0);
    const created = this.app.vault.getAbstractFileByPath(folderPath);
    if (!created || !(created instanceof TFolder)) throw new Error(`Failed to create folder: ${folderPath}`);
    return created;
  }

  private async clearFolderMarkdown(folderPath: string): Promise<number> {
    const root = this.app.vault.getAbstractFileByPath(folderPath);
    if (!root) return 0;
    const stack: TAbstractFile[] = [root];
    const toDelete: TFile[] = [];
    while (stack.length) {
      const cur = stack.pop();
      if (!cur) continue;
      if (cur instanceof TFile) {
        if (cur.extension === 'md') toDelete.push(cur);
      } else if (cur instanceof TFolder) {
        stack.push(...cur.children);
      }
    }

    let deleted = 0;
    for (const f of toDelete) {
      await this.app.vault.delete(f);
      deleted += 1;
    }
    return deleted;
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

  private authors: ApiAuthor[] = [];
  private authorSel: HTMLSelectElement | null = null;
  private statusCbs: Record<string, HTMLInputElement> = {};

  private lastItems: ApiItem[] = [];
  private lastLimit: number = 50;

  private _statusEditorEl: HTMLDivElement | null = null;

  private workflowStatuses(): string[] {
    return ['raw', 'reviewing', 'reviewed', 'scheduling', 'scheduled', 'published', 'archived'];
  }

  private choosePrimaryStatus(statuses: string[]): string | null {
    const clean = (statuses || []).map((s) => String(s).trim()).filter(Boolean);
    if (!clean.length) return null;
    const order = this.workflowStatuses();
    const ranked = order.filter((s) => clean.includes(s));
    return ranked.length ? ranked[ranked.length - 1] : clean[0];
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
  };

  private normalizeColumnsState(): void {
    const keys = Object.keys(this.columns);
    const anyVisible = keys.some((k) => Boolean(this.columns[k]));
    if (!anyVisible) {
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
    if (Array.isArray(ord)) this.columnOrder = ord.filter((x) => typeof x === 'string');
    const w = (this.plugin.settings as any).libraryColumnWidths as any;
    if (w && typeof w === 'object') {
      const next: Record<string, number> = {};
      for (const [k, v] of Object.entries(w)) {
        const n = Number(v);
        if (Number.isFinite(n) && n > 0) next[String(k)] = Math.floor(n);
      }
      this.columnWidths = next;
    }
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
  }

  private baseUrl(): string {
    return this.plugin.settings.apiBaseUrl.replace(/\/$/, '');
  }

  private updateStickyOffsets(): void {
    // Compute exact stacked sticky offsets so headers don't overlap when fonts/themes change.
    const root = this.contentEl as any as HTMLElement;
    if (!root?.isConnected) return;

    const menubar = root.querySelector('.sxdb-lib-menubar') as HTMLElement | null;
    const toolbar = root.querySelector('.sxdb-lib-toolbarrow') as HTMLElement | null;
    const pager = root.querySelector('.sxdb-lib-pager') as HTMLElement | null;

    const outerHeight = (el: HTMLElement | null): number => {
      if (!el) return 0;
      const rect = el.getBoundingClientRect();
      if (!rect.height) return 0;
      try {
        const cs = window.getComputedStyle(el);
        const mb = parseFloat(cs.marginBottom || '0') || 0;
        return rect.height + mb;
      } catch {
        return rect.height;
      }
    };

    const hMenubar = outerHeight(menubar);
    const hToolbar = outerHeight(toolbar);
    const hPager = outerHeight(pager);

    const topMenubar = 0;
    const topToolbar = hMenubar;
    const topPager = hMenubar + hToolbar;
    const topThead = hMenubar + hToolbar + hPager;

    root.style.setProperty('--sxdb-lib-stick-menubar-top', `${Math.max(0, Math.floor(topMenubar))}px`);
    root.style.setProperty('--sxdb-lib-stick-toolbar-top', `${Math.max(0, Math.floor(topToolbar))}px`);
    root.style.setProperty('--sxdb-lib-stick-pager-top', `${Math.max(0, Math.floor(topPager))}px`);
    root.style.setProperty('--sxdb-lib-stick-thead-top', `${Math.max(0, Math.floor(topThead))}px`);
  }

  private applyFreezePanes(table: HTMLTableElement, visibleKeys: string[]): void {
    if (!table?.isConnected) return;

    // Clear previous freeze styling/attrs.
    const prev = table.querySelectorAll('[data-sxdb-freeze-col], [data-sxdb-freeze-row]') as any;
    prev.forEach((el: HTMLElement) => {
      try {
        el.removeAttribute('data-sxdb-freeze-col');
        el.removeAttribute('data-sxdb-freeze-row');
        el.classList.remove('sxdb-freeze-col');
        el.classList.remove('sxdb-freeze-row');
        el.style.removeProperty('left');
        el.style.removeProperty('top');
      } catch {
        // ignore
      }
    });

    const resolveCols = (): string[] => {
      const keys = visibleKeys || [];
      if (!keys.length) return [];

      const has = (k: string) => keys.includes(k);
      if (this.freezeCols === 0) return [];

      if (this.freezeCols === 1) {
        if (has('id')) return ['id'];
        return [keys[0]];
      }

      // freezeCols === 2
      if (has('thumb') && has('id')) return ['thumb', 'id'];
      return keys.slice(0, 2);
    };

    const frozenCols = resolveCols();
    let left = 0;
    for (let i = 0; i < frozenCols.length; i++) {
      const key = frozenCols[i];
      const header = table.querySelector(`thead th[data-col="${key}"]`) as HTMLElement | null;
      const w = Math.max(
        0,
        header ? Math.ceil(header.getBoundingClientRect().width) : Math.ceil(Number(this.columnWidths[key] || 0))
      );

      const cells = table.querySelectorAll(`[data-col="${key}"]`) as any;
      cells.forEach((el: HTMLElement) => {
        try {
          el.setAttribute('data-sxdb-freeze-col', String(i + 1));
          el.classList.add('sxdb-freeze-col');
          el.style.left = `${left}px`;
        } catch {
          // ignore
        }
      });

      left += w;
    }

    if (this.freezeFirstRow) {
      const thead = table.querySelector('thead') as HTMLElement | null;
      const top = thead ? Math.ceil(thead.getBoundingClientRect().height) : 0;
      const firstRow = table.querySelector('tbody tr') as HTMLTableRowElement | null;
      if (firstRow) {
        const cells = firstRow.querySelectorAll('td') as any;
        cells.forEach((el: HTMLElement) => {
          try {
            el.setAttribute('data-sxdb-freeze-row', '1');
            el.classList.add('sxdb-freeze-row');
            el.style.top = `${top}px`;
          } catch {
            // ignore
          }
        });
      }
    }
  }

  private async copyToClipboard(text: string): Promise<boolean> {
    try {
      await navigator.clipboard.writeText(String(text ?? ''));
      return true;
    } catch {
      return false;
    }
  }

  private async findVaultNotesForId(id: string): Promise<TFile[]> {
    const safeId = String(id || '').trim();
    if (!safeId) return [];

    const roots = [
      normalizePath(this.plugin.settings.activeNotesDir),
      normalizePath(this.plugin.settings.bookmarksNotesDir),
      normalizePath(this.plugin.settings.authorsNotesDir)
    ].filter(Boolean);

    const out: TFile[] = [];
    const seen = new Set<string>();

    // Fast-path known locations.
    const directCandidates: string[] = [
      normalizePath(`${this.plugin.settings.activeNotesDir}/${safeId}.md`),
      normalizePath(`${this.plugin.settings.bookmarksNotesDir}/${safeId}.md`)
    ];
    for (const p of directCandidates) {
      const af = this.app.vault.getAbstractFileByPath(p);
      if (af && af instanceof TFile) {
        if (!seen.has(af.path)) {
          seen.add(af.path);
          out.push(af);
        }
      }
    }

    // Authors (or any other _db location): scan vault files, but scope to configured roots.
    const files = this.app.vault.getFiles();
    for (const f of files) {
      if (f.extension !== 'md') continue;
      if (f.basename !== safeId) continue;
      const p = normalizePath(f.path);
      if (!roots.some((r) => r && (p === r || p.startsWith(r + '/')))) continue;
      if (seen.has(f.path)) continue;
      seen.add(f.path);
      out.push(f);
    }

    return out;
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

  private clearHoverMarkdownHideTimer(): void {
    if (this.hoverMdHideT != null) {
      window.clearTimeout(this.hoverMdHideT);
      this.hoverMdHideT = null;
    }
  }

  private scheduleHoverMarkdownHide(delayMs: number = 220): void {
    this.clearHoverMarkdownHideTimer();
    this.hoverMdHideT = window.setTimeout(() => {
      this.hoverMdHideT = null;
      if (!this.hoverMdState) return;
      if (this.hoverMdState.onAnchor || this.hoverMdState.onPopover) return;
      this.closeHoverMarkdownPreview();
    }, Math.max(0, delayMs));
  }

  private closeHoverMarkdownPreview(): void {
    this.clearHoverMarkdownHideTimer();

    if (this.hoverMdOnDocMouseDown) document.removeEventListener('mousedown', this.hoverMdOnDocMouseDown, true);
    if (this.hoverMdOnKeyDown) document.removeEventListener('keydown', this.hoverMdOnKeyDown, true);
    if (this.hoverMdOnKeyUp) document.removeEventListener('keyup', this.hoverMdOnKeyUp, true);
    if (this.hoverMdOnScroll) window.removeEventListener('scroll', this.hoverMdOnScroll, true);
    this.hoverMdOnDocMouseDown = undefined;
    this.hoverMdOnKeyDown = undefined;
    this.hoverMdOnKeyUp = undefined;
    this.hoverMdOnScroll = undefined;

    if (this.hoverMdEl) {
      try {
        this.hoverMdEl.remove();
      } catch {
        // ignore
      }
    }

    this.hoverMdEl = null;
    this.hoverMdTitleEl = null;
    this.hoverMdBodyEl = null;
    this.hoverMdState = null;
  }

  private ensureHoverMarkdownPreview(): void {
    if (this.hoverMdEl && this.hoverMdBodyEl && this.hoverMdTitleEl && this.hoverMdState) {
      const el = this.hoverMdEl as any as HTMLElement;
      if (el?.isConnected) return;
    }
    this.closeHoverMarkdownPreview();

    const el = document.createElement('div') as HTMLDivElement;
    el.className = 'sxdb-hovermd';
    document.body.appendChild(el);
    this.hoverMdEl = el;

    const header = el.createDiv({ cls: 'sxdb-hovermd-header' });
    const title = header.createDiv({ cls: 'sxdb-hovermd-title', text: 'Preview' });
    const btns = header.createDiv({ cls: 'sxdb-hovermd-btns' });
    const pinBtn = btns.createEl('button', { text: 'Pin' });
    const openBtn = btns.createEl('button', { text: 'Open' });
    const closeBtn = btns.createEl('button', { text: '×' });
    const body = el.createDiv({ cls: 'sxdb-hovermd-body' });
    body.createEl('em', { text: 'Loading…' });

    this.hoverMdTitleEl = title;
    this.hoverMdBodyEl = body;
    this.hoverMdState = { id: '', filePath: '', anchorEl: null, onAnchor: false, onPopover: false, token: 0 };

    // Size (reuse the hover-preview settings so users have one place to tweak)
    const w = Math.max(220, Number(this.plugin.settings.libraryHoverPreviewWidth ?? 420));
    const h = Math.max(160, Number(this.plugin.settings.libraryHoverPreviewHeight ?? 320));
    el.style.width = `${Math.floor(w)}px`;
    el.style.height = `${Math.floor(h)}px`;

    el.addEventListener('mouseenter', () => {
      if (!this.hoverMdState) return;
      this.hoverMdState.onPopover = true;
      this.clearHoverMarkdownHideTimer();
    });
    el.addEventListener('mouseleave', () => {
      if (!this.hoverMdState) return;
      this.hoverMdState.onPopover = false;
      this.scheduleHoverMarkdownHide();
    });

    closeBtn.addEventListener('click', (evt) => {
      evt.preventDefault();
      evt.stopPropagation();
      this.closeHoverMarkdownPreview();
    });

    openBtn.addEventListener('click', async (evt) => {
      evt.preventDefault();
      evt.stopPropagation();
      const fp = this.hoverMdState?.filePath;
      if (!fp) return;
      const af = this.app.vault.getAbstractFileByPath(fp);
      if (af && af instanceof TFile) await this.app.workspace.getLeaf(true).openFile(af);
    });

    pinBtn.addEventListener('click', (evt) => {
      evt.preventDefault();
      evt.stopPropagation();
      const id = this.hoverMdState?.id;
      if (!id) return;
      void this.openNotePeekForId(id);
      this.closeHoverMarkdownPreview();
    });

    // Dismiss if the user clicks outside the popover (but allow clicking the anchor)
    this.hoverMdOnDocMouseDown = (evt: MouseEvent) => {
      const t = evt.target as any;
      if (!t) return;
      if (this.hoverMdEl?.contains(t)) return;
      if (this.hoverMdState?.anchorEl && this.hoverMdState.anchorEl.contains(t)) return;
      this.closeHoverMarkdownPreview();
    };
    document.addEventListener('mousedown', this.hoverMdOnDocMouseDown, true);

    // Escape to close
    this.hoverMdOnKeyDown = (evt: KeyboardEvent) => {
      if (evt.key === 'Escape') this.closeHoverMarkdownPreview();
    };
    document.addEventListener('keydown', this.hoverMdOnKeyDown, true);

    // If user releases Ctrl/Cmd and isn't hovering the preview or anchor, dismiss.
    this.hoverMdOnKeyUp = (evt: KeyboardEvent) => {
      const want = Boolean((evt as any).ctrlKey) || Boolean((evt as any).metaKey);
      if (want) return;
      if (!this.hoverMdState) return;
      if (this.hoverMdState.onPopover || this.hoverMdState.onAnchor) return;
      this.closeHoverMarkdownPreview();
    };
    document.addEventListener('keyup', this.hoverMdOnKeyUp, true);

    // Scrolling tends to move anchors; safest is to dismiss.
    this.hoverMdOnScroll = () => {
      this.scheduleHoverMarkdownHide(0);
    };
    window.addEventListener('scroll', this.hoverMdOnScroll, true);
  }

  private positionHoverMarkdownPreview(evt: MouseEvent): void {
    if (!this.hoverMdEl) return;
    const rect = this.hoverMdEl.getBoundingClientRect();
    const w = rect.width || Math.max(220, Number(this.plugin.settings.libraryHoverPreviewWidth ?? 420));
    const h = rect.height || Math.max(160, Number(this.plugin.settings.libraryHoverPreviewHeight ?? 320));
    let x = Math.floor(evt.clientX + 16);
    let y = Math.floor(evt.clientY + 14);
    x = Math.max(12, Math.min(window.innerWidth - w - 12, x));
    y = Math.max(12, Math.min(window.innerHeight - h - 12, y));
    this.hoverMdEl.style.left = `${x}px`;
    this.hoverMdEl.style.top = `${y}px`;
  }

  private setHoverMarkdownAnchor(anchorEl: HTMLElement, on: boolean): void {
    if (!this.hoverMdState) return;
    if (this.hoverMdState.anchorEl !== anchorEl) return;
    this.hoverMdState.onAnchor = on;
    if (on) this.clearHoverMarkdownHideTimer();
    else this.scheduleHoverMarkdownHide();
  }

  private async showHoverMarkdownPreview(id: string, evt: MouseEvent, anchorEl: HTMLElement): Promise<void> {
    this.ensureHoverMarkdownPreview();
    if (!this.hoverMdEl || !this.hoverMdBodyEl || !this.hoverMdTitleEl || !this.hoverMdState) return;

    this.clearHoverMarkdownHideTimer();
    this.hoverMdState.anchorEl = anchorEl;
    this.hoverMdState.onAnchor = true;
    this.hoverMdState.id = String(id);
    this.hoverMdState.filePath = '';
    this.hoverMdState.token += 1;
    const token = this.hoverMdState.token;

    this.hoverMdTitleEl.setText(`Preview · ${id}`);
    this.hoverMdBodyEl.empty();
    this.hoverMdBodyEl.createEl('em', { text: 'Loading…' });
    this.positionHoverMarkdownPreview(evt);

    const files = await this.findVaultNotesForId(id);
    const file = files[0];
    if (!this.hoverMdState || token !== this.hoverMdState.token) return;

    if (!file) {
      this.hoverMdBodyEl.empty();
      this.hoverMdBodyEl.createEl('div', { text: 'No _db note found for this ID yet.' });
      this.hoverMdBodyEl.createEl('div', { text: 'Tip: use Pin/Sync to materialize notes into your vault.' });
      return;
    }

    this.hoverMdState.filePath = file.path;

    try {
      const md = await this.app.vault.read(file);
      if (!this.hoverMdState || token !== this.hoverMdState.token) return;
      this.hoverMdBodyEl.empty();
      await MarkdownRenderer.renderMarkdown(String(md ?? ''), this.hoverMdBodyEl, file.path, this);
    } catch (e: any) {
      if (!this.hoverMdState || token !== this.hoverMdState.token) return;
      this.hoverMdBodyEl.empty();
      this.hoverMdBodyEl.createEl('pre', { text: `Failed to render note.\n\n${String(e?.message ?? e)}` });
    }
  }

  private normalizeYamlValue(v: any): any {
    if (v == null) return null;
    if (typeof v !== 'string') return v;
    const s = v.trim();
    if (!s) return null;
    if ((s.startsWith('[') && s.endsWith(']')) || (s.startsWith('{') && s.endsWith('}'))) {
      try {
        return JSON.parse(s);
      } catch {
        return s;
      }
    }
    return s;
  }

  private normalizeTagToken(raw: string): string | null {
    let t = String(raw ?? '').trim();
    if (!t) return null;
    if (t.startsWith('#')) t = t.slice(1);

    // Obsidian tags cannot contain spaces; prefer kebab-case.
    t = t.replace(/\s+/g, '-');
    t = t.replace(/-+/g, '-');
    t = t.replace(/^[-]+|[-]+$/g, '');

    // Keep only common tag-safe characters.
    t = t.replace(/[^A-Za-z0-9/_-]/g, '');
    if (!t) return null;
    return t;
  }

  private normalizeTagsValue(v: any): string[] | null {
    if (v == null) return null;

    const tokens: string[] = [];
    const pushToken = (raw: string) => {
      const t = this.normalizeTagToken(raw);
      if (!t) return;
      if (!tokens.includes(t)) tokens.push(t);
    };

    if (Array.isArray(v)) {
      for (const x of v) pushToken(String(x ?? ''));
    } else {
      const s = String(v ?? '').trim();
      if (!s) return null;
      // Table input uses comma-separated tags; also tolerate newlines.
      for (const part of s.split(/[,\n]/g)) pushToken(part);
    }

    return tokens.length ? tokens : null;
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

  private shouldUseNativeHoverEngine(): boolean {
    const engine = String((this.plugin.settings as any).libraryIdCtrlHoverPreviewEngine || 'auto');
    if (engine === 'native') return true;
    if (engine === 'custom') return false;

    // auto
    try {
      const pp = (this.app as any).internalPlugins?.plugins?.['page-preview'];
      if (pp && pp.enabled) return true;
    } catch {
      // ignore
    }
    return false;
  }

  private closeNotePeek(): void {
    if (!this.notePeekEl) return;
    this.cleanupInlineLeaf();
    try {
      this.notePeekEl.remove();
    } catch {
      // ignore
    }
    this.notePeekEl = null;
    this.notePeekHeaderEl = null;
    this.notePeekBodyEl = null;
    this.notePeekState = null;
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
    const hoverBtn = this.hasHoverEditorInstalled() ? headerBtns.createEl('button', { text: 'Hover' }) : null;
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
      if (id) await this.openNotePeekForId(id);
    });

    hoverBtn?.addEventListener('click', async () => {
      const fp = this.notePeekState?.filePath;
      if (!fp) return;
      const af = this.app.vault.getAbstractFileByPath(fp);
      if (af && af instanceof TFile) {
        await this.openFileInHoverEditor(af);
      }
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
    const text = String(md ?? '');
    if (!text.startsWith('---\n')) return { fm: null, body: text };
    const end = text.indexOf('\n---', 4);
    if (end === -1) return { fm: null, body: text };
    const raw = text.slice(4, end + 1);
    const body = text.slice(end + 4);
    try {
      const fm = parseYaml(raw) as any;
      if (fm && typeof fm === 'object') return { fm: fm as Record<string, any>, body };
    } catch {
      // ignore
    }
    return { fm: null, body: text };
  }

  private buildPeekPrelude(fm: Record<string, any> | null): string {
    if (!fm) return '';
    const lines: string[] = [];

    const pick = (k: string): string => {
      const v = (fm as any)[k];
      if (v == null) return '';
      const s = String(v).trim();
      return s;
    };

    const cover = pick('cover');
    const video = pick('video');
    const caption = pick('caption');
    const videoUrl = pick('video_url');
    const authorUrl = pick('author_url');

    // If none of our known fields exist, don't add noise.
    if (!cover && !video && !caption && !videoUrl && !authorUrl) return '';

    lines.push('## Preview');
    lines.push('');

    if (cover) {
      // Try to render as an embed so the preview shows the actual image.
      lines.push('**Cover**');
      lines.push(`![[${cover}]]`);
      lines.push('');
    }

    if (video) {
      lines.push('**Video**');
      // Embedding video in reading view can work; if not, it still shows a clickable link.
      lines.push(`![[${video}]]`);
      lines.push('');
    }

    if (caption) {
      lines.push('**Caption**');
      lines.push(caption);
      lines.push('');
    }

    const links: string[] = [];
    if (videoUrl) links.push(`- video_url: ${videoUrl}`);
    if (authorUrl) links.push(`- author_url: ${authorUrl}`);
    if (links.length) {
      lines.push('**Links**');
      lines.push(...links);
      lines.push('');
    }

    // Divider between prelude and body.
    lines.push('---');
    lines.push('');
    return lines.join('\n');
  }

  private async openNotePeekForId(id: string): Promise<void> {
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

    // If user wants to rely on Obsidian's own rendering/modes, delegate to native note views.
    const engine = this.notePeekEngine();
    if (engine === 'hover-editor') {
      await this.openFileInHoverEditor(file);
      return;
    }
    if (engine === 'popout') {
      await this.openFileInNotePeekPopout(file);
      return;
    }

    this.ensureNotePeek();
    if (!this.notePeekEl || !this.notePeekBodyEl || !this.notePeekState) return;

    // If a leaf was previously embedded but the engine changed, clean it up.
    if (engine !== 'inline-leaf' && this.notePeekLeaf) {
      this.cleanupInlineLeaf();
    }

    // Inline leaf: mount a real Obsidian leaf/view into our window.
    if (engine === 'inline-leaf') {
      const leaf = await this.ensureInlineLeafHost();
      if (!leaf) {
        new Notice('Inline (Obsidian leaf) could not be mounted. Falling back to Inline renderer.');
      } else {
        this.notePeekState.id = String(id);
        this.notePeekState.filePath = file.path;
        const title = this.notePeekEl.querySelector('.sxdb-notepeek-title') as HTMLDivElement | null;
        if (title) title.setText(`Note Peek · ${id}`);
        try {
          await leaf.openFile(file);
          window.setTimeout(() => {
            try {
              (leaf as any)?.view?.onResize?.();
            } catch {
              // ignore
            }
          }, 0);
          return;
        } catch {
          // If leaf open fails, clean up and fall through to inline renderer.
          this.cleanupInlineLeaf();
        }
      }
    }

    this.notePeekState.id = String(id);
    this.notePeekState.filePath = file.path;

    const title = this.notePeekEl.querySelector('.sxdb-notepeek-title') as HTMLDivElement | null;
    if (title) title.setText(`Note Peek · ${id}`);

    try {
      const md = await this.app.vault.read(file);
      this.notePeekBodyEl.empty();

      // Source vs rendered preview.
      if (this.notePeekMode === 'source') {
        this.notePeekBodyEl.createEl('pre', { text: String(md ?? '') });
        return;
      }

      // Render a "page preview" style view:
      // - Prefer rendering *the file's content* (body)
      // - Add a lightweight prelude that visually previews key properties (cover/video/caption)
      //   because Obsidian's full Properties UI is tied to the MarkdownView pipeline.
      const { fm, body } = this.extractFrontmatter(String(md ?? ''));
      const prelude = this.buildPeekPrelude(fm);
      const renderMd = `${prelude}${body || ''}`;
      await MarkdownRenderer.renderMarkdown(renderMd, this.notePeekBodyEl, file.path, this);
    } catch (e: any) {
      this.notePeekBodyEl.empty();
      this.notePeekBodyEl.createEl('pre', {
        text: `Failed to render note.\n\n${String(e?.message ?? e)}`
      });
    }
  }

  private async openVaultNoteForId(id: string): Promise<boolean> {
    const safeId = String(id || '').trim();
    if (!safeId) return false;

    const candidates: string[] = [
      normalizePath(`${this.plugin.settings.activeNotesDir}/${safeId}.md`),
      normalizePath(`${this.plugin.settings.bookmarksNotesDir}/${safeId}.md`)
    ];

    for (const p of candidates) {
      const af = this.app.vault.getAbstractFileByPath(p);
      if (af && af instanceof TFile) {
        await this.app.workspace.getLeaf(true).openFile(af);
        return true;
      }
    }

    const authorsRoot = normalizePath(this.plugin.settings.authorsNotesDir);
    const found = this.app.vault
      .getFiles()
      .find((f) => f.extension === 'md' && f.basename === safeId && (f.path === authorsRoot || f.path.startsWith(authorsRoot + '/')));
    if (found) {
      await this.app.workspace.getLeaf(true).openFile(found);
      return true;
    }

    return false;
  }

  private slugFolderName(s: string): string {
    const v = (s || '').trim().toLowerCase();
    const slug = v
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+/, '')
      .replace(/-+$/, '');
    return slug || 'unknown';
  }

  /** Command hook: materialize current table selection into vault (_db folders). */
  async syncCurrentSelection(): Promise<void> {
    const batch = Math.max(10, this.plugin.settings.syncBatchSize ?? 200);
    const maxItems = Math.max(0, this.plugin.settings.syncMaxItems ?? 2000);
    const replace = Boolean(this.plugin.settings.syncReplaceOnPull);
    const strategy = String(this.plugin.settings.vaultWriteStrategy || 'split');

    const baseParams: string[] = [];
    baseParams.push(`q=${encodeURIComponent(this.q)}`);
    baseParams.push(`bookmarked_only=${this.bookmarkedOnly ? 'true' : 'false'}`);
    baseParams.push(`order=${encodeURIComponent(this.sortOrder)}`);
    if (this.authorFilter) baseParams.push(`author_unique_id=${encodeURIComponent(this.authorFilter)}`);
    if (this.statusFilters.size) baseParams.push(`status=${encodeURIComponent(Array.from(this.statusFilters).join(','))}`);
    if (this.tagFilter.trim()) baseParams.push(`tag=${encodeURIComponent(this.tagFilter.trim())}`);
    if (this.captionFilter.trim()) baseParams.push(`caption_q=${encodeURIComponent(this.captionFilter.trim())}`);
    if (this.ratingMin.trim()) baseParams.push(`rating_min=${encodeURIComponent(this.ratingMin.trim())}`);
    if (this.ratingMax.trim()) baseParams.push(`rating_max=${encodeURIComponent(this.ratingMax.trim())}`);
    if (this.hasNotesOnly) baseParams.push(`has_notes=true`);

    const baseUrl = this.baseUrl();
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
      const url = `${baseUrl}/notes?limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}&${baseParams.join('&')}`;

      const resp = await requestUrl({ url });
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

    new Notice(`Sync complete: wrote ${written} note(s).`);
    // refresh current page (optional) so user sees updated counts/status etc.
    void this.refresh();
  }

  /** Command hook: refresh current table page from API using current filters. */
  async refresh(): Promise<void> {
    const limit = this.pageLimit();

    const params: string[] = [];
    params.push(`q=${encodeURIComponent(this.q)}`);
    params.push(`limit=${encodeURIComponent(String(limit))}`);
    params.push(`offset=${encodeURIComponent(String(this.offset))}`);
    params.push(`bookmarked_only=${this.bookmarkedOnly ? 'true' : 'false'}`);
    params.push(`order=${encodeURIComponent(this.sortOrder)}`);
    if (this.authorFilter) params.push(`author_unique_id=${encodeURIComponent(this.authorFilter)}`);
    if (this.statusFilters.size) params.push(`status=${encodeURIComponent(Array.from(this.statusFilters).join(','))}`);
    if (this.tagFilter.trim()) params.push(`tag=${encodeURIComponent(this.tagFilter.trim())}`);
    if (this.captionFilter.trim()) params.push(`caption_q=${encodeURIComponent(this.captionFilter.trim())}`);
    if (this.ratingMin.trim()) params.push(`rating_min=${encodeURIComponent(this.ratingMin.trim())}`);
    if (this.ratingMax.trim()) params.push(`rating_max=${encodeURIComponent(this.ratingMax.trim())}`);
    if (this.hasNotesOnly) params.push(`has_notes=true`);

    const url = `${this.baseUrl()}/items?${params.join('&')}`;

    try {
      const resp = await requestUrl({ url });
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
      const url = `${this.baseUrl()}/authors?limit=2000&offset=0&order=count`;
      const resp = await requestUrl({ url });
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

    // ID wrapping mode (affects ID column presentation)
    const idWrap = String(this.plugin.settings.libraryIdWrapMode || 'ellipsis');
    contentEl.setAttr('data-sxdb-idwrap', idWrap);

    // Apply hover preview sizing via CSS variables (so it updates without CSS edits).
    const w = Math.max(120, Number(this.plugin.settings.libraryHoverPreviewWidth ?? 360));
    const h = Math.max(90, Number(this.plugin.settings.libraryHoverPreviewHeight ?? 202));
    contentEl.style.setProperty('--sxdb-hovervideo-width', `${Math.floor(w)}px`);
    contentEl.style.setProperty('--sxdb-hovervideo-height', `${Math.floor(h)}px`);

    const header = contentEl.createDiv({ cls: 'sxdb-lib-header' });
    header.createEl('h2', { text: 'SX Library (DB)' });

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

    const syncTopBtn = menuBtns.createEl('button', { text: 'Sync', cls: 'sxdb-lib-menubtn' });
    syncTopBtn.addEventListener('click', () => {
      void this.syncCurrentSelection().catch((e: any) => {
        new Notice(`Sync failed: ${String(e?.message ?? e)}`);
      });
    });

    const clearTopBtn = menuBtns.createEl('button', { text: 'Clear', cls: 'sxdb-lib-menubtn' });
    clearTopBtn.addEventListener('click', () => {
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
        panel.createEl('div', { text: 'ID wrapping', cls: 'sxdb-lib-viewmenu-section' });

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
    const w = Math.max(120, Number(this.plugin.settings.libraryHoverPreviewWidth ?? 360));
    const h = Math.max(90, Number(this.plugin.settings.libraryHoverPreviewHeight ?? 202));
    this.contentEl.style.setProperty('--sxdb-hovervideo-width', `${Math.floor(w)}px`);
    this.contentEl.style.setProperty('--sxdb-hovervideo-height', `${Math.floor(h)}px`);

    const pageInfo = (this as any)._pageInfoEl as HTMLDivElement | undefined;
    if (pageInfo) {
      const start = this.total ? this.offset + 1 : 0;
      const end = Math.min(this.total, this.offset + limit);
      pageInfo.setText(`${start}–${end} of ${this.total}`);
    }

    const table = wrap.createEl('table', { cls: 'sxdb-lib-table' });

    const defs: Array<{ key: string; label: string }> = [
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
      { key: 'platform_targets', label: 'Platform targets' },
      { key: 'post_url', label: 'Post URL' },
      { key: 'published_time', label: 'Published time' },
      { key: 'workflow_log', label: 'Workflow log' },
      { key: 'actions', label: 'Actions' }
    ];

    const allKeys = defs.map((d) => d.key);
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

    for (const it of items) {
      const tr = tbody.createEl('tr');

      const meta = it.meta ?? {};

      // status is now edited via a multi-select popover; see status column renderer.
      let rating: HTMLInputElement | null = null;
      let tags: HTMLInputElement | null = null;
      let notes: HTMLInputElement | null = null;
      let productLink: HTMLInputElement | null = null;
      let platformTargets: HTMLInputElement | null = null;
      let postUrl: HTMLInputElement | null = null;
      let publishedTime: HTMLInputElement | null = null;
      let workflowLog: HTMLInputElement | null = null;

      let previewBtn: HTMLButtonElement | null = null;
      let openLocalBtn: HTMLButtonElement | null = null;
      let revealLocalBtn: HTMLButtonElement | null = null;
      let pinBtn: HTMLButtonElement | null = null;
      let unpinBtn: HTMLButtonElement | null = null;

      for (const c of visibleDefs) {
        if (c.key === 'thumb') {
          const td = tr.createEl('td', { cls: 'sxdb-lib-thumb' });
          td.setAttr('data-col', 'thumb');
          const img = td.createEl('img');
          img.loading = 'lazy';
          if (it.cover_path) {
            img.src = `${this.baseUrl()}/media/cover/${encodeURIComponent(it.id)}`;
            img.addEventListener('error', () => {
              img.style.display = 'none';
            });
          } else {
            img.style.display = 'none';
          }

          if (this.plugin.settings.libraryHoverVideoPreview) {
            const video = td.createEl('video', { cls: 'sxdb-lib-hovervideo' });
            video.muted = Boolean(this.plugin.settings.libraryHoverPreviewMuted);
            video.loop = true;
            video.playsInline = true;
            video.preload = 'none';
            video.controls = true;
            video.src = `${this.baseUrl()}/media/video/${encodeURIComponent(it.id)}`;

            const show = async () => {
              video.style.display = 'block';
              try {
                await video.play();
              } catch {
                // Autoplay might be blocked (especially with sound). Controls still allow manual play.
              }
            };
            const hide = () => {
              try {
                video.pause();
              } catch {
                // ignore
              }
              video.style.display = 'none';
            };

            td.addEventListener('mouseenter', () => void show());
            td.addEventListener('mouseleave', () => hide());
            video.style.display = 'none';
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
              void this.openNotePeekForId(it.id);
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

            if (this.shouldUseNativeHoverEngine()) {
              void this.findVaultNotesForId(it.id).then((files) => {
                const f = files[0];
                if (!f) return;
                this.triggerObsidianHoverPreview(evt, f, btn);
              });
              return;
            }

            void this.showHoverMarkdownPreview(it.id, evt, btn);
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
              void this.openNotePeekForId(it.id);
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
        const payload: any = {
          status: meta.status ?? null,
          statuses: Array.isArray((meta as any).statuses) ? (meta as any).statuses : (meta.status ? [meta.status] : null),
          rating: meta.rating ?? null,
          tags: meta.tags ?? null,
          notes: meta.notes ?? null,
          product_link: meta.product_link ?? null,
          platform_targets: meta.platform_targets ?? null,
          workflow_log: meta.workflow_log ?? null,
          post_url: meta.post_url ?? null,
          published_time: meta.published_time ?? null
        };

        // statusSel removed (multi-choice status editor writes into meta.status/meta.statuses)
        if (rating) payload.rating = rating.value ? Number(rating.value) : null;
        if (tags) payload.tags = tags.value.trim() || null;
        if (notes) payload.notes = notes.value.trim() || null;
        if (productLink) payload.product_link = productLink.value.trim() || null;
        if (platformTargets) payload.platform_targets = platformTargets.value.trim() || null;
        if (workflowLog) payload.workflow_log = workflowLog.value.trim() || null;
        if (postUrl) payload.post_url = postUrl.value.trim() || null;
        if (publishedTime) payload.published_time = publishedTime.value.trim() || null;

        try {
          await requestUrl({
            url: `${this.baseUrl()}/items/${encodeURIComponent(it.id)}/meta`,
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
        } catch (e: any) {
          new Notice(`Failed saving meta for ${it.id}: ${String(e?.message ?? e)}`);
        }
      };

      // status changes are persisted immediately by the status editor
      rating?.addEventListener('change', () => void saveMeta());
      tags?.addEventListener('change', () => void saveMeta());
      notes?.addEventListener('change', () => void saveMeta());
      productLink?.addEventListener('change', () => void saveMeta());
      platformTargets?.addEventListener('change', () => void saveMeta());
      workflowLog?.addEventListener('change', () => void saveMeta());
      postUrl?.addEventListener('change', () => void saveMeta());
      publishedTime?.addEventListener('change', () => void saveMeta());

      previewBtn?.addEventListener('click', () => {
        const url = `${this.baseUrl()}/media/video/${encodeURIComponent(it.id)}`;
        window.open(url);
      });

      const openOrReveal = async (kind: 'open' | 'reveal') => {
        try {
          // Prefer dedicated endpoint that computes links from canonical paths.
          const linksResp = await requestUrl({ url: `${this.baseUrl()}/items/${encodeURIComponent(it.id)}/links` });
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
          const resp = await requestUrl({ url: `${this.baseUrl()}/items/${encodeURIComponent(it.id)}/note` });
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
          const resp = await requestUrl({ url: `${this.baseUrl()}/items/${encodeURIComponent(it.id)}/note` });
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
  }
}
