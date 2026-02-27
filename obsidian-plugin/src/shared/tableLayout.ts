export function applyStickyOffsets(root: HTMLElement): void {
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

export function applyFreezePanesLayout(
  table: HTMLTableElement,
  visibleKeys: string[],
  freezeCols: 0 | 1 | 2,
  freezeFirstRow: boolean,
  columnWidths: Record<string, number>
): void {
  if (!table?.isConnected) return;

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
    if (freezeCols === 0) return [];

    if (freezeCols === 1) {
      if (has('id')) return ['id'];
      return [keys[0]];
    }

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
      header ? Math.ceil(header.getBoundingClientRect().width) : Math.ceil(Number(columnWidths[key] || 0))
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

  if (freezeFirstRow) {
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
