import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({
  findVideosAction: vi.fn(),
  cancelVideoSearchAction: vi.fn(),
  retryVideoSearchAction: vi.fn(),
}));
vi.mock("@/lib/videos/actions", () => actions);
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { TopicVideos } from "@/components/videos/topic-videos";
import type { TopicVideos as TopicVideosData } from "@/lib/api/server";
import { GOAL, ITEM } from "@/test-support/lessons";
import { search, topicVideos, video, videoJob } from "@/test-support/videos";

beforeEach(() => {
  vi.clearAllMocks();
});

function show(data: TopicVideosData) {
  return render(<TopicVideos goalId={GOAL} itemId={ITEM} data={data} timeZone="Asia/Kolkata" />);
}

describe("TopicVideos", () => {
  it("says plainly where the videos come from", () => {
    show(topicVideos());

    expect(screen.getByRole("heading", { name: "Videos on this topic" })).toBeInTheDocument();
    expect(
      screen.getByText(/didn.t make these videos and hasn.t reviewed them/),
    ).toBeInTheDocument();
  });

  it("offers a first search when there is none", () => {
    show(topicVideos());

    expect(screen.getByRole("button", { name: "Find videos" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Find other videos" })).not.toBeInTheDocument();
  });

  it("says when the server cannot search, and offers nothing", () => {
    show(topicVideos({ configured: false, can_search: false }));

    expect(screen.getByText(/aren.t set up on this server yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a running search with its progress and a way to stop it", () => {
    show(topicVideos({ job: videoJob() }));

    expect(screen.getByText("Finding videos on YouTube")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Find videos" })).not.toBeInTheDocument();
  });

  it("shows a failed search with its learner-safe reason and a retry", () => {
    show(
      topicVideos({
        job: videoJob({
          status: "failed",
          error_message: "Video suggestions have reached today's limit on this server.",
        }),
      }),
    );

    expect(screen.getByText("We couldn’t find videos")).toBeInTheDocument();
    expect(screen.getByText(/reached today's limit/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("lists videos as links to YouTube that open in a new tab, with length and language", () => {
    show(topicVideos({ search: search(), videos: [video()] }));

    const list = screen.getByRole("list", { name: "Suggested videos" });
    const link = within(list).getByRole("link", { name: /Ownership in Rust, explained/ });
    expect(link).toHaveAttribute("href", "https://www.youtube.com/watch?v=dQw4w9WgXcQ");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAccessibleName(/opens YouTube in a new tab/);
    expect(within(list).getByText("12:30")).toBeInTheDocument();
    expect(within(list).getByText("Rust Teacher · 1.3M views")).toBeInTheDocument();
    expect(within(list).getByText("Strong match")).toBeInTheDocument();
    expect(within(list).getByText("English")).toBeInTheDocument();
    expect(
      screen.getByText(/Searched YouTube for “Ownership and borrowing rust”/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Find other videos" })).toBeInTheDocument();
  });

  it("builds every link from the video id, never from the stored address", () => {
    show(
      topicVideos({
        search: search(),
        videos: [
          video({ url: "https://evil.example/phish" }),
          video({ id: "88888888-8888-4888-8888-888888888888", video_id: "bad id!" }),
        ],
      }),
    );

    const links = within(screen.getByRole("list", { name: "Suggested videos" })).getAllByRole(
      "link",
    );
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://www.youtube.com/watch?v=dQw4w9WgXcQ");
  });

  it("shows a thumbnail only from YouTube's image host", () => {
    const { container } = show(
      topicVideos({
        search: search(),
        videos: [video({ thumbnail_url: "https://tracker.example/pixel.gif" })],
      }),
    );

    expect(container.querySelector("img")).toBeNull();
  });

  it("renders titles as text, never as markup", () => {
    const hostile = '<img src=x onerror="alert(1)">';
    const { container } = show(
      topicVideos({ search: search(), videos: [video({ title: hostile })] }),
    );

    expect(screen.getByText(hostile, { exact: false })).toBeInTheDocument();
    expect(container.querySelector('img[src="x"]')).toBeNull();
  });

  it("says when a finished search found nothing suitable", () => {
    show(topicVideos({ search: search({ result_count: 0 }), videos: [] }));

    expect(screen.getByText(/No videos fitted this topic well enough/)).toBeInTheDocument();
  });

  it("keeps the videos when a newer search failed, and says they are unchanged", () => {
    show(
      topicVideos({
        search: search({ searched_at: "2026-10-01T00:00:00Z" }),
        videos: [video()],
        job: videoJob({ status: "failed", error_message: "YouTube couldn't be reached." }),
      }),
    );

    expect(screen.getByText(/The videos below are unchanged/)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Suggested videos" })).toBeInTheDocument();
  });
});
