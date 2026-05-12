/* eslint-disable react-hooks/incompatible-library */
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";

import { EmptyState } from "./empty-state";
import { cn } from "../lib/utils";
import { Inbox } from "lucide-react";

interface DataTableProps<TData> {
  columns: ColumnDef<TData>[];
  data: TData[];
  emptyTitle: string;
  emptyDescription: string;
  ariaLabel?: string;
  className?: string;
}

export function DataTable<TData>({
  columns,
  data,
  emptyTitle,
  emptyDescription,
  ariaLabel,
  className,
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
    <div className={cn("min-w-0 max-w-full overflow-hidden rounded-md border border-[#d6dde1] bg-white", className)}>
      <div className="max-w-full overflow-x-auto">
        <table aria-label={ariaLabel} className="w-full min-w-[720px] table-fixed text-left text-sm">
          <thead className="border-b border-[#d6dde1] bg-[#f4f7f8] text-xs uppercase text-[#62717a]">
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
          <tbody className="divide-y divide-[#edf1f3]">
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="hover:bg-[#f7fafb]">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="min-w-0 overflow-hidden px-4 py-3 align-middle text-[#24313a]">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
