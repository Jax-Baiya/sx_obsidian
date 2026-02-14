export type HoverVideoResizeMode = 'scale' | 'free';

export const WORKFLOW_STATUSES = ['raw', 'reviewing', 'reviewed', 'scheduling', 'scheduled', 'published', 'archived'] as const;

export interface HoverVideoSizeInput {
  mode?: HoverVideoResizeMode | string;
  scalePct?: number;
  width?: number;
  height?: number;
}

export interface HoverVideoSize {
  w: number;
  h: number;
}

export const TIKTOK_PREVIEW_BASE = {
  w: 240,
  h: 426
} as const;

export function computeHoverVideoSizePx(input: HoverVideoSizeInput): HoverVideoSize {
  const baseW = TIKTOK_PREVIEW_BASE.w;
  const baseH = TIKTOK_PREVIEW_BASE.h;
  const mode = String(input?.mode || 'scale');

  if (mode === 'free') {
    const w = Math.max(120, Number(input?.width ?? baseW));
    const h = Math.max(90, Number(input?.height ?? baseH));
    return { w: Math.floor(w), h: Math.floor(h) };
  }

  const scalePct = Number(input?.scalePct ?? 100);
  const safeScale = Number.isFinite(scalePct) ? Math.max(40, Math.min(300, scalePct)) : 100;
  const mul = safeScale / 100;
  const w = Math.max(96, Math.floor(baseW * mul));
  const h = Math.max(170, Math.floor(baseH * mul));
  return { w, h };
}

export function parseLinksValue(v: unknown): string[] {
  if (v == null) return [];

  let rawItems: string[] = [];
  if (Array.isArray(v)) {
    rawItems = v.map((x) => String(x).trim());
  } else {
    const s = String(v).trim();
    if (!s) return [];

    if ((s.startsWith('[') && s.endsWith(']')) || (s.startsWith('{') && s.endsWith('}'))) {
      try {
        const obj = JSON.parse(s);
        if (Array.isArray(obj)) {
          rawItems = obj.map((x) => String(x).trim());
        } else {
          rawItems = [s];
        }
      } catch {
        rawItems = s.split(/[\n,]/g).map((x) => String(x).trim());
      }
    } else {
      rawItems = s.split(/[\n,]/g).map((x) => String(x).trim());
    }
  }

  const out: string[] = [];
  for (const x of rawItems) {
    if (!x) continue;
    if (out.includes(x)) continue;
    out.push(x);
  }
  return out;
}

export function getWorkflowStatuses(): string[] {
  return [...WORKFLOW_STATUSES];
}

export function choosePrimaryWorkflowStatus(statuses: string[]): string | null {
  const clean = (statuses || []).map((s) => String(s).trim()).filter(Boolean);
  if (!clean.length) return null;
  const order = getWorkflowStatuses();
  const ranked = order.filter((s) => clean.includes(s));
  return ranked.length ? ranked[ranked.length - 1] : clean[0];
}

