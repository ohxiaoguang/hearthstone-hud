# Third-party notices

- engine/power.py: hs-decktracker-linux, Copyright (c) 2026 justfaked, MIT. Vendored commit 649534be99f35cb499ed2fae371625bd04b95b1d. Only local change: postponed annotation evaluation for Python 3.9. License included alongside this file.
- NotoSansCJKsc-Regular.otf: Noto CJK, SIL OFL 1.1, license included (licenses/Noto-OFL.txt). Downloaded 2026-11-14 from https://github.com/notofonts/noto-cjk/tree/main/Sans/OTF/SimplifiedChinese . Unmodified font; reserved names remain unchanged.
- NotoSansThai-Regular.ttf: Noto Sans Thai, SIL OFL 1.1, same license file. Downloaded 2026-11-15 from https://github.com/notofonts/noto-fonts/tree/main/hinted/ttf/NotoSansThai . Unmodified font, merged into the HUD font atlas at runtime so Thai card names render.
- GLFW 3.3.10: zlib/libpng license; build-native.sh copies original license to distribution.
- Dear ImGui 1.90.9: MIT; original license copied by native build.
- nlohmann/json 3.11.3: MIT; original license copied by native build.
- stb f0569113c93ad095470c54bf34a17b36646bbbb5: dual MIT/public domain; original license copied by native build.
- Frontend uses @decky/api, @decky/ui, @decky/rollup, react-icons and tslib; upstream notices are retained in node_modules for development. Runtime modules supplied by Decky are external. React-icons icon attribution: Font Awesome Free, CC BY 4.0, https://fontawesome.com/license/free .

Reference-only audits (no copied native/UI implementation): OverLaid 9fe79cd38610d28890c76c3e6da5fbd918e406bc; official Decky template 90d0780e882a17f5714fc6de044c645f22608290; Loadout e99b26384f1e7b3405a5bd8b194449908f85f1f2.

- engine/deckstring.py is additionally vendored from the same hs-decktracker-linux commit and MIT license, with postponed annotations for Python 3.9. DeckLog's confirmed headers and deck-code approach are adapted independently from decks.py; cards.py's HearthstoneJSON cache approach is independently adapted with bounded asynchronous downloads. No memory or arena modules are imported.
- Card metadata: https://api.hearthstonejson.com/v1/latest/{LOCALE}/cards.json for all fourteen HearthstoneJSON locales (enUS, zhCN, zhTW, deDE, esES, esMX, frFR, itIT, jaJP, koKR, plPL, ptBR, ruRU, thTH). Card images: https://art.hearthstonejson.com/v1/tiles/{CARD_ID}.png . HearthstoneJSON site documentation is CC0, while game data and art remain Copyright Blizzard Entertainment, All Rights Reserved. These are not relicensed under this project's MIT license. See https://hearthstonejson.com/ and https://hearthstonejson.com/docs/images.html . The API permits use with caching and asks commercial users to contact HearthSim; this project does not bundle a card-image collection.

- assets/certs/cacert.pem: unmodified Mozilla/certifi public root CA data, MPL-2.0. Source https://github.com/certifi/python-certifi at ca446ca404ff3b962a0193f36e03d1eabb231968. Original upstream license notice is included as certifi-MPL-2.0.txt. No certifi Python package is installed. Bundle SHA256 is recorded in assets/certs/README.md.
