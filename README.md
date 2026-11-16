# Hearthstone HUD

**English** · [简体中文](README.zh-CN.md)

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that draws an
always-on overlay for Hearthstone on SteamOS and other Linux handhelds: your remaining
deck, both players' played cards, and an arena drafting panel with card ratings.

Current release: **v1.0.5** · [Changelog](CHANGELOG.md) · [中文说明](README.zh-CN.md)

> This is an unofficial community project. It is not affiliated with, endorsed by, or
> sponsored by Blizzard Entertainment or HearthSim. Hearthstone and its card data and art
> are property of Blizzard Entertainment.

## What it does

| Feature | Details |
| --- | --- |
| Deck tracker | Your remaining deck with per-card counts, plus "your plays" and "opponent plays" driven by Hearthstone's own `Power.log`. |
| Arena panel | The three candidates with arena ratings (best pick highlighted) and your drafted cards as one list sorted by mana cost. |
| Card art | Tiles are downloaded on demand for the cards you actually see, never as a full set. |
| Bilingual interface | English (default) and Simplified Chinese. The card database follows the interface language. |
| Read-only arena memory | Optional. Reads the game's own draft objects to show what you have already picked. |

## Requirements

- SteamOS 3.x, or another Linux x86_64 system with [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 2.x installed.
- Hearthstone installed and run through Proton.
- The **Linux x86_64** build from the Releases page. The HUD is a native OpenGL program;
  Windows builds are not provided.
- About 40 MB for the plugin, plus roughly 2–4 MB per cached card database. Card art is
  stored without a size cap, so a full download takes noticeably more space.

## Installation

1. Download the plugin ZIP from the [latest release](https://github.com/ohxiaoguang/hearthstone-hud/releases/latest),
   or always the newest one from the fixed address:
   `https://github.com/ohxiaoguang/hearthstone-hud/releases/latest/download/hearthstone-hud.zip`.
2. Open Decky Loader → **Settings (⚙) → General → Install plugin from file** and pick the ZIP.
3. Open the Quick Access Menu (⋯ button) and select **Hearthstone HUD**.

Updating works the same way: install the newer ZIP over the old version. Settings, caches and
downloaded art are kept. Upgrading from a version older than v0.7.0 re-downloads the card
database once, because the old language-neutral `cards.json` cache is no longer read.

## First run

1. The plugin is enabled by default. Turn on **Show HUD** to start the overlay.
2. On first start the plugin adds the `Power`, `Decks` and `Arena` sections to Hearthstone's
   `log.config` for the Proton prefix that is currently running, after backing up the original
   file. **Fully exit Hearthstone and start it again** so the game writes those logs.
3. Queue into a match. The HUD shows a header line, your remaining deck, and lists of played
   cards as soon as the game exposes them.
4. For arena drafting, enable **Arena helper** as well (see below).

If the game is not running when you enable the HUD, the plugin waits for the process and
enables logging the next time Hearthstone starts.

## Settings

| Setting | What it changes |
| --- | --- |
| Language options | English or 简体中文. Applies immediately to this panel and to the HUD; the card database follows it (enUS / zhCN) and is loaded from cache or downloaded. |
| Enable plugin | Master switch. Turning it off stops all background work and keeps settings and caches. |
| Show HUD | Starts or stops the overlay renderer. |
| Arena helper | Opt-in read-only process memory access for the arena panel. |
| Display (fold) | Card name font size (14–30 px), panel width (180–640 px), overall scale, opacity, panel positions, and which panels are shown. |
| Download resources (fold) | Per-database state and size with a delete button for each language, plus card art statistics, a full art download and a delete button. |
| Copy diagnostics | Small button at the bottom; copies a redacted report for bug reports. |
| About | Small button at the bottom; plugin name, summary, version and repository address. |

## Card data, languages and caching

- Card metadata comes from [HearthstoneJSON](https://hearthstonejson.com/): one database per
  locale, fetched from `https://api.hearthstonejson.com/v1/latest/<locale>/cards.json`.
- The settings page manages two databases: **English (enUS)** and **Simplified Chinese
  (zhCN)**. The interface language selects which one is used; the engine still understands
  all fourteen HearthstoneJSON locales, so more interface languages can be added later.
- Each database is cached as `cache/cards-<locale>.json` and reported with its size and
  state in *Download resources*. Switching language reloads a cached file; it only downloads
  when that language has no cache yet, so no data is downloaded twice.
- Card art is language independent. Tiles live in `cache/images/`, are shared by every
  language and are never evicted by a size cap. *Download all card art* fetches every unique
  Card ID in the loaded database, skips files already on disk (so an interrupted run resumes
  where it stopped), ignores duplicates and retries failures once. A card the art server has
  no tile for (HTTP 404) is counted separately as *without art* instead of as a failure and is
  not requested again in that session. Progress reports finished cards only, so a card that
  fails once and then succeeds is counted as a success and the bar never exceeds 100%.
- Each database and the art cache have their own delete button with a confirmation prompt.
  Deleting one database keeps the other one and all art; deleting art keeps both databases.
- Until a newly selected database finishes downloading, the HUD keeps showing the previous
  language's names instead of falling back to raw card IDs. Switching again while a download
  is still running discards that download, so an older language can never overwrite the one
  you just picked.
- Reloading the plugin keeps the selected language and never re-downloads existing caches.

The HUD renderer builds one font atlas that covers Latin, Cyrillic, Chinese, Japanese, Korean
and Thai so that card names from any locale render correctly.

## Reading the HUD

**Match header** – state, current turn, and how many cards the opponent has in hand and in deck.

**Your remaining deck** – one row per card with the copies left. `?` means the information is
not known yet, `>=n` means "at least n". Exhausted cards can be hidden in the settings.

**Your plays / Opponent plays** – newest first. A label shows where a card came from when the
game reports it (original card, copied, generated by an effect, transformed, gained by the
opponent). The opponent's unknown cards stay unknown; the plugin never invents identities.

**Arena panel** – during hero, hero power and card selection the left panel lists the three
candidates with their arena score; the recommended one is highlighted. The right panel is a
single `Selected X/30` list sorted by mana cost, then by name, with duplicates kept. If a
memory read fails while cards are already known, the title becomes
`Selected X/30 (count unconfirmed)` until the next successful read.

## Arena helper (read-only memory)

The arena panel is fed by the game's own draft objects (`DraftManager.m_draftDeck`, and
`m_undergroundDraftDeck` in underground drafts). This is why it is opt-in:

- The reader only reads process memory; it never writes to the game.
- Selected cards come **only** from memory. Arena.log is not used for counting, because
  simply previewing a candidate can make the game write several identical
  `Client chooses` lines.
- The reader is written for Unity 6000.3 x64 / `mono-2.0-bdwgc.dll` / `Assembly-CSharp`.
  On a different build it reports "incompatible" and stops instead of guessing.
- The deck is replaced as a whole on every snapshot, so nothing is appended twice. A new
  arena, a new game process, or a return to hero selection clears the previous list;
  a failed read keeps the last list and marks it unconfirmed.

## Ratings data

Both ratings are static snapshots shipped with the plugin; nothing is fetched at runtime and
nothing is re-scored locally.

- **Arena card ratings**: [HearthArena](https://www.heartharena.com/tierlist) tier-list
  snapshot from 2026-11-14 (4240 entries across 11 classes and neutral). Cards without a
  score show *No rating*; the plugin does not estimate one.
- **Arena class win rates**: Firestone / Zero-to-Heroes public arena statistics snapshot from
  2026-11-14, aggregated per class for normal and underground arena separately.

Provenance details: [docs/ARENA_RATINGS_SOURCE.md](docs/ARENA_RATINGS_SOURCE.md),
[docs/ARENA_CLASS_RATINGS_SOURCE.md](docs/ARENA_CLASS_RATINGS_SOURCE.md) (Chinese, with the
source URLs and capture times).

## Troubleshooting

**The HUD does not appear.**
Check that *Show HUD* is on and the plugin is enabled. The renderer only runs on Linux x86_64;
on other systems starting it fails with a message. Renderer output is written to
`renderer.log` in the plugin's runtime directory, and *Copy diagnostics* includes its tail.

**Cards show their IDs instead of names.**
The card database is not loaded yet: wait for the first download, or press *Retry card data
download* in *Download resources*. The plugin still tracks cards correctly with IDs.

**`Selected X/30 (count unconfirmed)` stays visible.**
A memory read failed and the last known list is being shown. The diagnostics section
`[Arena Memory]` reports the error code; the title recovers automatically on the next
successful read.

**The arena panel is empty.**
*Arena helper* is off, you are not in a draft screen, or the game build is not supported.
Without memory access the panel has no data by design — there is no log fallback.

**A warning says the logs are not ready.**
Hearthstone must be fully restarted after the plugin edits `log.config`. Close the game
completely (not just the match) and start it again.

**Names appear in the wrong language.**
The card database follows the interface language. Change *Language options*, or delete the
wrongly loaded database in *Download resources* so it is fetched again.

**Art takes a lot of disk space.**
There is no cache size cap any more. Delete the art in *Download resources*; the next cards
you see are downloaded again on demand.

**Diagnostics contain some Chinese text.**
The panel and HUD follow your interface language. Diagnostics are a technical report: field
names are English, and a few low-level messages from log configuration and process discovery
are still Chinese.

## Limitations

- Linux x86_64 only (SteamOS, Bazzite, …). There is no Windows or macOS build.
- Requires Decky Loader; the plugin is not a standalone application.
- The read-only arena reader supports the Unity 6000.3 x64 build listed above. Other builds
  report incompatibility; nothing is guessed.
- Once the memory reader is unavailable the arena panel shows nothing: selected cards are
  deliberately not reconstructed from Arena.log.
- Draft order is unknown by design; selected cards are sorted by mana cost and name, not by
  pick order.
- Ratings and class win rates are static snapshots and may lag the live arena pool.
- Card tracking depends on Hearthstone's text logs. Cards the game does not reveal stay
  unknown, and counts can be shown as lower bounds.
- The HUD builds a 64 MB font atlas while it runs, so it is not started on very low-memory
  systems unless you enable it.

## Credits, licenses and data sources

This plugin is MIT licensed ([LICENSE](LICENSE)). Third-party notices are collected in
[licenses/THIRD_PARTY.md](licenses/THIRD_PARTY.md); the list below makes clear what is
original work and what is not.

**Own implementation.** The Decky plugin backend, the arena memory reader, the arena panel
logic and the native OpenGL HUD renderer are written for this project.

**Vendored or adapted code (MIT).**
[hs-decktracker-linux](https://github.com/justfaked/hs-decktracker-linux) by *justfaked*,
commit `649534be99f35cb499ed2fae371625bd04b95b1d`: `engine/power.py` (Power.log parser) and
`engine/deckstring.py` (deck code decoder) are vendored, with only postponed annotation
evaluation changed; `engine/tracker.py` and `engine/cards.py` adapt its Decks.log header and
card-cache approach. License text:
[licenses/hs-decktracker-linux-MIT.txt](licenses/hs-decktracker-linux-MIT.txt).

**Card data and art.** [HearthstoneJSON](https://hearthstonejson.com/) (HearthSim) provides
card metadata and tile images. The site documentation is CC0, but the game data and artwork
remain © Blizzard Entertainment, All Rights Reserved; they are not relicensed under MIT. This
project downloads data at runtime and never bundles a card-image collection.

**Ratings.** Card tier list from [HearthArena](https://www.heartharena.com/tierlist); class
win rates from Firestone / [Zero-to-Heroes](https://www.zerotoheroes.com/) public statistics.
Both are third-party data, captured once and stored as JSON snapshots.

**Bundled assets.** Noto Sans CJK SC and Noto Sans Thai (SIL OFL 1.1,
[licenses/Noto-OFL.txt](licenses/Noto-OFL.txt)); Mozilla/certifi CA bundle (MPL-2.0,
[licenses/certifi-MPL-2.0.txt](licenses/certifi-MPL-2.0.txt)).

**Native dependencies** (built by CI, licenses copied into the release): GLFW (zlib/libpng),
Dear ImGui (MIT), nlohmann/json (MIT), stb (MIT / public domain).

**Frontend dependencies**: Decky Loader with `@decky/api` and `@decky/ui`; icons from
`react-icons` (Font Awesome Free, CC BY 4.0).

**Reference only** (ideas and layout comparisons, no copied code): OverLaid, the official
Decky plugin template, and Loadout — see `licenses/THIRD_PARTY.md` for the exact commits.

## Hover previews and deck names

Hover any visible HUD card row for 200 ms to see its full card render. The preview
keeps its aspect ratio and chooses a position inside the overlay, preferring space
beside the hovered row. Mouse position is read once per rendering frame through
X11; the window retains its empty input shape and does not intercept game clicks.
Hit regions come from the visible, clipped rows of the current page, in window
coordinates (framebuffer DPI scaling is left to ImGui).

Full cards use HearthstoneJSON's documented
[card render API](https://hearthstonejson.com/docs/images.html),
`/v1/render/latest/{locale}/512x/{card_id}.png`. These include the frame and text,
whereas tiles contain only cropped artwork. A missing localized render falls back
to English. Only hovered cards are requested; there is no bulk full-card download.
`cache/full-cards/<locale>/` is separate from tiles, limited to 256 MiB and pruned
by last use when a new image is saved. The renderer retains at most 12 full-card
textures. Network and CPU decode run in background workers; GL upload runs on the
render thread. Workers are drained when the plugin or renderer stops.

When Hearthstone is running without a match, a plain “Waiting for match” label
appears at the remaining-deck position, following the HUD and own-deck switches.
It does not depend on the match-summary switch and is suppressed by arena drafting.
Confirmed inactive drafts clear their selected cards; temporary read failures keep
the last valid selection marked unconfirmed.

The original-deck heading uses the name from the queue-time Decks.log block that
supplied the current match's deck definition. It never uses a later or previous
match's name; missing names retain “Original deck”. Arena matches use “Arena ·
<class>”. Added/transformed cards retain their separate group.

### Diagnosing hover previews

Copy diagnostics now includes **Hover Preview**, with separate renderer and downloader
states. Mouse detection uses the X11 root pointer translated into the overlay client,
then scaled to ImGui display coordinates; HUD scale is applied only to card geometry.
The empty X11 input shape and ImGui NoInputs flags remain enabled.

- `pointer_unavailable`: root pointer query or client translation failed; inspect
  `query_ok`, `translated`, client/display sizes and framebuffer scale.
- `no_card_regions` / `no_hit`: no visible clipped card rectangles, or the pointer
  lies outside them. Compare `position`, `first_region`, and `hit_region`.
- `hover_delay`: the 200 ms dwell interval has not elapsed.
- `request_write_failed` / downloader `request_error`, `locale_mismatch`, or
  `request_expired`: inspect the renderer-to-backend hover.json handoff.
- Downloader `downloading`, `ready`, `cached`, or `download_failed`: shows the card,
  source locale and bounded error details. A failed request retries after 60 seconds
  while still hovered; duplicate requests are coalesced.
- Renderer `awaiting_texture` with texture `missing_file`, `decode_failed`, or
  `upload_failed`: identifies the cache/decode/upload stage; `render_failed` reports
  render exceptions or GL errors. `rendered` means the image was submitted without
  a detected error, not a guarantee of compositor visibility.

Renderer details are in runtime `diagnostic.json`; request IPC is `hover.json`.
No additional mouse-polling thread or input-capturing window is created.

Hover registration diagnostics also record the current `registration_frame`,
`render_context`, `card_rows_submitted`, `registered_ids` (up to 12), and per-panel
`available`, `submitted`, `sections`, `rejected_id`, `clipped`, `registered` and
`skipped` counters. `first_registration_attempt` contains the original draw rectangle
and clip rectangle, including when registration rejects every row.

`registration_state=no_cards` means the active render branch has no input rows
(e.g. a completed match); `no_submitted_cards` means rows exist but no card row was
submitted (check skipped panels/section rows); `all_filtered` means submitted card
rows were rejected by ID or clipping; `registered` means hit rectangles reached the
preview. A `no_hit` preview with registered rows is different from a download failure.
`last_nonempty_registration` and `last_hit` retain bounded snapshots with frame
numbers after the match ends. They are historical evidence, not current hit regions.
All panels explicitly receive the same frame-local collector, and the preview reads
it only after panel submission; no global card-hit list is cleared between panels.

`pointer_history` counts valid pointer samples and position changes while cards
are registered, retaining observed bounds and time since the last observed change.
`last_request` records the most recent card request even after the pointer leaves.
Diagnostics also show Game X11 Display and Renderer display to help identify separate
X servers. A successful XQueryPointer call alone does not prove its coordinates track
the cursor over the game; compare history while deliberately moving across card rows.
