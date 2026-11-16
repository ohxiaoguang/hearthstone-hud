# Changelog

User-visible changes per version. 中文版：[CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)

## v1.0.6

- Read the pointer from the live game's X11 display when Gamescope runs the game
  and the HUD on separate servers (for example, game :1 and overlay :0).
- Map game root coordinates into the fullscreen HUD display, preserving the overlay
  window, shared card registration, click-through, image downloads and caches.
- Add pointer source/resolution/mapping diagnostics and recoverable game-display
  connection handling with a five-second reconnect cooldown.
- Same-display setups keep the existing client-coordinate path. Live SteamOS
  verification is still required, especially for unusual compositor letterboxing.

## v1.0.5

- Add a frame-local card-region collector shared by arena and match panels, with
  registration counts, Card IDs, filtering reasons and draw/clip rectangles.
- Retain the last nonempty registration, hover hit and image request after the
  pointer leaves, so opening Decky to copy diagnostics preserves useful evidence.
- Record pointer movement while cards are visible and report both game and renderer
  X11 displays. Keep pointer acquisition, downloads, caches and click-through unchanged.
- This release improves diagnosis; the reported hover failure is not yet confirmed fixed.

## v1.0.4

- Translate the X11 root pointer into HUD client and ImGui display coordinates for
  the shared arena/match hover mechanism; ignore clipped empty card hit regions.
- Add hover diagnostics covering pointer queries, card hits, request IPC, download,
  decode, texture upload and rendering, available through Copy diagnostics.
- Retry failed full-card downloads after cooldown while still hovered, preserve
  error details, and reject malformed hover requests without interrupting tracking.
- Preserve the transparent overlay, empty X11 input shape and ImGui NoInputs flags.

## v1.0.3

- Add Copy Update Link beside Copy diagnostics, with localized clipboard feedback
  and a fixed link to the latest stable release ZIP.
- Add full-card hover previews with localized, bounded on-demand caching.
- Clear confirmed inactive arena drafts while preserving cards across temporary read failures.
- Show a waiting label at the remaining-deck position and the confirmed match deck name.

## v1.0.2

- Promoting a batch-queued card to the front of the download queue now checks the queue's
  capacity first: when the on-demand queue is full, the card keeps its low-priority slot and
  its reservation instead of raising an error, and no download task can be lost. A card
  promoted after cancelling the batch still downloads, and every card is still fetched
  exactly once.

- A card waiting in the bulk-download queue is promoted to the front when the game asks for
  it, so scrolling a deck never waits behind a full run; it is still downloaded exactly once
  and counted once in the batch progress.
- Full card-art downloads can be cancelled from the settings panel. Cancelling keeps every
  tile already on disk, drops the rest of the batch, and leaves the on-demand requests for
  cards visible in the game untouched.
- Card art now uses two download queues: cards currently visible in the game (deck, plays,
  arena) go first, and the full download only fills the low-priority queue, so game art
  never waits behind a bulk run.
- The resource panel no longer uses modal dialogs: deleting a database or clearing card art
  asks for confirmation inline, with Confirm/Cancel buttons next to the resource, and the
  running download shows a Cancel button.

## v1.0.1

- Download-failure messages no longer mention the removed offline import: the failure text
  points to the retry button, and the card-data validation messages describe downloaded
  data instead of imported files. The TLS error about a missing CA bundle was reworded too.
- While a full card-art download is running, both the download and the delete-art buttons
  are disabled, so the two operations can no longer conflict.
- The full language table is kept: the engine still knows all fourteen HearthstoneJSON
  locales; today the settings page manages the English and Simplified Chinese databases.

- The legacy language-neutral `cards.json` cache is no longer read or adopted. Databases
  are exactly `cache/cards-enUS.json` and `cache/cards-zhCN.json`, following the interface
  language; a fresh install downloads its language automatically, and upgrading from a
  version older than v0.7.0 re-downloads the card names once.
- The settings page scans only those two databases; other locales' leftover cache files are
  ignored.
- The unused offline card-database import and the manual card-art import machinery were
  removed, including the legacy `cache/images/manual/` override directory: *Delete card
  art* deletes that directory too, and tiles in it are no longer displayed.
- *About* is now a fold inside the settings page (summary, version, repository) instead of
  a dialog, avoiding modal layout glitches.

## v1.0.0

First stable release. Everything implemented so far, in one place:

- **Deck tracking.** Parses Power.log for the live match: your remaining deck grouped by
  original vs added/transformed cards, opponent hand and deck counts, your and their most
  recent plays, per-card provenance (starting deck, transformed, copied, generated), turn
  header, and exact counts with reasons whenever evidence is incomplete. Decks.log provides
  the exact starting deck for arena matches.
