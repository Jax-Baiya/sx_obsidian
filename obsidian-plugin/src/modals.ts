import { App, Modal } from 'obsidian';
import { sxPinById } from './actions';
import type SxDbPlugin from './main';

type SearchRow = {
  id: string;
  author_unique_id?: string;
  author_name?: string;
  snippet?: string;
  bookmarked?: number;
};

export class SearchModal extends Modal {
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

    const limit = Math.max(1, this.plugin.settings.searchLimit ?? 50);
    const bookmarkedOnly = Boolean(this.plugin.settings.bookmarkedOnly);

    try {
      const resp = await this.plugin.apiRequest({
        path: '/search',
        query: { q, limit: String(limit), offset: '0' }
      });
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

export class PinByIdModal extends Modal {
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
