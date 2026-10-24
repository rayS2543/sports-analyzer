import { configure, fireEvent, render, screen, within } from "@testing-library/react";
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
let uploadedClips;
let reviewResponse;
const KEY = {
  verdict: "offside", margin_m: 0.35, uncertainty_m: 0.31, offside_line_x: 81.29, second_last_defender_track_id: 16,
  attacker_track_id: 10, frame_t: 13.2, attack_direction: "right", reasons: ["Judged at the detected pass (13.2 s)."],
};

beforeEach(() => {
  analysed = false;
  priorWindows = [];
  uploadedClips = [];
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
    if (url === `${API}/var/uploads`) return Promise.resolve({ data: { clips: uploadedClips } });
    if (url === `${API}/var/windows/90000000001`) return Promise.resolve({ data: { windows: [] } });
    if (url === `${API}/var/analysis/90000000001`) return Promise.resolve({ data: { status: "none", progress: null, error: null, result: null } });
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
  it("finds VAR offside reviews from commentary and opens the clip ESPN lists for one", { timeout: 20000 }, async () => {
    const user = userEvent.setup();
    const clip = { id: "49827977", title: "Carlos Espi's bicycle kick ruled out", duration_seconds: 58, source_url: SOURCE, page_url: null };
    const base = axios.get.getMockImplementation();
    axios.get.mockImplementation((url, config) =>
      url === `${API}/var/discover`
        ? Promise.resolve({ data: { reviews: [
            { event: "401882894", match: "Real Madrid at Real Betis", date: "2026-09-04", minute: "87'", player: "Carlos Espí", outcome: "goal ruled out", offside: true, clip },
            { event: "401882895", match: "Getafe at Sevilla", date: "2026-09-03", minute: "12'", player: "Mayoral", outcome: "goal ruled out", offside: true, clip: null, highlights: { ...clip, id: "77", title: "Getafe vs. Sevilla - Game Highlights" } },
            { event: "401882896", match: "Osasuna at Atletico Madrid", date: "2026-09-02", minute: "9'", player: "Griezmann", outcome: "goal ruled out", offside: true, clip: null, highlights: null },
          ] } })
        : base(url, config)
    );
    renderAt("/var?date=2026-09-10");
    await user.click(await screen.findByRole("button", { name: "Find VAR offside reviews" }));
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/discover`, { params: { league: "PD", from: "2026-08-28", to: "2026-09-10", kind: "offside" } });
    // No clip names the player: offer the match's short highlights, and for a match with neither, open the match.
    expect(await screen.findByRole("button", { name: /Open the match highlights for Getafe at Sevilla 12'/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Open the match Osasuna at Atletico Madrid/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Open the match Osasuna at Atletico Madrid/ }));
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/clips`, { params: { league: "PD", event: "401882896" } });
    await user.click(screen.getByRole("button", { name: /Open the clip for Real Madrid at Real Betis 87'/ }));
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/clips`, { params: { league: "PD", event: "401882894" } });
  });

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

  it("marks replay frames calibrated from the live camera with their speed and synced live time", async () => {
    // Shot 1 of the sample is uncalibrated; pretend crossview.py calibrated it as a x0.4 replay of shot 0.
    const shot0 = sample.frames.find((f) => f.shot === 0 && f.calibration.ok);
    const crossViewed = {
      ...sample,
      shots: sample.shots.map((s) => (s.id === 1 ? { ...s, calibrated_ratio: 1, usable: true, playback_speed: 0.4, replay_of: { clip: "46338651", window: "12.0-16.2", t_live_anchor: 13.0, t_replay_anchor: 15.0, speed: 0.4 } } : s)),
      frames: sample.frames.map((f) =>
        f.shot === 1
          ? { ...f, live_t: 13 + 0.4 * (f.t - 15), calibration: { ok: true, source: "cross_view", homography: shot0.calibration.homography, reprojection_error_m: 0.6, cross_view: { speed: 0.4 } } }
          : f,
      ),
    };
    analysed = true;
    const base = axios.get.getMockImplementation();
    axios.get.mockImplementation((url, opts) =>
      url === `${API}/var/analysis/46338651` ? Promise.resolve({ data: { status: "done", result: crossViewed } }) : base(url, opts),
    );
    renderAt(WINDOW_LINK);
    await screen.findByRole("article");
    fireEvent.change(screen.getByRole("slider", { name: "Clip time" }), { target: { value: "15" } });
    expect(await screen.findByText("Replay ×0.4 · synced to live 0:13.0")).toBeInTheDocument();
    expect(screen.getByText(/from the live camera/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider", { name: "Clip time" }), { target: { value: "13" } });
    expect(screen.queryByText(/synced to live/)).not.toBeInTheDocument();
  });

  it("shows the backend's message when analysis can't start", async () => {
    axios.post.mockRejectedValueOnce({ response: { status: 409, data: { error: "Another clip is being analysed. Try again when it finishes." } } });
    const user = userEvent.setup();
    renderAt(WINDOW_LINK);
    await user.click(await screen.findByRole("button", { name: "Analyze these seconds" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Another clip is being analysed");
  });
});

describe("VarPage goals to check", () => {
  it("lists goal clips found by ESPN headline and opens one", { timeout: 20000 }, async () => {
    const user = userEvent.setup();
    const base = axios.get.getMockImplementation();
    axios.get.mockImplementation((url, config) =>
      url === `${API}/var/discover`
        ? Promise.resolve({ data: { clips: [{ id: "55", title: "Pablo Durán gets on the scoresheet for Celta Vigo", duration_seconds: 61, source_url: SOURCE, page_url: null, event: "401001", match: "Real Sociedad at Celta Vigo", date: "2026-10-19", kind: "goal" }] } })
        : base(url, config)
    );
    renderAt("/var?date=2026-10-19");
    await user.click(await screen.findByRole("button", { name: "Find goals to check" }));
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/discover`, { params: { league: "PD", from: "2026-10-06", to: "2026-10-19", kind: "goal" } });
    await user.click(await screen.findByRole("button", { name: /Open the goal clip Pablo Durán/ }));
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/clips`, { params: { league: "PD", event: "401001" } });
  });
});

describe("VarPage uploads", () => {
  it("uploads an MP4, previews it from this computer and analyses it without a league or match", { timeout: 20000 }, async () => {
    const user = userEvent.setup();
    const clip = { id: "90000000001", title: "My corner", filename: "my corner.mp4", bytes: 88, uploaded_at: 1 };
    axios.post.mockImplementation((url) =>
      url === `${API}/var/upload`
        ? Promise.resolve({ status: 201, data: { clip } })
        : Promise.resolve({ status: 202, data: { clip: clip.id, status: "queued", window: "0.0-2.0" } })
    );
    const { container } = renderAt("/var");
    const file = new File(["x"], "my corner.mp4", { type: "video/mp4" });
    await user.upload(await screen.findByLabelText("Upload your own clip"), file);
    expect(axios.post).toHaveBeenCalledWith(`${API}/var/upload`, expect.any(FormData));

    expect(await screen.findByRole("heading", { name: "Find the moment" })).toBeInTheDocument();
    expect(container.querySelector("video")).toHaveAttribute("src", `${API}/var/video/${clip.id}`);
    await user.click(screen.getByRole("button", { name: "Analyze these seconds" }));
    expect(axios.post).toHaveBeenCalledWith(`${API}/var/analyze`, { clip: clip.id, start: 0, end: 2 });
  });

  it("lists clips uploaded earlier and reopens one", { timeout: 20000 }, async () => {
    const user = userEvent.setup();
    uploadedClips = [{ id: "90000000001", title: "My corner", filename: "a.mp4", bytes: 88, uploaded_at: 1 }];
    const { container } = renderAt("/var");
    await user.click(await screen.findByRole("button", { name: "Open your clip My corner" }));
    expect(await screen.findByRole("heading", { name: "Find the moment" })).toBeInTheDocument();
    expect(container.querySelector("video")).toHaveAttribute("src", `${API}/var/video/90000000001`);
  });
});

describe("VarPage clip by link", () => {
  it("gets an ESPN clip from a pasted link and analyses it without a match", { timeout: 20000 }, async () => {
    const user = userEvent.setup();
    const clip = { id: "44656413", title: "Mbappé is sent off", duration_seconds: 65, source_url: SOURCE, page_url: null };
    const base = axios.get.getMockImplementation();
    axios.get.mockImplementation((url, config) => {
      if (url === `${API}/var/clip`) return Promise.resolve({ data: { clip } });
      if (url === `${API}/var/windows/44656413`) return Promise.resolve({ data: { windows: [] } });
      if (url === `${API}/var/analysis/44656413`) return Promise.resolve({ data: { status: "none", progress: null, error: null, result: null } });
      return base(url, config);
    });
    axios.post.mockImplementation(() => Promise.resolve({ status: 202, data: { clip: clip.id, status: "queued", window: "0.0-2.0" } }));
    const { container } = renderAt("/var");
    await user.type(await screen.findByLabelText("ESPN video link or ID"), "https://www.espn.com/watch/syndicatedplayer/_/id/44656413");
    await user.click(screen.getByRole("button", { name: "Get clip" }));
    expect(axios.get).toHaveBeenCalledWith(`${API}/var/clip`, { params: { link: "https://www.espn.com/watch/syndicatedplayer/_/id/44656413" } });
    expect(await screen.findByRole("heading", { name: "Find the moment" })).toBeInTheDocument();
    expect(container.querySelector("video")).toHaveAttribute("src", SOURCE);
    await user.click(screen.getByRole("button", { name: "Analyze these seconds" }));
    expect(axios.post).toHaveBeenCalledWith(`${API}/var/analyze`, { clip: "44656413", start: 0, end: 2 });
  });

  it("says so when ESPN has no such video", { timeout: 20000 }, async () => {
    const user = userEvent.setup();
    const base = axios.get.getMockImplementation();
    axios.get.mockImplementation((url, config) =>
      url === `${API}/var/clip` ? Promise.reject({ response: { data: { error: "ESPN has no downloadable video with that ID" } } }) : base(url, config)
    );
    renderAt("/var");
    await user.type(await screen.findByLabelText("ESPN video link or ID"), "12345678");
    await user.click(screen.getByRole("button", { name: "Get clip" }));
    expect(await screen.findByText("ESPN has no downloadable video with that ID")).toBeInTheDocument();
  });
});

describe("VarPage drag and drop", () => {
  it("uploads an MP4 dropped on the picker", { timeout: 20000 }, async () => {
    const clip = { id: "90000000001", title: "Dropped", filename: "d.mp4", bytes: 1, uploaded_at: 1 };
    axios.post.mockImplementation(() => Promise.resolve({ status: 201, data: { clip } }));
    renderAt("/var");
    const zone = await screen.findByTestId("drop-zone");
    fireEvent.drop(zone, { dataTransfer: { files: [new File(["x"], "d.mp4", { type: "video/mp4" })] } });
    expect(await screen.findByRole("heading", { name: "Find the moment" })).toBeInTheDocument();
    expect(axios.post).toHaveBeenCalledWith(`${API}/var/upload`, expect.any(FormData));
  });
});