export function normalizeTagToken(raw: string): string | null {
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

export function normalizeTagsValue(v: unknown): string[] | null {
  if (v == null) return null;

  const tokens: string[] = [];
  const pushToken = (raw: string) => {
    const t = normalizeTagToken(raw);
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

export function formatLinkChipLabel(url: string): string {
  const raw = String(url || '').trim();
  if (!raw) return '';
  try {
    const parsed = new URL(raw);
    const host = parsed.hostname.replace(/^www\./i, '');
    const seg = parsed.pathname
      .split('/')
      .filter(Boolean)
      .slice(0, 1)
      .join('/');
    return seg ? `${host}/${seg}` : host;
  } catch {
    return raw;
  }
}

export function validateHttpUrlLike(v: string): boolean {
  const s = String(v || '').trim();
  if (!s) return true;
  try {
    const u = new URL(s);
    return /^https?:$/i.test(u.protocol);
  } catch {
    return false;
  }
}

export function cellSelectionKey(rowId: string, colKey: string): string {
  return `${rowId}::${colKey}`;
}

export function shouldCommitLinkChipOnKey(key: string, mode: 'tab' | 'enter' | 'both' | string): boolean {
  if (mode === 'enter') return key === 'Enter';
  if (mode === 'both') return key === 'Enter' || key === 'Tab';
  return key === 'Tab';
}

export function clearSingleSelectionState(
  selectedCells: Set<string>,
  selectedRows: Set<string>,
  selectedCols: Set<string>
): void {
  selectedCells.clear();
  selectedRows.clear();
  selectedCols.clear();
}

export function isOnlyColumnSelection(
  selectedCells: Set<string>,
  selectedRows: Set<string>,
  selectedCols: Set<string>,
  tableSelectedAll: boolean,
  colKey: string
): boolean {
  return selectedCols.size === 1
    && selectedCols.has(colKey)
    && selectedRows.size === 0
    && selectedCells.size === 0
    && !tableSelectedAll;
}

export function isOnlyRowSelection(
  selectedCells: Set<string>,
  selectedRows: Set<string>,
  selectedCols: Set<string>,
  tableSelectedAll: boolean,
  rowId: string
): boolean {
  return selectedRows.size === 1
    && selectedRows.has(rowId)
    && selectedCols.size === 0
    && selectedCells.size === 0
    && !tableSelectedAll;
}

export function isOnlyCellSelection(
  selectedCells: Set<string>,
  selectedRows: Set<string>,
  selectedCols: Set<string>,
  tableSelectedAll: boolean,
  rowId: string,
  colKey: string
): boolean {
  const key = cellSelectionKey(rowId, colKey);
  return selectedCells.size === 1
    && selectedCells.has(key)
    && selectedRows.size === 0
    && selectedCols.size === 0
    && !tableSelectedAll;
}

export function applySelectAllToggle(
  selectedCells: Set<string>,
  selectedRows: Set<string>,
  selectedCols: Set<string>,
  tableSelectedAll: boolean
): boolean {
  const already = tableSelectedAll;
  clearSingleSelectionState(selectedCells, selectedRows, selectedCols);
  return !already;
}

export function applyColumnSingleSelection(
  selectedCells: Set<string>,
  selectedRows: Set<string>,
  selectedCols: Set<string>,
  tableSelectedAll: boolean,
  colKey: string
): boolean {
  const already = isOnlyColumnSelection(selectedCells, selectedRows, selectedCols, tableSelectedAll, colKey);
  clearSingleSelectionState(selectedCells, selectedRows, selectedCols);
  if (!already) selectedCols.add(colKey);
  return false;
}

export function applyRowSingleSelection(
  selectedCells: Set<string>,
  selectedRows: Set<string>,
  selectedCols: Set<string>,
  tableSelectedAll: boolean,
  rowId: string
): boolean {
  const already = isOnlyRowSelection(selectedCells, selectedRows, selectedCols, tableSelectedAll, rowId);
  clearSingleSelectionState(selectedCells, selectedRows, selectedCols);
  if (!already) selectedRows.add(rowId);
  return false;
}

export function applyCellSingleSelection(
  selectedCells: Set<string>,
  selectedRows: Set<string>,
  selectedCols: Set<string>,
  tableSelectedAll: boolean,
  rowId: string,
  colKey: string
): boolean {
  const already = isOnlyCellSelection(selectedCells, selectedRows, selectedCols, tableSelectedAll, rowId, colKey);
  clearSingleSelectionState(selectedCells, selectedRows, selectedCols);
  if (!already) selectedCells.add(cellSelectionKey(rowId, colKey));
  return false;
}

export function hasAnyVisibleColumns(columns: Record<string, boolean>): boolean {
  return Object.keys(columns).some((k) => Boolean(columns[k]));
}

export function sanitizeColumnOrder(savedOrder: unknown, allKeys: string[]): string[] {
  const order: string[] = [];
  const seen = new Set<string>();
  const arr = Array.isArray(savedOrder) ? savedOrder : [];
  for (const k of arr) {
    if (typeof k !== 'string') continue;
    if (!allKeys.includes(k)) continue;
    if (seen.has(k)) continue;
    seen.add(k);
    order.push(k);
  }
  for (const k of allKeys) {
    if (!seen.has(k)) order.push(k);
  }
  return order;
}

export function sanitizeColumnWidths(raw: unknown): Record<string, number> {
  const next: Record<string, number> = {};
  if (!raw || typeof raw !== 'object') return next;
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    const n = Number(v);
    if (Number.isFinite(n) && n > 0) next[String(k)] = Math.floor(n);
  }
  return next;
}

// ---------------------------------------------------------------------------
// Phase-2 scaffold: stable API surface + adapter contracts (non-breaking).
// These contracts are intentionally framework-agnostic and can be implemented
// by Obsidian, SchedulerX frontend, or any future host.
// ---------------------------------------------------------------------------

export interface LibraryCoreSelectionSnapshot {
  selectedCells: ReadonlySet<string>;
  selectedRows: ReadonlySet<string>;
  selectedCols: ReadonlySet<string>;
  tableSelectedAll: boolean;
}

export interface LibraryCoreMediaPreviewConfig {
  mode: HoverVideoResizeMode;
  scalePct?: number;
  width?: number;
  height?: number;
}

export interface LibraryCoreHostAdapter {
  now?(): number;
  openExternalUrl?(url: string): void;
  copyToClipboard?(text: string): Promise<boolean>;
}

export interface LibraryCorePublicApi {
  readonly version: '1.0.0';
  readonly workflowStatuses: readonly string[];
  computeHoverVideoSizePx: typeof computeHoverVideoSizePx;
  parseLinksValue: typeof parseLinksValue;
  formatLinkChipLabel: typeof formatLinkChipLabel;
  validateHttpUrlLike: typeof validateHttpUrlLike;
  normalizeTagToken: typeof normalizeTagToken;
  normalizeTagsValue: typeof normalizeTagsValue;
  choosePrimaryWorkflowStatus: typeof choosePrimaryWorkflowStatus;
  shouldCommitLinkChipOnKey: typeof shouldCommitLinkChipOnKey;
  cellSelectionKey: typeof cellSelectionKey;
  clearSingleSelectionState: typeof clearSingleSelectionState;
  applySelectAllToggle: typeof applySelectAllToggle;
  applyColumnSingleSelection: typeof applyColumnSingleSelection;
  applyRowSingleSelection: typeof applyRowSingleSelection;
  applyCellSingleSelection: typeof applyCellSingleSelection;
  hasAnyVisibleColumns: typeof hasAnyVisibleColumns;
  sanitizeColumnOrder: typeof sanitizeColumnOrder;
  sanitizeColumnWidths: typeof sanitizeColumnWidths;
}

export const libraryCoreApi: LibraryCorePublicApi = {
  version: '1.0.0',
  workflowStatuses: WORKFLOW_STATUSES,
  computeHoverVideoSizePx,
  parseLinksValue,
  formatLinkChipLabel,
  validateHttpUrlLike,
  normalizeTagToken,
  normalizeTagsValue,
  choosePrimaryWorkflowStatus,
  shouldCommitLinkChipOnKey,
  cellSelectionKey,
  clearSingleSelectionState,
  applySelectAllToggle,
  applyColumnSingleSelection,
  applyRowSingleSelection,
  applyCellSingleSelection,
  hasAnyVisibleColumns,
  sanitizeColumnOrder,
  sanitizeColumnWidths
};
