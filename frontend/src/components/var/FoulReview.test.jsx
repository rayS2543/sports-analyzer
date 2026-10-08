import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import axios from "axios";
import FoulReview from "./FoulReview";
import { API_BASE } from "../../apiBase";

vi.mock("axios");

const ind = (label, value, confidence, extra = {}) => ({ label, value, confidence, observable: value !== null, detail: `${label} detail`, ...extra });

const INCIDENT = {
  id: 0,
  t: 3.203,
  sanction: "red",
  sanction_note: "At least one sending-off ground is met by the measurements.",
  players: { challenger: { track_id: 4, team: "A" }, victim: { track_id: 9, team: "B", jersey_number: 8 } },
  notes: ["Challenger chosen because its right foot is the striking point closest to the other player's body."],
  grounds: [
    {
      ground: "serious_foul_play",
      label: "Serious foul play",
      verdict: "red",
      reasons: ["Contact in a challenge that endangers the opponent's safety: studs/sole led into the opponent above the ankle."],
      indicators: [
        { key: "contact", ...ind("Contact", true, 0.82) },
        { key: "studs_showing", ...ind("Studs / sole towards the opponent", true, 0.71) },
        { key: "challenger_speed", ...ind("Challenger speed at contact", null, 0), observable: false },
      ],
    },
    { ground: "violent_conduct", label: "Violent conduct", verdict: "not_red", reasons: ["No hand or arm reached the head."], indicators: [] },
    {
      ground: "dogso",
      label: "Denying an obvious goal-scoring opportunity",
      verdict: "inconclusive",
      reasons: ["Distance to goal: not observable."],
      indicators: [],
    },
  ],
};
const DONE = { status: "done", incidents: [INCIDENT, { ...INCIDENT, id: 1, t: 5.1, sanction: "none", sanction_note: "None met." }], message: null, assumptions: ["One camera."] };

let responses;
beforeEach(() => {
  vi.resetAllMocks();
  responses = [];
  axios.get.mockImplementation((url) =>
    url.endsWith("/crossview")
      ? Promise.resolve({ data: { status: "none" } })
      : Promise.resolve({ data: responses.length > 1 ? responses.shift() : responses[0] }),
  );
});

