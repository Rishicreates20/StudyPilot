import type { TopicVideo, TopicVideos, VideoSearchInfo } from "@/lib/api/server";
import { ITEM, lessonJob } from "@/test-support/lessons";

export const VIDEO_ROW = "66666666-6666-4666-8666-666666666666";
export const SEARCH = "77777777-7777-4777-8777-777777777777";

export function video(overrides: Partial<TopicVideo> = {}): TopicVideo {
  return {
    id: VIDEO_ROW,
    video_id: "dQw4w9WgXcQ",
    url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    title: "Ownership in Rust, explained",
    channel_title: "Rust Teacher",
    duration_seconds: 750,
    published_at: "2025-03-04T05:06:07Z",
    language: "en",
    language_source: "audio",
    searched_language: "en",
    thumbnail_url: "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
    thumbnail_width: 320,
    thumbnail_height: 180,
    view_count: 1_250_000,
    relevance_score: 82,
    score_basis: { title: 35, description: 5, length: 15, category: 10, language: 10 },
    position: 1,
    last_verified_at: "2026-10-11T10:00:05Z",
    ...overrides,
  };
}

export function search(overrides: Partial<VideoSearchInfo> = {}): VideoSearchInfo {
  return {
    id: SEARCH,
    queries: ["Ownership and borrowing rust"],
    languages: ["en"],
    candidates_seen: 20,
    result_count: 1,
    searched_at: "2026-10-11T10:00:05Z",
    last_verified_at: "2026-10-11T10:00:05Z",
    ...overrides,
  };
}

export function topicVideos(overrides: Partial<TopicVideos> = {}): TopicVideos {
  return {
    item_id: ITEM,
    configured: true,
    can_search: true,
    search: null,
    videos: [],
    job: null,
    ...overrides,
  };
}

export function videoJob(overrides: Parameters<typeof lessonJob>[0] = {}) {
  return lessonJob({ job_type: "resources", stage: "searching", progress: 30, ...overrides });
}