- **Arena helper.** Optional read-only process memory access: hero and card candidates with
  HearthArena card ratings and Firestone class statistics, the selected deck sorted by mana
  cost (ties by name, unknown cost last), and duplicate cards kept as real copies. The
  memory DraftDeck is the only source for selected cards, verified by two consistent reads;
  candidates are preview-only. Failures keep the last deck marked "count unconfirmed".
- **Card data and languages.** Bilingual interface (English default, 简体中文) that also drives
  the card database (enUS / zhCN); each database is cached per language, reused offline and
  only downloaded when missing. Language switching mid-download cannot corrupt the result.
- **Card art.** Language-independent tile cache, downloaded on demand for what is on screen
  or in one resumable full pass with per-card statistics (success, failed, without art,
  already cached); HTTP 404 is remembered as "no art" and not retried in the session.
- **Resource management.** The settings panel shows both databases with size, state and a
  delete button each, plus card art usage with independent cleanup; clearing one resource
  never touches the others.
- **Lifecycle and diagnostics.** Master switch that stops all background work, safe
  start/stop of the native HUD renderer, log.config management for Power/Decks/Arena
  logging, and a one-click redacted diagnostic report for bug reports.
- **Release format.** Releases contain a single `hearthstone-hud.zip` at the permanent
  address
  `https://github.com/ohxiaoguang/hearthstone-hud/releases/latest/download/hearthstone-hud.zip`;
  they are stable (not pre-releases) and the build reports stay in the Actions artifacts.

## v0.7.2

- Card art download counts each card once: a card that fails and then succeeds on the retry
  is reported as a success, a card without art (HTTP 404) is listed separately and never
  requested again in that session, and progress stays at or below 100%.
- Image statistics and "delete card art" now also cover the legacy `cache/images/manual/`
  directory, while JSON databases, settings and unrelated files are left in place.

- Settings are simpler: one *Language options* control drives both the interface and the card
  database (English → enUS, Chinese → zhCN); the separate card-language picker is gone.
- New *Download resources* section: per-database status, file size and delete button, plus
  card art statistics, a resumable "download all card art" run and an art-only delete button.
  Card art is no longer capped at 256 files / 32 MiB.
- Font size and panel width moved into *Display*; the old "clear and re-download card data"
  button and manual image import were removed.
- *Copy diagnostics* and *About* are now small buttons side by side at the bottom; About shows
  the name, summary, version and repository.

## v0.7.1

- Switching the card language while a download is running now discards that download: the
  finish order can no longer install the previous language or overwrite the new language's
  pending state.
- Every remaining text the HUD renders (deck group headings) and every error the settings
  panel can show now comes from the translation catalog; English mode no longer shows
  Chinese text anywhere in the HUD or the panel.

## v0.7.0

- Card database supports all 14 HearthstoneJSON locales, each cached separately and reused
  when you switch back — no repeated downloads.
- New **Interface language** setting (English default, Simplified Chinese) covering the Decky
  panel, the HUD labels and the arena panel titles. It is independent of the card language.
- The HUD font atlas now covers Latin, Cyrillic, Chinese, Japanese, Korean and Thai, so card
  names render in every supported language.
- Arena titles and HUD labels are supplied by the backend instead of being hardcoded in the
  renderer; the `chinese_names` setting became `show_card_names` (old values are migrated).
- README rewritten as a user guide in English with a Simplified Chinese translation; obsolete
  development reports removed.

## v0.6.0

- Arena selected cards come only from the game's memory DraftDeck. Arena.log no longer counts
  picks, so previewing a candidate several times cannot inflate the list.
- One flat `Selected X/30` list sorted by mana cost; duplicates keep their copies; the count
  hint appears only while a memory read is failing and clears by itself afterwards.
- Removed the log/memory merge and the unused manual arena page from the QAM.

## v0.5.1

- Arena recovery anchored on the read window of the memory snapshot, so a pick made while the
  deck was being read is never mistaken for history.
- Deck parsing isolated from candidate parsing; missing and null fields reported separately.
- `Recovery Executed` separated from `Merge Executed`.

## v0.5.0

- Master switch that stops renderer, log scanning, memory thread and downloads while keeping
  settings and caches.
- Arena helper recovers cards already drafted when it is turned on mid-draft.

## v0.4.2

- Simplified QAM page: HUD and arena switches, font size and width, display settings, card art
  download, cache reset and diagnostics only.
- Automatic log configuration for the running Proton prefix, following prefix changes.

## v0.4.1

- Single-line card rows with a mana badge, adjustable 14–30 px font, compact panels.
- One "Show HUD" switch and immediate setting publication.

## v0.4.0

- Optional read-only memory reader for arena candidates; off by default.

## v0.3.0

- Static arena card ratings and class win rates, with per-candidate recommendations.

## v0.2.x

- Log configuration and backups, certificate verification with offline import, deck tracking
  fixes, clipboard diagnostics and frontend checks.

## v0.1.x

- First working HUD: own remaining deck and played cards, with display and touch pass-through
  verified on hardware.