describe("FoulReview", () => {
  it("starts a review, shows progress while polling, then lists incidents", async () => {
    responses = [{ status: "none", incidents: null }];
    axios.post.mockResolvedValue({ data: { status: "queued" } });
    render(<FoulReview clip="44656413" start={1} end={7} time={0} onSeek={() => {}} pollMs={5} />);
    expect(axios.get).toHaveBeenCalledWith(`${API_BASE}/var/fouls/44656413`, { params: { start: 1, end: 7 } });

    // "running" stays the answer until asserted, so a loaded machine can't race past it.
    responses = [{ status: "running", progress: { progress: 0.4, message: "pose around candidate 2/4" } }];
    await userEvent.click(await screen.findByRole("button", { name: "Review challenges" }));
    expect(axios.post).toHaveBeenCalledWith(`${API_BASE}/var/fouls`, { clip: "44656413", start: 1, end: 7 });
    expect(await screen.findByText("pose around candidate 2/4")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    responses = [DONE];
    expect(await screen.findByRole("list", { name: "Examined challenges" }, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText("Red card")).toBeInTheDocument();
    expect(screen.getByText("No red-card ground")).toBeInTheDocument();
  });

  it("seeks to the contact frame and shows per-ground verdicts with confidence", async () => {
    responses = [DONE];
    const onSeek = vi.fn();
    render(<FoulReview clip="44656413" start={1} end={7} time={3.2} onSeek={onSeek} />);
    const row = await screen.findByRole("button", { name: /0:03\.2/ });
    expect(row).toHaveTextContent("Team A track 4 on Team B #8");
    await userEvent.click(row);
    expect(onSeek).toHaveBeenCalledWith(3.203);
    expect(row).toHaveAttribute("aria-expanded", "true");

    const sfp = screen.getByRole("article", { name: "Serious foul play" });
    expect(sfp).toHaveAttribute("data-verdict", "red");
    expect(within(sfp).getByText("Red")).toHaveClass("text-loss");
    expect(within(sfp).getByText("82%")).toBeInTheDocument();
    expect(within(sfp).getByRole("meter", { name: "Contact confidence" })).toHaveAttribute("aria-valuenow", "82");
    expect(within(sfp).getByText("Not observable")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Violent conduct" })).toHaveAttribute("data-verdict", "not_red");
    const dogso = screen.getByRole("article", { name: "Denying an obvious goal-scoring opportunity" });
    expect(within(dogso).getByText("Inconclusive")).toHaveClass("text-accent");
    expect(screen.getByText(/without looking at the official decision/)).toBeInTheDocument();
  });

  it("shows the downgrade to a caution", async () => {
    const yellow = {
      ...INCIDENT,
      sanction: "yellow",
      grounds: [{ ...INCIDENT.grounds[2], verdict: "not_red", downgraded_to: "yellow" }],
    };
    responses = [{ ...DONE, incidents: [yellow] }];
    render(<FoulReview clip="1" start={0} end={5} />);
    await userEvent.click(await screen.findByRole("button", { name: /Yellow card/ }));
    expect(screen.getByText("Downgraded to a caution (penalty area)")).toBeInTheDocument();
  });

  it("explains an empty window and reports failures", async () => {
    responses = [{ status: "done", incidents: [], message: "No opposing players came close enough." }];
    const { unmount } = render(<FoulReview clip="1" start={0} end={5} />);
    expect(await screen.findByText("No opposing players came close enough.")).toBeInTheDocument();
    unmount();

    responses = [{ status: "none" }];
    axios.post.mockRejectedValueOnce({ response: { status: 409, data: { error: "Analyse this window first." } } });
    render(<FoulReview clip="1" start={0} end={5} />);
    await userEvent.click(await screen.findByRole("button", { name: "Review challenges" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Analyse this window first.");
  });

  it("combines the incident with the same challenge seen from another reviewed window", async () => {
    const replay = { ...INCIDENT, id: 3, t: 23.22 };
    axios.get.mockImplementation((url, opts) => {
      if (url.endsWith("/crossview")) return Promise.resolve({ data: { status: "none" } });
      if (url === `${API_BASE}/var/windows/44656413`)
        return Promise.resolve({ data: { windows: [{ start: 1, end: 7, key: "1.0-7.0", status: "done" }, { start: 23, end: 28, key: "23.0-28.0", status: "done" }] } });
      return Promise.resolve({ data: opts.params.start === 23 ? { status: "done", incidents: [replay] } : DONE });
    });
    const combined = { ...INCIDENT, angles: [{ angle: "1.0-7.0", t: 3.203 }, { angle: "23.0-28.0", t: 23.22 }] };
    axios.post.mockResolvedValue({ data: combined });
    render(<FoulReview clip="44656413" start={1} end={7} />);
    await userEvent.click(await screen.findByRole("button", { name: /0:03\.2/ }));
    const select = await screen.findByRole("combobox", { name: /Same incident from another angle/ });
    await userEvent.selectOptions(select, "23.0-28.0|3");
    expect(axios.post).toHaveBeenCalledWith(`${API_BASE}/var/fouls/44656413/combine`, {
      parts: [
        { start: 1, end: 7, id: 0 },
        { start: 23, end: 28, id: 3 },
      ],
    });
    const out = await screen.findByRole("region", { name: "Combined angles" });
    expect(within(out).getByText(/Combined from 1\.0-7\.0/)).toBeInTheDocument();
    expect(within(out).getByRole("article", { name: "Serious foul play" })).toHaveAttribute("data-verdict", "red");
  });

  it("calibrates an uncalibrated replay from the live camera, then re-combines the re-reviewed pair", async () => {
    const live = { ...INCIDENT, id: 3, t: 3.27 };
    let phase = "before";
    const replayIncident = () => ({ ...INCIDENT, id: phase === "after" ? 5 : 0, t: 23.223 }); // the re-run renumbers
    const report = { status: "done", speed: 0.4, live: { clip: "44656413", window: "1.0-7.0", shot: 0 }, calibrated_frames: 30, frames: 42 };
    axios.get.mockImplementation((url, opts) => {
      if (url === `${API_BASE}/var/analysis/44656413/crossview`) {
        if (opts.params.start === 1) return Promise.resolve({ data: { status: "none" } });
        if (phase === "running") return Promise.resolve({ data: { status: "running", progress: { progress: 0.5, message: "solving the replay camera" } } });
        return Promise.resolve({ data: { status: "done", report } });
      }
      if (url === `${API_BASE}/var/windows/44656413`)
        return Promise.resolve({ data: { windows: [{ start: 1, end: 7, key: "1.0-7.0", status: "done" }, { start: 23, end: 28, key: "23.0-28.0", status: "done" }] } });
      return Promise.resolve({ data: opts.params.start === 23 ? { status: "done", incidents: [replayIncident()] } : { ...DONE, incidents: [live] } });
    });
    const request = { clip: "44656413", start: 23, end: 28, live: { clip: "44656413", start: 1, end: 7 }, anchor: [3.27, 23.223] };
    const combined = { ...INCIDENT, angles: [{ angle: "1.0-7.0", t: 3.27 }, { angle: "23.0-28.0", t: 23.223 }] };
    axios.post.mockImplementation((url) => {
      if (url.endsWith("/crossview")) {
        phase = "running";
        return Promise.resolve({ data: { status: "queued" } });
      }
      return Promise.resolve({ data: phase === "before" ? { ...combined, crossview_available: true, crossview_request: request } : { ...combined, crossview_available: false } });
    });
    const onRecalibrated = vi.fn();
    render(<FoulReview clip="44656413" start={1} end={7} pollMs={5} onRecalibrated={onRecalibrated} />);
    await userEvent.click(await screen.findByRole("button", { name: /0:03\.3/ }));
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: /Same incident from another angle/ }), "23.0-28.0|0");
    const calibrate = await screen.findByRole("button", { name: "Calibrate this replay from the live camera" });
    expect(screen.getByText(/synced on these two contacts \(0:03\.3 live, 0:23\.2 replay\)/)).toBeInTheDocument();

    await userEvent.click(calibrate);
    expect(axios.post).toHaveBeenCalledWith(`${API_BASE}/var/analysis/44656413/crossview`, {
      start: 23, end: 28, live: { clip: "44656413", start: 1, end: 7 }, anchor: [3.27, 23.223],
    });
    expect(await screen.findByText(/solving the replay camera/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Cross-view calibration progress" })).toHaveAttribute("aria-valuenow", "50");

    phase = "after";
    expect(await screen.findByText(/Positions in the replay 0:23\.0–0:28\.0 are inferred from the live camera \(0:01\.0–0:07\.0\), synced ×0\.4 · 30\/42 frames calibrated/)).toBeInTheDocument();
    // Re-combined with the re-reviewed replay challenge, found by its time (its id changed from 0 to 5).
    await vi.waitFor(() =>
      expect(axios.post).toHaveBeenLastCalledWith(`${API_BASE}/var/fouls/44656413/combine`, {
        parts: [
          { start: 1, end: 7, id: 3 },
          { start: 23, end: 28, id: 5 },
        ],
      }),
    );
    expect(await screen.findByRole("region", { name: "Combined angles" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Calibrate this replay from the live camera" })).not.toBeInTheDocument();
    expect(onRecalibrated).not.toHaveBeenCalled(); // the live window's own analysis did not change
  });

  it("puts the pairs matched by the cross-view sync first and says where replay positions come from", async () => {
    const replay = { ...INCIDENT, id: 0, t: 23.223 };
    const pair = { live: { clip: "44656413", start: 1, end: 7, id: 3, t: 3.27 }, replay: { clip: "44656413", start: 23, end: 28, id: 0, t: 23.223 }, dt_s: 0.004 };
    axios.get.mockImplementation((url, opts) => {
      if (url.endsWith("/crossview"))
        return Promise.resolve({ data: { status: "done", report: { status: "done", speed: 0.4, live: { window: "1.0-7.0" } } } });
      if (url === `${API_BASE}/var/windows/44656413`)
        return Promise.resolve({ data: { windows: [{ start: 1, end: 7, key: "1.0-7.0", status: "done" }, { start: 23, end: 28, key: "23.0-28.0", status: "done" }] } });
      if (opts.params.start === 23) return Promise.resolve({ data: { status: "done", incidents: [replay], suggested_pairs: [pair] } });
      return Promise.resolve({ data: { ...DONE, incidents: [{ ...INCIDENT, id: 2, t: 3.136 }, { ...INCIDENT, id: 3, t: 3.27 }] } });
    });
    render(<FoulReview clip="44656413" start={23} end={28} />);
    expect(await screen.findByText(/Positions in this replay are inferred from the live camera \(0:01\.0–0:07\.0\), synced ×0\.4/)).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /0:23\.2/ }));
    const select = await screen.findByRole("combobox", { name: /Same incident from another angle/ });
    const groups = within(select).getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("label"))).toEqual(["Matched by the cross-view sync", "Other reviewed challenges"]);
    expect(within(groups[0]).getByRole("option")).toHaveTextContent(/0:03\.3 · .* · synced, 0\.00 s apart/);
    expect(within(groups[1]).getByRole("option")).toHaveTextContent("0:03.1");
  });

  it("still offers an unanchored calibration when the chosen pair is refused", async () => {
    axios.get.mockImplementation((url, opts) => {
      if (url.endsWith("/crossview")) return Promise.resolve({ data: { status: "none" } });
      if (url === `${API_BASE}/var/windows/44656413`)
        return Promise.resolve({ data: { windows: [{ start: 1, end: 7, key: "1.0-7.0", status: "done" }, { start: 23, end: 28, key: "23.0-28.0", status: "done" }] } });
      return Promise.resolve({ data: opts.params.start === 23 ? { status: "done", incidents: [{ ...INCIDENT, id: 1, t: 23.223 }] } : DONE });
    });
    const request = { clip: "44656413", start: 23, end: 28, live: { clip: "44656413", start: 1, end: 7 } };
    axios.post.mockImplementation((url) =>
      url.endsWith("/combine")
        ? Promise.reject({ response: { status: 409, data: { error: "Challengers from different teams.", crossview_available: true, crossview_request: request } } })
        : Promise.resolve({ data: { status: "queued" } }),
    );
    render(<FoulReview clip="44656413" start={1} end={7} />);
    await userEvent.click(await screen.findByRole("button", { name: /0:03\.2/ }));
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: /Same incident from another angle/ }), "23.0-28.0|1");
    expect(await screen.findByRole("alert")).toHaveTextContent("Challengers from different teams.");
    expect(screen.getByText(/synced automatically on contacts both reviews found \(not on this pair\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Calibrate this replay from the live camera" }));
    expect(axios.post).toHaveBeenLastCalledWith(`${API_BASE}/var/analysis/44656413/crossview`, {
      start: 23, end: 28, live: { clip: "44656413", start: 1, end: 7 }, anchor: undefined,
    });
  });

  it("reports an honest cross-view failure", async () => {
    axios.get.mockImplementation((url) =>
      Promise.resolve({ data: url.endsWith("/crossview") ? { status: "failed", error: "sync ambiguous", report: { status: "failed" } } : DONE }),
    );
    render(<FoulReview clip="44656413" start={23} end={28} />);
    expect(await screen.findByText(/Couldn.t calibrate this replay from the live camera: sync ambiguous\. Its positions stay unmeasured/)).toBeInTheDocument();
  });

  it("offers a retry after a failed run", async () => {
    responses = [{ status: "failed", error: "Foul review exited with code 1" }];
    render(<FoulReview clip="1" start={0} end={5} />);
    expect(await screen.findByText(/Foul review exited with code 1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
