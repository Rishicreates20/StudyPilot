import { describe, expect, it } from "vitest";

import {
  describeVideoStage,
  formatDuration,
  formatViews,
  matchLabel,
  safeThumbnail,
  videoLanguage,
  watchUrl,
} from "@/lib/videos/labels";
import { videoCardState } from "@/lib/videos/state";
import { search, topicVideos, videoJob } from "@/test-support/videos";

describe("watchUrl", () => {
  it("builds the watch address from a real video id", () => {
    expect(watchUrl("dQw4w9WgXcQ")).toBe("https://www.youtube.com/watch?v=dQw4w9WgXcQ");
  });

  it.each(["", "short", "dQw4w9WgXcQ&x=1", "javascript:1", "../../../../x", "dQw4w9WgXcQQ"])(
    "refuses %j instead of building a link from it",
    (id) => {
      expect(watchUrl(id)).toBeNull();
    },
  );
});

describe("safeThumbnail", () => {
  it("keeps YouTube's own image host", () => {
    const url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg";
    expect(safeThumbnail(url)).toBe(url);
  });

  it.each([
    "http://i.ytimg.com/vi/x.jpg",
    "https://evil.example/vi/x.jpg",
    "https://i.ytimg.com.evil.example/x.jpg",
    "https://i.ytimg.com/x.jpg?track=1",
    "javascript:alert(1)",
    null,
    undefined,
  ])("drops %j", (url) => {
    expect(safeThumbnail(url)).toBeNull();
  });
});

describe("formatting", () => {
  it.each([
    [750, "12:30"],
    [59, "0:59"],
    [3723, "1:02:03"],
    [0, null],
    [null, null],
  ])("formats %j seconds as %j", (seconds, text) => {
    expect(formatDuration(seconds)).toBe(text);
  });

  it("formats view counts compactly", () => {
    expect(formatViews(1_250_000)).toBe("1.3M views");
    expect(formatViews(800)).toBe("800 views");
    expect(formatViews(1)).toBe("1 view");
    expect(formatViews(null)).toBeNull();
  });

  it("names a language only when the video declares one", () => {
    expect(videoLanguage({ language: "hi", language_source: "audio" })).toBe("Hindi");
    expect(videoLanguage({ language: "en-GB", language_source: "metadata" })).toBe("English");
    expect(videoLanguage({ language: "ta", language_source: "audio" })).toBe("ta");
    expect(videoLanguage({ language: null, language_source: "unknown" })).toBeNull();
  });

  it("puts the match estimate into words", () => {
    expect(matchLabel(90)).toBe("Strong match");
    expect(matchLabel(60)).toBe("Good match");
    expect(matchLabel(31)).toBe("Possible match");
  });

  it("describes each stage of a search, and anything unknown generically", () => {
    expect(describeVideoStage({ status: "running", stage: "searching" })).toBe(
      "Searching YouTube…",
    );
    expect(describeVideoStage({ status: "queued", stage: "waiting_retry" })).toMatch(/busy/);
    expect(describeVideoStage({ status: "running", stage: "mystery" })).toBe("Working on it…");
  });
});

describe("videoCardState", () => {
  it("offers a search when there is none and nothing is running", () => {
    expect(videoCardState(topicVideos())).toEqual({ active: null, failed: null, canSearch: true });
  });

  it("shows a running search and offers nothing else meanwhile", () => {
    const job = videoJob({ status: "running" });
    const state = videoCardState(topicVideos({ job }));
    expect(state.active).toBe(job);
    expect(state.canSearch).toBe(false);
  });

  it("shows a failure only when it is newer than the suggestions", () => {
    const old = videoJob({ status: "failed", created_at: "2026-10-01T00:00:00Z" });
    const fresh = videoJob({ status: "failed", created_at: "2026-10-12T00:00:00Z" });
    const data = { search: search({ searched_at: "2026-10-11T10:00:05Z" }) };

    expect(videoCardState(topicVideos({ ...data, job: old })).failed).toBeNull();
    expect(videoCardState(topicVideos({ ...data, job: fresh })).failed).toBe(fresh);
    expect(videoCardState(topicVideos({ job: old })).failed).toBe(old);
  });

  it("never offers a search the API says cannot start", () => {
    expect(videoCardState(topicVideos({ can_search: false })).canSearch).toBe(false);
  });
});
