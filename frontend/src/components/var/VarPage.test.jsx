import { configure, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import sample from "./fixtures/sampleAnalysis.json";
import VarPage from "./VarPage";
import { API_BASE } from "../../apiBase";

vi.mock("axios");
// WebGL doesn't exist in jsdom; the scene is covered by its pure helpers instead.
vi.mock("./PitchScene", () => ({
  default: ({ frame, preset }) => (
    <div data-testid="pitch-scene" data-preset={preset}>
      {frame ? `${frame.players.length} tracked at ${frame.t}` : "empty"}
    </div>
  ),
}));
// Canvas isn't implemented in jsdom; the overlay's geometry is tested in projection.test.js.
vi.mock("./VideoOverlay", () => ({
  default: ({ overlay }) => <div data-testid="video-overlay">{overlay ? overlay.label : "no lines"}</div>,
}));

// The walkthrough chains several async steps; give slow CI machines headroom.
configure({ asyncUtilTimeout: 4000 });

const API = API_BASE;
const SOURCE = "https://espnmedia-cdn.akamaized.net/espn/media/16x9/wsc/2025/0921/clip.mp4";
let analysed;
let priorWindows;
let reviewResponse;
const KEY = {
  verdict: "offside", margin_m: 0.35, uncertainty_m: 0.31, offside_line_x: 81.29, second_last_defender_track_id: 16,
  attacker_track_id: 10, frame_t: 13.2, attack_direction: "right", reasons: ["Judged at the detected pass (13.2 s)."],
};

beforeEach(() => {
  analysed = false;
  priorWindows = [];
  reviewResponse = {
    reviews: [
      {
        event: sample.events[0],
        key: KEY,
        candidates: [
          { track_id: 10, verdict: "offside", margin_m: 0.35 },
          { track_id: 9, verdict: "onside", margin_m: -6.1 },
        ],
      },
    ],
    message: null,
  };
  axios.get.mockImplementation((url) => {
    if (url === `${API}/var/fixtures`)
      return Promise.resolve({ data: { fixtures: [{ id: "748191", home: "Barcelona", away: "Getafe", date: "2025-09-21T19:00Z" }] } });
    if (url === `${API}/var/clips`)
      return Promise.resolve({
        data: {
          clips: [
            {
              id: "46338651",
              title: "Barcelona vs. Getafe - Game Highlights",
              duration_seconds: 74,
              source_url: SOURCE,
              page_url: "https://www.espn.com/video/clip?id=46338651",
            },
          ],
        },
      });
    if (url === `${API}/var/windows/46338651`) return Promise.resolve({ data: { windows: priorWindows } });
    if (url === `${API}/var/analysis/46338651`)
      return Promise.resolve({ data: analysed ? { status: "done", result: sample } : { status: "none", progress: null, error: null, result: null } });
    if (url === `${API}/var/official`)
      return Promise.resolve({ data: { events: [{ type: "offside", clock: "6'", team: "Getafe", text: "Mayoral is caught offside." }] } });
    return Promise.reject(new Error(`unexpected ${url}`));
  });
  axios.post.mockImplementation((url, body) => {
    if (url === `${API}/var/review`) return Promise.resolve({ data: reviewResponse });
    if (url === `${API}/var/assess`)
      return Promise.resolve({
        data: { verdict: "offside", margin_m: 1.4, uncertainty_m: 0.4, offside_line_x: 81.4, second_last_defender_track_id: 16, attacker_track_id: body.attacker_track_id, frame_t: body.t, attack_direction: "right", reasons: ["Judged at the frame you picked."] },
      });
    analysed = true;
    return Promise.resolve({ status: 202, data: { clip: "46338651", status: "queued", window: "0.0-2.0" } });
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

const renderAt = (path) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <VarPage />
    </MemoryRouter>
  );

const WINDOW_LINK = "/var?league=PD&event=748191&clip=46338651&start=12.0&end=16.2";

describe("VarPage", () => {
  it("walks fixture → clip → ESPN preview → analyze these seconds → viewer", { timeout: 20000 }, async () => {
    const user = userEvent.setup();
    const { container } = renderAt("/var");

    await user.click(await screen.findByRole("button", { name: /Barcelona vs Getafe/ }));
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/fixtures`, { params: { league: "PD", date: "2025-09-21" } });
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/clips`, { params: { league: "PD", event: "748191" } });

    await user.click(await screen.findByRole("button", { name: /Game Highlights/ }));

    // Preview streams straight from ESPN; nothing is analysed yet.
    expect(await screen.findByRole("heading", { name: "Find the moment" })).toBeInTheDocument();
    expect(container.querySelector("video")).toHaveAttribute("src", SOURCE);
    expect(axios.post).not.toHaveBeenCalled();

    // Paused at 0:00 the window is [0, 2]: 3 s before is clamped to the clip start.
    await user.click(screen.getByRole("button", { name: "Analyze these seconds" }));
    expect(axios.post).toHaveBeenCalledWith(`${API}/var/analyze`, { league: "PD", event: "748191", clip: "46338651", start: 0, end: 2 });
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/analysis/46338651`, { params: { start: 0, end: 2 } });

    // Viewer: 3D scene, honesty label, and the official record kept separate from the system assessment.
    expect(await screen.findByTestId("pitch-scene")).toBeInTheDocument();
    expect(screen.getByText(/bodies are assumed geometry/)).toBeInTheDocument();
    const official = screen.getByRole("heading", { name: "Official record (ESPN)" }).closest("section");
    expect(await within(official).findByText("Mayoral is caught offside.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "System assessment" }).closest("section")).not.toBe(official);
  });

  it("reviews the detected pass in one click: jumps there, preselects the key attacker, draws the lines", { timeout: 20000 }, async () => {
    analysed = true;
    const user = userEvent.setup();
    renderAt(WINDOW_LINK);
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/analysis/46338651`, { params: { start: 12, end: 16.2 } });
    expect(await screen.findByRole("article")).toHaveAttribute("data-verdict", "offside");
    expect(axios.post).toHaveBeenCalledWith(`${API}/var/review`, { clip: "46338651", start: 12, end: 16.2 });

    // Parked on the pass frame, camera behind the line, line drawn on the video.
    expect(screen.getByTestId("pitch-scene")).toHaveTextContent("at 13.2");
    expect(screen.getByTestId("pitch-scene")).toHaveAttribute("data-preset", "line");
    expect(screen.getByTestId("video-overlay")).toHaveTextContent("OFFSIDE");
    expect(screen.getByRole("button", { name: "Pass at 0:13.2, Team A" })).toBeInTheDocument();

    // Flip to another attacker at the same pass: assessed on the same frame, with the window and direction.
    await user.click(screen.getByRole("button", { name: /109/ }));
    expect(axios.post).toHaveBeenCalledWith(`${API}/var/assess`, {
      clip: "46338651", start: 12, end: 16.2, t: 13.2, attacker_track_id: 9, attacking_team: "A", attack_direction: "right",
    });
  });

  it("keeps the manual check for a different player, sending the window", { timeout: 20000 }, async () => {
    analysed = true;
    const user = userEvent.setup();
    renderAt(WINDOW_LINK);
    await screen.findByRole("article");
    await user.click(screen.getByRole("button", { name: "Check a different moment or player" }));
    await user.click(screen.getByRole("button", { name: "Player #9, Team A" }));
    await user.click(screen.getByRole("button", { name: "Check offside" }));
    expect(axios.post).toHaveBeenLastCalledWith(`${API}/var/assess`, {
      clip: "46338651", start: 12, end: 16.2, t: 13.2, attacker_track_id: 10, attacking_team: "A",
    });
  });

  it("falls back to the manual check when no pass was detected", async () => {
    analysed = true;
    reviewResponse = { reviews: [], message: "No pass events were detected in this window." };
    renderAt(WINDOW_LINK);
    expect(await screen.findByRole("tab", { name: "Manual check", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check offside" })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("tab", { name: "Automatic review" }));
    expect(screen.getByText("No pass events were detected in this window.")).toBeInTheDocument();
  });

  it("lists earlier windows as chips that open straight into the review", async () => {
    analysed = true;
    priorWindows = [{ start: 12.0, end: 16.2, key: "12.0-16.2", status: "done" }];
    const user = userEvent.setup();
    renderAt("/var?league=PD&event=748191&clip=46338651");
    await user.click(await screen.findByRole("button", { name: /0:12\.0–0:16\.2/ }));
    expect(await screen.findByTestId("pitch-scene")).toBeInTheDocument();
    expect(axios.post).not.toHaveBeenCalledWith(`${API}/var/analyze`, expect.anything());
  });

  it("shows the backend's message when analysis can't start", async () => {
    axios.post.mockRejectedValueOnce({ response: { status: 409, data: { error: "Another clip is being analysed. Try again when it finishes." } } });
    const user = userEvent.setup();
    renderAt(WINDOW_LINK);
    await user.click(await screen.findByRole("button", { name: "Analyze these seconds" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Another clip is being analysed");
  });
});
