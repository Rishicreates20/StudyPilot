# StudyPilot — Product Requirements Document

| | |
|---|---|
| **Status** | Draft v0.1 — planning phase, no application code yet |
| **Date** | 2026-10-09 |
| **Source** | `StudyPilot_AI_Learning_Platform_Conversation.pdf` (product brief, architecture notes, schema, AI workflows, master build prompt). Referred to below as "the source brief". It is not committed to this repository. |
| **Related** | [ARCHITECTURE.md](ARCHITECTURE.md) · [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |

"StudyPilot" is a working name. It is configurable (`APP_NAME` / `NEXT_PUBLIC_APP_NAME`) and must not be hard-coded into logic.

---

## 1. Vision

> Turn any learning goal or study material into a personalized, measurable learning journey.

StudyPilot is a **personal AI learning coach**, not an AI notes generator. The product exists to answer five questions for a learner:

1. What do I need to learn to reach my goal?
2. What should I study today?
3. Can I understand this concept in a different way?
4. Do I actually understand what I studied?
5. What should I work on next?

The whole learning loop is the product: **intent → plan → teach → test → find weaknesses → adapt the next session.** A feature that does not improve the learner's *next* study session is lower priority than one that does.

### Product principles

- **Outcomes over content volume.** Measure learning (quiz results, mastery, return rate), not the number of generated notes.
- **One audience first, configurable beyond.** Launch narrow; keep goal types, curricula and languages as data, not code.
- **AI is a controlled backend workflow.** Every AI step has typed input/output, validation, bounded retries and a cost cap. No open-ended autonomous agents.
- **Deterministic where possible.** Grading, mastery, scheduling and plan feasibility are computed by code, not by a model judging itself.
- **Honest about uncertainty.** Source-backed claims show their source; unsupported claims are labelled; OCR output is reviewable.
- **The learner owns their data.** Private by default, deletable, minimised.

## 2. Launch positioning

**Assumption A1 — launch segment is Persona A (professional upskiller).** The source brief recommends this if the entry point is DevOps/software, and it fits the intended team background. Personas B and C are supported by the architecture (goal types and languages are data) but not validated at launch.

| Persona | Who | What they need | Launch role |
|---|---|---|---|
| **A — Professional upskiller** | Learning Linux, Docker, Kubernetes, CI/CD, cloud, system design; preparing for technical interviews or certifications | Practical roadmaps, knowledge checks, a way to track competence | **First target** |
| **B — Exam candidate** | School/university/competitive-exam candidates | Syllabus coverage, revision schedules, practice questions tailored to an exam date and weekly hours | After learning quality and retention are demonstrated |
| **C — Student** | Needs help with hard lessons, turning class notes into study material, revision, weak-chapter detection | Note ingestion (incl. handwritten), revision tools | After B; requires a minors/consent review first (see A9) |

## 3. Primary user journey

1. **Create a goal** — topic/exam/certification, current level, target date, daily time, preferred language(s).
2. **Add context (optional)** — PDF, notes, pasted text, public syllabus URL. *(P1)*
3. **Review a roadmap** — ordered modules with objectives, prerequisites, estimated durations and a clear "start here".
4. **Study a lesson** — structured explanation, examples, glossary, source references, "explain simply".
5. **Take a knowledge check** — questions, explanations after submission, saved attempts, mastery.
6. **Adapt** — weak topics get more practice; strong topics progress or move to revision. The learner is always told **what to do next and why**, not just given a score.

The critical hand-off is **assessment result → next recommended action**.

## 4. Scope and priorities

The source brief contains two priority schemes that disagree on where *document upload* sits (P0 in the Part II table; P1 in the master build prompt). **Resolution:** the master build prompt governs, because it is the more detailed and later statement. Document upload and RAG are P1, but the data model, job queue and AI abstractions are designed from day one so RAG slots in without rework. The *beta* gate still requires document upload (see §11), matching the source brief's MVP acceptance criteria.

| Priority | Features | Success definition |
|---|---|---|
| **P0 — Core loop** | Auth and profiles · learning-goal create/edit/archive · learning preferences (level, daily time, target date, languages) · async roadmap generation · versioned roadmaps (modules, objectives, prerequisites, durations) · structured lessons · study workspace with progress and resume · MCQ assessments with explanations · saved attempts and topic mastery · resumable/retry-safe jobs · ownership enforcement · per-user generation limits | A user can sign up, create a goal, generate a roadmap, study a lesson, take a quiz, see weak topics, and resume later |
| **P1 — Learning loop** | Document upload + RAG + citations · PDF extraction and OCR · flashcards with deterministic spaced repetition · YouTube recommendations (official API) · adaptive roadmap updates · revision reminders and study streaks · learner analytics · "report a problem" on content | Assessment results measurably change what the app recommends next, and source-based answers show their sources |
| **P2 — Differentiation** | PDF/PPT export · multilingual improvements (Hindi, Odia) · richer gamification · Expo mobile apps · subscriptions and usage-limit infrastructure · offline study · more exam verticals | Learners reuse materials; the product can reach new audiences and channels |

**Postponed on purpose** (from the source brief): open-ended autonomous agents, Pinecone or any second vector store, elaborate gamification, multiple simultaneous LLM providers, microservices, automatic video transcription, sophisticated recommendation engines.

## 5. Functional requirements

Each requirement has an ID so milestones, tests and commits can reference it.

### P0

| ID | Requirement | Acceptance criteria |
|---|---|---|
| **FR-1 Auth & profile** | Sign up, sign in, sign out, persistent session. A `profiles` row exists for every user. Display name, locale and timezone are editable. | An unauthenticated request to any protected endpoint returns 401. User B cannot read or modify user A's profile or goals through the API **or** through a database session acting as user B. |
| **FR-2 Learning goals** | Create, view, edit, pause, complete and archive goals. Fields: title, description, goal type, current level (including `unknown`), target date (optional, not in the past), daily minutes, preferred languages. | A created goal is stored in PostgreSQL, belongs to the authenticated user, and appears on the dashboard after a reload. Invalid input yields field-level errors. Lists are paginated. Loading, empty and error states exist. |
| **FR-3 Roadmap generation** | Asynchronous generation from a goal (text-only; works with no documents and no YouTube). The user sees stage-level progress, can navigate away and return, and can retry a failed job. | Submitting twice does not create two roadmaps or two charges (idempotency). The saved roadmap passes **programmatic** checks: total planned minutes fit the available time budget when a target date exists; prerequisites precede dependents; every learning objective is covered by at least one item; sequence numbers are unique. The roadmap has a clear next step. |
| **FR-4 Roadmap review & versioning** | Roadmaps are versioned. The learner can review, skip, reorder, and adjust the time of items. Regeneration creates a new version and supersedes the old one without deleting it. | Version history is retained. At most one `published` roadmap exists per goal. Learner edits persist. |
| **FR-5 Lessons** | One lesson per roadmap item, generated as validated structured JSON: objectives, sections, key terms, examples, common misconceptions, summary, and a pre-generated simple explanation. | Output conforms to the lesson schema or is rejected and retried within a bound. The "Explain simply" toggle uses the stored simple explanation (no extra model call). When sources exist, claims carry real chunk citations; otherwise the lesson is labelled as general knowledge. |
| **FR-6 Study workspace** | Readable lesson view with navigation across roadmap items, progress indicators, glossary and a "continue where you left off" entry point. | Closing the app and returning resumes at the last item. Mobile-width layout is usable. |
| **FR-7 Quizzes** | MCQ (and true/false) questions linked to learning objectives. Answers are graded **on the server**. Explanations appear only after submission. | The API never returns answer keys or explanations before submission (verified by test). Every MCQ has exactly one correct option. Attempts and per-question answers persist. Retakes are allowed. |
| **FR-8 Mastery & next action** | Deterministic per-topic mastery from attempts, difficulty and recency. Weak topics are flagged against transparent, configurable thresholds. The app recommends one concrete next action with its reason. | Mastery is recomputed from stored attempts and is reproducible. The default weak-topic threshold is 70% — a **tunable product rule, not a validated educational threshold**. |
| **FR-9 Jobs** | All long-running work runs in a worker. Jobs have states `queued`, `running`, `completed`, `failed`, `cancelled`; bounded retries; clear user-safe errors. | A killed worker does not lose a job; it is reclaimed after its lease expires. A retried job resumes from its last completed stage instead of repeating (and re-paying for) finished stages. |
| **FR-10 Usage limits** | Per-user daily generation budgets with visible remaining allowance; token and cost recorded per call. | Exceeding the budget returns a clear, non-technical error before any model call is made. |

### P1

| ID | Requirement |
|---|---|
| **FR-11 Documents & RAG** | Private upload (PDF, text/markdown; images via OCR) with visible processing status and useful failure messages; page-aware chunking; embeddings; hybrid retrieval limited to the user's own documents; citations to real chunk IDs and page numbers; explicit "insufficient evidence" handling. Uploaded content is treated as untrusted data, never as instructions. |
| **FR-12 OCR & handwriting** | Extracted text is reviewable and correctable before it is used as authoritative material; uncertain passages are flagged. No promise of perfect recognition. |
| **FR-13 Flashcards** | Deterministic spaced repetition (SM-2-style) with full review history stored so the algorithm can be upgraded later. |
| **FR-14 Resource curation** | YouTube results come only from the official API (never model-invented URLs), are cached, ranked by explicit criteria, and carry a last-verified timestamp. No fabricated timestamps. |
| **FR-15 Adaptive roadmap** | Mastery records trigger a planner request for an updated roadmap version; weak areas get more practice. |
| **FR-16 Reminders & streaks** | In-app "due today" and revision-due indicators and a supportive streak counter. Email reminders are a later add-on. |
| **FR-17 Analytics** | Mastery by topic, revision due dates, study consistency, suggested next actions. |
| **FR-18 Report a problem** | Learners can flag an incorrect lesson, question or resource. |

### P2

PDF and PPT export, Hindi/Odia improvements, Expo apps, subscriptions, offline study, additional exam verticals.

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| **Security** | JWT verified at the API boundary; ownership checked on every protected operation **and** enforced by row-level security; answer keys never leave the server before submission; private storage with short-lived signed URLs; no service-role, LLM or database credentials in client bundles or Git; safe error responses (no stack traces, prompts or secrets). |
| **Privacy** | Learner documents and performance history are sensitive. Data minimisation, deletion on request (including stored files), retention controls, and no document or prompt content in logs by default. Document content may be sent to the configured AI provider; this must be disclosed in the privacy notice. |
| **Reliability** | Idempotent job creation, bounded retries, lease-based job recovery, transactional persistence of related writes. |
| **Cost** | Per-user budgets, caching of reusable results, no redundant model calls, usage metering per job and per user. |
| **Performance** | API responses never wait on model calls. Dashboard and lesson views load from stored data. Targets are set after M3 with real measurements rather than guessed now. |
| **Accessibility** | WCAG-minded: keyboard navigation, visible focus, contrast-checked light and dark themes, reduced-motion support, semantic structure. |
| **Internationalisation** | Fonts and rendering that support Latin, Devanagari and Odia scripts; per-goal preferred languages; UI translation deferred. |
| **Responsiveness** | Study flows are designed for mobile widths first. |
| **Observability** | Request correlation IDs, structured logs with job IDs, model identifiers, latency and token usage; error tracking. |
| **Maintainability** | Modular monolith, typed contracts, versioned prompts, tests alongside every slice. |

## 7. UX requirements

Calm, focused, reading-oriented — not a generic chat screen.

**Core screens:** landing · sign-in/sign-up · onboarding wizard · learning dashboard · create goal · roadmap overview · lesson workspace · quiz and results · progress and mastery · flashcard review · settings · basic admin/diagnostic view.

**Standards:** small token-based palette and consistent spacing/typography; light and dark themes; accessible shadcn/ui primitives; loading skeletons, empty, error, success, offline and retry states; no hard-coded statistics presented as real data; mock data only in clearly labelled previews.

## 8. Success metrics

Track from the first beta: **activation rate**, **time to first completed lesson**, **first-quiz completion**, **week-one return rate**, **generation failure rate**, **AI cost per active learner**. These matter more than the total number of generated notes.

## 9. Product risks and mitigations

| Risk (from the source brief) | Mitigation in this plan |
|---|---|
| Market too broad | Persona A first; goal types and languages are data. |
| Hallucinated educational content | Citation validation against real chunks; supported vs general-knowledge labelling; server-validated answer keys; "report a problem" (FR-18). |
| Unbounded AI cost | Per-user budgets and usage ledger land with the *first* AI feature (M3), not at the end. |
| Slow generation | Worker + stage-level status; users can navigate away; checkpointed retries. |
| Building content instead of outcomes | Quizzes, mastery and next-action are in the P0 loop (M5), before any content-breadth features. |
| Video search ≠ quality curation | Transparent ranking, caching, learner feedback; YouTube quota verified on the real project before it becomes a dependency. |
| Student privacy | Adult launch segment; consent/age review before opening to students; deletion and retention design from the start. |

## 10. MVP acceptance criteria

Taken from the source brief; each is traced to a milestone in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

| # | Criterion | Milestone |
|---|---|---|
| 1 | A user can sign up, create a goal and access only their own data. | M1 |
| 2 | A document upload shows clear processing status, useful errors on failure, and yields a usable roadmap when successful. | M6 |
| 3 | Roadmaps have objectives, ordered topics, estimated time and a clear next step. | M3 |
| 4 | Lessons and questions conform to validated schemas, not free-text blobs. | M4, M5 |
| 5 | Quiz submissions persist; explanations appear after submission without exposing answer keys beforehand. | M5 |
| 6 | A learner can close the app, return and continue where they stopped. | M4 |
| 7 | Failed AI jobs can be retried safely without duplicate roadmaps or charges. | M3 |
| 8 | Source-based answers expose supporting material; unsupported claims are marked, not presented as verified. | M6 |

**Release gates:** *private alpha* = M5 complete (the full P0 loop). *Beta* = M6 complete (documents/RAG) plus M9 hardening.

## 11. Assumptions

Recorded rather than asked, per the working agreement. Each can be overridden; none blocks Milestone 1 unless stated.

| ID | Assumption |
|---|---|
| **A1** | Launch segment is Persona A (professional upskiller). |
| **A2** | UI is English at launch. Lesson language follows the goal's first preferred language; Hindi/Odia content quality is a P2 improvement. |
| **A3** | Auth is Supabase email + password, with email confirmation enabled outside local development. Social login is a later addition. |
| **A4** | The first real LLM adapter is **Gemini** (generous free tier for an MVP, strong multilingual and vision support). OpenAI is the second adapter. Provider choice is configuration, not architecture. **To confirm before M3.** |
| **A5** | Embeddings use a fixed 1536-dimension vector, matching the source schema. The exact model is chosen with the provider and recorded per chunk. |
| **A6** | Hosting: Vercel (web), Render (API + worker, Docker), Supabase managed (Auth, Postgres, Storage). |
| **A7** | Learner edits to a roadmap apply in place to the published version; regeneration creates a new version. |
| **A8** | Budget defaults (for example 5 roadmap and 30 lesson generations per user per day) are placeholders to be tuned from M3 measurements. |
| **A9** | The launch audience is adults. Before enabling Persona C, review age gating, consent and applicable child-privacy rules. |
| **A10** | Reminders are in-app first; email reminders come after beta. |
| **A11** | No payments or subscriptions at launch. |
| **A12** | Supabase region should be near the users (for example Mumbai) — the account owner's choice. |
| **A13** | Tooling: Python 3.14, Node 24, npm workspaces, `uv`. See ARCHITECTURE §15 for why. |
| **A14** | No open-source licence has been chosen; until one is added the code is all-rights-reserved by default. |

### Open questions (none block M1)

- **Q1** Confirm Persona A as the launch segment.
- **Q2** Confirm Gemini first (A4) before M3.
- **Q3** Supabase region (A12).
- **Q4** Licence (A14), and whether the repository should stay public.
- **Q5** Additional sign-in methods (for example Google) for beta.
