import {
  CircleAlertIcon,
  ExternalLinkIcon,
  InfoIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  SearchIcon,
  VideoIcon,
} from "lucide-react";

import { EmptyState } from "@/components/feedback/empty-state";
import { SubmitButton } from "@/components/forms/submit-button";
import { VideoSearchStatus } from "@/components/videos/video-search-status";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import type { TopicVideo, TopicVideos as TopicVideosData } from "@/lib/api/server";
import { formatMoment } from "@/lib/format";
import { findVideosAction, retryVideoSearchAction } from "@/lib/videos/actions";
import {
  formatDuration,
  formatViews,
  matchLabel,
  safeThumbnail,
  videoLanguage,
  watchUrl,
} from "@/lib/videos/labels";
import { videoCardState } from "@/lib/videos/state";

type TopicVideosProps = {
  goalId: string;
  itemId: string;
  data: TopicVideosData;
  timeZone: string;
};

/**
 * "Watch": videos for this topic, found on YouTube by the worker and ranked by explicit rules.
 *
 * The card is honest about where they come from: StudyPilot did not make or review them, the
 * lesson was not written from them, and the match is an estimate from YouTube's own metadata.
 * Links are rebuilt from the video id and open YouTube in a new tab.
 */
export function TopicVideos({ goalId, itemId, data, timeZone }: TopicVideosProps) {
  const state = videoCardState(data);
  const { search, videos } = data;
  const find = findVideosAction.bind(null, goalId, itemId);

  return (
    <section id="videos" aria-labelledby="videos-heading" className="scroll-mt-24 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h2 id="videos-heading" className="font-heading text-xl font-semibold tracking-tight">
            Videos on this topic
          </h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Found on YouTube and checked for length, language and availability. StudyPilot
            didn&rsquo;t make these videos and hasn&rsquo;t reviewed them, and your lesson
            wasn&rsquo;t written from them.
          </p>
        </div>
        {search && state.canSearch ? (
          <form action={find}>
            <input type="hidden" name="refresh" value="1" />
            <SubmitButton size="sm" variant="outline">
              <RefreshCwIcon aria-hidden="true" />
              Find other videos
            </SubmitButton>
          </form>
        ) : null}
      </div>

      {!data.configured ? (
        <Alert variant="info">
          <InfoIcon aria-hidden="true" />
          <AlertDescription>
            Video suggestions aren&rsquo;t set up on this server yet.
          </AlertDescription>
        </Alert>
      ) : null}

      {state.active ? (
        <VideoSearchStatus goalId={goalId} itemId={itemId} job={state.active} />
      ) : null}

      {state.failed ? (
        <Alert variant="destructive">
          <CircleAlertIcon aria-hidden="true" />
          <AlertTitle>We couldn&rsquo;t find videos</AlertTitle>
          <AlertDescription>
            <p>
              {state.failed.error_message ?? "Something went wrong. Please try again."}
              {search ? " The videos below are unchanged." : null}
            </p>
            {state.canSearch ? (
              <form
                action={retryVideoSearchAction.bind(null, goalId, itemId, state.failed.id)}
                className="mt-3"
              >
                <SubmitButton size="sm" variant="outline">
                  <RotateCcwIcon aria-hidden="true" />
                  Try again
                </SubmitButton>
              </form>
            ) : null}
          </AlertDescription>
        </Alert>
      ) : null}

      {data.configured && !search && !state.active && !state.failed ? (
        <EmptyState
          icon={VideoIcon}
          headingLevel="h3"
          title="Find videos for this topic"
          description={
            data.can_search
              ? "StudyPilot searches YouTube for this topic and suggests a few videos that fit it, with their length and language."
              : "Videos can only be found for topics of the current roadmap of a goal that isn't archived."
          }
          action={
            state.canSearch ? (
              <form action={find}>
                <SubmitButton>
                  <SearchIcon aria-hidden="true" />
                  Find videos
                </SubmitButton>
              </form>
            ) : undefined
          }
        />
      ) : null}

      {search && videos.length === 0 && !state.active ? (
        <p className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
          No videos fitted this topic well enough to suggest. You can search again later.
        </p>
      ) : null}

      {videos.length > 0 ? (
        <ol className="grid gap-4 sm:grid-cols-2" aria-label="Suggested videos">
          {videos.map((video) => (
            <VideoCard key={video.id} video={video} />
          ))}
        </ol>
      ) : null}

      {search ? (
        <p className="text-xs text-muted-foreground">
          Searched YouTube for &ldquo;{search.queries[0] ?? ""}&rdquo;
          {search.languages.length > 1 ? ` (in ${search.languages.join(" and ")})` : ""},{" "}
          {formatMoment(search.searched_at, timeZone)}. Match is an estimate from each video&rsquo;s
          title, description, length and language, not a rating of its quality.
        </p>
      ) : null}
    </section>
  );
}

function VideoCard({ video }: { video: TopicVideo }) {
  const href = watchUrl(video.video_id);
  if (href === null) return null;
  const thumbnail = safeThumbnail(video.thumbnail_url);
  const duration = formatDuration(video.duration_seconds);
  const views = formatViews(video.view_count);
  const language = videoLanguage(video);

  return (
    <li className="overflow-hidden rounded-xl border bg-card">
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="group block outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
      >
        <div className="relative aspect-video bg-muted">
          {thumbnail ? (
            // A plain <img>: thumbnails come straight from YouTube's image host, at a fixed small
            // size, so the Next image optimiser (and a remote-image allow-list) would add nothing.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={thumbnail}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              width={video.thumbnail_width ?? 320}
              height={video.thumbnail_height ?? 180}
              className="size-full object-cover"
            />
          ) : (
            <div className="flex size-full items-center justify-center text-muted-foreground">
              <VideoIcon className="size-8" aria-hidden="true" />
            </div>
          )}
          {duration ? (
            <span className="absolute right-2 bottom-2 rounded bg-foreground/80 px-1.5 py-0.5 text-xs font-medium text-background tabular-nums">
              <span className="sr-only">Length </span>
              {duration}
            </span>
          ) : null}
        </div>
        <div className="space-y-2 p-4">
          <p className="line-clamp-2 font-medium group-hover:underline group-hover:underline-offset-4">
            {video.title}
            <ExternalLinkIcon
              className="ml-1 inline size-3.5 align-baseline text-muted-foreground"
              aria-hidden="true"
            />
            <span className="sr-only"> (opens YouTube in a new tab)</span>
          </p>
          <p className="text-sm text-muted-foreground">
            {video.channel_title || "Unknown channel"}
            {views ? ` · ${views}` : ""}
          </p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">{matchLabel(video.relevance_score)}</Badge>
            {language ? <Badge variant="outline">{language}</Badge> : null}
          </div>
        </div>
      </a>
    </li>
  );
}
