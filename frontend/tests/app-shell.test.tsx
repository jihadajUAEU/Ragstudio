import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "../src/components/app-shell";

describe("AppShell", () => {
  it("opens the mobile navigation as a modal dialog and returns focus on close", async () => {
    render(
      <AppShell activePath="/" title="Studio Dashboard" onNavigate={vi.fn()}>
        <div>Dashboard content</div>
      </AppShell>,
    );

    const trigger = screen.getByRole("button", { name: "Open navigation" });
    trigger.focus();
    fireEvent.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "Studio navigation" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => {
      expect(within(dialog).getByRole("button", { name: "Close navigation" })).toHaveFocus();
    });

    fireEvent.keyDown(window, { key: "Escape" });

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Studio navigation" })).not.toBeInTheDocument();
    });
    expect(trigger).toHaveFocus();
  });
});
