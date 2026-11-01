import type { GenerationJob, TopicVideo } from "@/lib/api/server";

/**
 * Wording and safe links for a topic's study videos.
 *
 * Every link is rebuilt here from the video's id, and only YouTube's own image host is used for
 * thumbnails, whatever the API sent: a stored value can never send a learner somewhere else.
 */

const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;
const THUMBNAIL = /^https:\/\/i\.ytimg\.com\/[A-Za-z0-9_\-./]+$/;

/** The watch address of a video, or null if the id is not a YouTube video id. */
export function watchUrl(videoId: string): string | null {
  return VIDEO_ID.test(videoId) ? `https://www.youtube.com/watch?v=${videoId}` : null;
}

/** The thumbnail address if it is on YouTube's image host, otherwise null (no image). */
export function safeThumbnail(url: string | null | undefined): string | null {
  return typeof url === "string" && THUMBNAIL.test(url) ? url : null;
}

/** "12:30", "1:02:03"; null when the length is unknown. */
export function formatDuration(seconds: number | null | undefined): string | null {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds <= 0) return null;
  const whole = Math.round(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = String(whole % 60).padStart(2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

/** "1.2M views", "45K views", "800 views"; null when YouTube gave no count. */
export function formatViews(views: number | null | undefined): string | null {
  if (typeof views !== "number" || !Number.isFinite(views) || views < 0) return null;
  const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });
  return `${compact.format(views)} ${views === 1 ? "view" : "views"}`;
}

const LANGUAGE_NAMES: Readonly<Record<string, string>> = {
  en: "English",
  hi: "Hindi",
  or: "Odia",
};

/** A short language name for a video, but only when the video itself declares one. */
export function videoLanguage(video: Pick<TopicVideo, "language" | "language_source">) {
  if (video.language_source === "unknown" || !video.language) return null;
  const base = video.language.split("-")[0]?.toLowerCase() ?? "";
  return LANGUAGE_NAMES[base] ?? video.language;
}

/** How well a video matched the topic, in words (the number is an estimate, not a rating). */
export function matchLabel(score: number): string {
  if (score >= 75) return "Strong match";
  if (score >= 55) return "Good match";
  return "Possible match";
}

/** What a video search job is doing, in words. */
const STAGE_TEXT: Readonly<Record<string, string>> = {
  queued: "Waiting for a free worker…",
  starting: "Getting started…",
  loading: "Reading the topic…",
  searching: "Searching YouTube…",
  checking: "Checking length, language and availability…",
  saving: "Saving the videos…",
  waiting_retry: "YouTube was busy. Trying again shortly…",
};

export function describeVideoStage(job: Pick<GenerationJob, "stage" | "status">): string {
  if (job.status === "queued" && job.stage === "queued") return STAGE_TEXT["queued"] ?? "";
  return STAGE_TEXT[job.stage] ?? "Working on it…";
}
