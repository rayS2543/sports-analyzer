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
  axios.get.mockImplementation(() => Promise.resolve({ data: responses.length > 1 ? responses.shift() : responses[0] }));
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

  it("offers a retry after a failed run", async () => {
    responses = [{ status: "failed", error: "Foul review exited with code 1" }];
    render(<FoulReview clip="1" start={0} end={5} />);
    expect(await screen.findByText(/Foul review exited with code 1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
