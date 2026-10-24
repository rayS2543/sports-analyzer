import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import ChecksPage from "./ChecksPage";
import { API_BASE } from "../../apiBase";

vi.mock("axios");

const pass = (t, verdict, margin, flags = []) => ({ t, verdict, margin_m: margin, uncertainty_m: 0.7, attacker_track_id: 7, restart: null, reasons: [], flags });
const clip = (id, title, date) => ({ id, title, match: "Rayo Vallecano at Getafe", date, duration_seconds: 60, event: "1" });
const CHECKS = [
  { clip: clip("1", "Álvaro García scores in the 11'", "2026-10-19"), status: "read", flagged: false,
    windows: [{ key: "0.0-10.0", calibrated_frames: [84, 100], players_per_frame: 10, flags: [], passes: [pass(8.7, "onside", -2.7)] }] },
  { clip: clip("2", "Hugo Novoa scores in the 87'", "2026-10-18"), status: "read", flagged: true,
    windows: [{ key: "0.0-10.0", calibrated_frames: [98, 100], players_per_frame: 13, flags: [], passes: [pass(4.6, "offside", 4.0, ["a margin of 4.0 m is unusually large"])] }] },
  { clip: clip("3", "A clip that never fitted the pitch", "2026-10-17"), status: "uncalibrated", flagged: true,
    windows: [{ key: "0.0-10.0", calibrated_frames: [0, 80], players_per_frame: 0, flags: ["the pitch could not be fitted in most frames, so positions here are not usable"], passes: [] }] },
];

const renderPage = () =>
  render(
    <MemoryRouter>
      <ChecksPage />
    </MemoryRouter>
  );

afterEach(() => vi.clearAllMocks());

describe("ChecksPage", () => {
  it("lists every swept clip with what the pipeline had and what it read at each pass", async () => {
    axios.get.mockResolvedValue({ data: { checks: CHECKS, sweep: { running: false } } });
    renderPage();
    const first = (await screen.findByText("Álvaro García scores in the 11'")).closest("li");
    expect(within(first).getByText("Read")).toBeInTheDocument();
    expect(within(first).getByText(/pitch fitted in 84 of 100 frames/)).toBeInTheDocument();
    expect(within(first).getByText(/onside, behind the line by 2.7 m/)).toBeInTheDocument();
    expect(within(first).getByRole("link", { name: /Open Álvaro García scores in the 11' in the viewer/ })).toHaveAttribute("href", "/var?clip=1&start=0.0&end=10.0");
    expect(screen.getByText("Pitch not fitted")).toBeInTheDocument();
  });

  it("says why a reading needs a human look, and can show only those", async () => {
    const user = userEvent.setup();
    axios.get.mockResolvedValue({ data: { checks: CHECKS, sweep: { running: false } } });
    renderPage();
    expect(await screen.findByText(/a margin of 4.0 m is unusually large/)).toBeInTheDocument();
    await user.click(screen.getByLabelText("Only the ones to look at"));
    expect(screen.queryByText("Álvaro García scores in the 11'")).not.toBeInTheDocument();
    expect(screen.getByText("Hugo Novoa scores in the 87'")).toBeInTheDocument();
  });

  it("starts a sweep and shows its progress", async () => {
    const user = userEvent.setup();
    let started = false;
    axios.get.mockImplementation(() =>
      Promise.resolve({ data: { checks: [], sweep: started ? { running: true, done: 2, total: 12, current: "Rayo Vallecano at Getafe: a goal" } : { running: false } } })
    );
    axios.post.mockImplementation(() => {
      started = true;
      return Promise.resolve({ status: 202, data: { status: "started" } });
    });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Check recent goals" }));
    expect(axios.post).toHaveBeenCalledWith(`${API_BASE}/var/sweep`, { league: "PD", days: 14, limit: 12 });
    expect(await screen.findByRole("status")).toHaveTextContent("2 of 12 clips done");
    expect(screen.getByRole("button", { name: "Checking…" })).toBeDisabled();
  });

  it("shows the server's reason when a sweep cannot start", async () => {
    const user = userEvent.setup();
    axios.get.mockResolvedValue({ data: { checks: [], sweep: { running: false } } });
    axios.post.mockRejectedValue({ response: { data: { error: "Clip 1 window 0.0-10.0 is being analysed; try again when it finishes" } } });
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Check recent goals" }));
    expect(await screen.findByText(/is being analysed; try again/)).toBeInTheDocument();
  });

  it("explains how to get results when nothing has been checked yet", async () => {
    axios.get.mockResolvedValue({ data: { checks: [], sweep: { running: false } } });
    renderPage();
    expect(await screen.findByText(/No clips checked yet/)).toBeInTheDocument();
  });
});
