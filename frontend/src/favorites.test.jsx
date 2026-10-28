import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import FollowButton from "./components/FollowButton";
import { FavoritesProvider } from "./favorites";

const STORAGE_KEY = "sa-favorites";

function renderButtons() {
  return render(
    <FavoritesProvider>
      <div data-testid="pd">
        <FollowButton league="PD" name="Valencia CF" />
      </div>
      <div data-testid="pl">
        <FollowButton league="PL" name="Valencia CF" />
      </div>
    </FavoritesProvider>
  );
}

function button(league) {
  return within(screen.getByTestId(league)).getByRole("button");
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

it("remembers a follow across a remount and drops it on the second click", () => {
  const { unmount } = render(
    <FavoritesProvider>
      <FollowButton league="PD" name="FC Barcelona" />
    </FavoritesProvider>
  );

  fireEvent.click(screen.getByRole("button", { name: "Follow" }));
  expect(screen.getByRole("button", { name: "Following" })).toHaveAttribute("aria-pressed", "true");
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY))).toEqual([{ league: "PD", name: "FC Barcelona" }]);

  unmount();
  render(
    <FavoritesProvider>
      <FollowButton league="PD" name="FC Barcelona" />
    </FavoritesProvider>
  );
  expect(screen.getByRole("button", { name: "Following" })).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Following" }));
  expect(screen.getByRole("button", { name: "Follow" })).toHaveAttribute("aria-pressed", "false");
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY))).toEqual([]);
});

it("keeps the same club name in two leagues as two follows", () => {
  renderButtons();

  fireEvent.click(button("pd"));
  fireEvent.click(button("pl"));

  expect(button("pd")).toHaveAttribute("aria-pressed", "true");
  expect(button("pl")).toHaveAttribute("aria-pressed", "true");
  expect(JSON.parse(localStorage.getItem(STORAGE_KEY))).toEqual([
    { league: "PD", name: "Valencia CF" },
    { league: "PL", name: "Valencia CF" },
  ]);

  fireEvent.click(button("pd"));
  expect(button("pd")).toHaveAttribute("aria-pressed", "false");
  expect(button("pl")).toHaveAttribute("aria-pressed", "true");
});

it("ignores corrupt stored favorites and still follows when storage throws", () => {
  localStorage.setItem(STORAGE_KEY, "{");
  const broken = render(
    <FavoritesProvider>
      <FollowButton league="PD" name="Sevilla FC" />
    </FavoritesProvider>
  );
  expect(screen.getByRole("button", { name: "Follow" })).toBeInTheDocument();
  broken.unmount();

  localStorage.setItem(STORAGE_KEY, JSON.stringify({ league: "PD", name: "Sevilla FC" }));
  const objectValue = render(
    <FavoritesProvider>
      <FollowButton league="PD" name="Sevilla FC" />
    </FavoritesProvider>
  );
  expect(screen.getByRole("button", { name: "Follow" })).toBeInTheDocument();
  objectValue.unmount();

  localStorage.clear();
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = () => {
    throw new Error("quota");
  };
  try {
    render(
      <FavoritesProvider>
        <FollowButton league="PD" name="Sevilla FC" />
      </FavoritesProvider>
    );
    fireEvent.click(screen.getByRole("button", { name: "Follow" }));
    expect(screen.getByRole("button", { name: "Following" })).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  } finally {
    Storage.prototype.setItem = original;
  }
});
