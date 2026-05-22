/* eslint-disable react-hooks/incompatible-library */
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronsLeft, ChevronsRight, ChevronLeft, ChevronRight, Inbox } from "lucide-react";

import { EmptyState } from "./empty-state";
import { Button } from "./ui/button";
import { rs } from "../lib/design-tokens";
import { cn } from "../lib/utils";

export interface DataTablePagination {
  page: number;
  pageSize: number;
  totalItems: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (pageSize: number) => void;
  pageSizeOptions?: number[];
  itemLabel?: string;
  isLoading?: boolean;
}

interface DataTableProps<TData> {
  columns: ColumnDef<TData>[];
  data: TData[];
  emptyTitle: string;
  emptyDescription: string;
  ariaLabel?: string;
  className?: string;
  pagination?: DataTablePagination;
}

export function DataTable<TData>({
  columns,
  data,
  emptyTitle,
  emptyDescription,
  ariaLabel,
  className,
  pagination,
}: DataTableProps<TData>) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  if (data.length === 0) {
    return (
      <EmptyState
        icon={Inbox}
        title={emptyTitle}
        description={emptyDescription}
        className={className}
      />
    );
  }

  return (
    <div
      className={cn(
        `flex min-w-0 max-w-full flex-col overflow-hidden rounded-md border ${rs.border.line} ${rs.bg.paper}`,
        className,
      )}
    >
      <div className="max-w-full overflow-x-auto">
        <table aria-label={ariaLabel} className="w-full min-w-[720px] table-fixed text-left text-sm">
          <thead className={`border-b ${rs.border.line} ${rs.bg.field} text-xs uppercase ${rs.text.body}`}>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id} className="px-4 py-3 font-semibold">
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className={`divide-y ${rs.divide.line}`}>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className={rs.hover.field}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className={`min-w-0 overflow-hidden px-4 py-3 align-middle ${rs.text.body}`}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pagination ? <DataTablePaginationFooter pagination={pagination} /> : null}
    </div>
  );
}

function DataTablePaginationFooter({ pagination }: { pagination: DataTablePagination }) {
  const pageSizeOptions = pagination.pageSizeOptions ?? [10, 25, 50, 100];
  const pageSize = Math.max(1, pagination.pageSize);
  const totalItems = Math.max(0, pagination.totalItems);
  const pageCount = Math.max(1, Math.ceil(totalItems / pageSize));
  const page = Math.min(Math.max(1, pagination.page), pageCount);
  const startItem = totalItems === 0 ? 0 : (page - 1) * pageSize + 1;
  const endItem = Math.min(totalItems, page * pageSize);
  const itemLabel = pagination.itemLabel ?? "rows";
  const isLoading = pagination.isLoading ?? false;
  const canGoPrevious = page > 1 && !isLoading;
  const canGoNext = page < pageCount && !isLoading;

  return (
    <div
      className={`flex flex-col gap-3 border-t px-3 py-3 text-sm ${rs.border.line} ${rs.text.body} sm:flex-row sm:items-center sm:justify-between`}
    >
      <p className="min-w-0 text-xs font-medium text-[var(--rs-muted)]" aria-live="polite">
        Showing {startItem}-{endItem} of {totalItems} {itemLabel}
      </p>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        {pagination.onPageSizeChange ? (
          <label className="flex items-center gap-2 text-xs font-medium text-[var(--rs-muted)]">
            Rows
            <select
              value={pageSize}
              onChange={(event) => pagination.onPageSizeChange?.(Number(event.target.value))}
              disabled={isLoading}
              className="h-8 rounded-md border border-[var(--rs-line-strong)] bg-[var(--rs-paper)] px-2 text-xs text-[var(--rs-text)] outline-none focus:ring-2 focus:ring-[var(--rs-accent)]"
              aria-label="Rows per page"
            >
              {pageSizeOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="flex items-center gap-2">
          <p className="text-xs font-medium text-[var(--rs-muted)]">
            Page {page} of {pageCount}
          </p>
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={() => pagination.onPageChange(1)}
              disabled={!canGoPrevious}
              aria-label="Go to first page"
            >
              <ChevronsLeft className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={() => pagination.onPageChange(page - 1)}
              disabled={!canGoPrevious}
              aria-label="Go to previous page"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={() => pagination.onPageChange(page + 1)}
              disabled={!canGoNext}
              aria-label="Go to next page"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              onClick={() => pagination.onPageChange(pageCount)}
              disabled={!canGoNext}
              aria-label="Go to last page"
            >
              <ChevronsRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
