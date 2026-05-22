import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { DataTable } from "../src/components/data-table";

interface Row {
  name: string;
}

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: "name",
    header: "Name",
    cell: ({ row }) => row.original.name,
  },
];

describe("DataTable", () => {
  it("renders shared pagination controls when pagination is provided", () => {
    const onPageChange = vi.fn();

    render(
      <DataTable
        ariaLabel="Example table"
        columns={columns}
        data={[{ name: "Alpha" }, { name: "Beta" }]}
        emptyTitle="No rows"
        emptyDescription="Rows will appear here."
        pagination={{
          page: 2,
          pageSize: 2,
          totalItems: 5,
          onPageChange,
          itemLabel: "records",
        }}
      />,
    );

    expect(screen.getByText("Showing 3-4 of 5 records")).toBeVisible();
    expect(screen.getByText("Page 2 of 3")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Go to next page" }));
    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it("supports controlled page size changes", () => {
    function Harness() {
      const rows = useMemo(
        () => Array.from({ length: 30 }, (_, index) => ({ name: `Row ${index + 1}` })),
        [],
      );
      const [page, setPage] = useState(1);
      const [pageSize, setPageSize] = useState(10);
      const visibleRows = rows.slice((page - 1) * pageSize, page * pageSize);

      return (
        <DataTable
          ariaLabel="Paged table"
          columns={columns}
          data={visibleRows}
          emptyTitle="No rows"
          emptyDescription="Rows will appear here."
          pagination={{
            page,
            pageSize,
            totalItems: rows.length,
            onPageChange: setPage,
            onPageSizeChange: (nextPageSize) => {
              setPageSize(nextPageSize);
              setPage(1);
            },
            pageSizeOptions: [10, 25],
          }}
        />
      );
    }

    render(<Harness />);

    const table = screen.getByRole("table", { name: "Paged table" });
    expect(within(table).getByText("Row 10")).toBeVisible();
    expect(screen.getByText("Showing 1-10 of 30 rows")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Rows per page"), { target: { value: "25" } });

    expect(within(table).getByText("Row 25")).toBeVisible();
    expect(screen.getByText("Showing 1-25 of 30 rows")).toBeVisible();
  });
});
