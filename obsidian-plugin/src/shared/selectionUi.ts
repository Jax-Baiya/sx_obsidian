import { cellSelectionKey } from '../libraryCore';

export function applySelectionClasses(
  table: HTMLTableElement,
  selectedCells: Set<string>,
  selectedRows: Set<string>,
  selectedCols: Set<string>,
  tableSelectedAll: boolean
): void {
  if (!table?.isConnected) return;

  const headers = table.querySelectorAll('thead th[data-col]') as NodeListOf<HTMLTableCellElement>;
  headers.forEach((th) => {
    const col = String(th.getAttribute('data-col') || '').trim();
    if (!col) return;
    const selected = (col === 'index' && tableSelectedAll) || selectedCols.has(col);
    if (selected) th.addClass('sxdb-cell-selected');
    else th.removeClass('sxdb-cell-selected');
  });

  const rows = table.querySelectorAll('tbody tr[data-row-id]') as NodeListOf<HTMLTableRowElement>;
  rows.forEach((tr) => {
    const rowId = String(tr.getAttribute('data-row-id') || '').trim();
    if (!rowId) return;
    const cells = tr.querySelectorAll('td[data-col]') as NodeListOf<HTMLTableCellElement>;
    cells.forEach((td) => {
      const col = String(td.getAttribute('data-col') || '').trim();
      if (!col) return;
      const selected = tableSelectedAll
        || selectedRows.has(rowId)
        || selectedCols.has(col)
        || selectedCells.has(cellSelectionKey(rowId, col));
      if (selected) td.addClass('sxdb-cell-selected');
      else td.removeClass('sxdb-cell-selected');
    });
  });
}
