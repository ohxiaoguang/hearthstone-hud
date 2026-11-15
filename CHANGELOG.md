# Changelog

User-visible changes per version. 中文版：[CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)

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
