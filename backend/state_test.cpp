#include "hud_state.h"
#include "card_regions.h"
#include <iostream>
int main(){
    using nlohmann::json;
    auto good=json::parse(R"({"updated":1,"tracking":{"status":"playing","turn":2,"own":[],"opponent":[]}})");
    if(!valid_hud_state(good)||valid_hud_state(json::array()))return 1;
    auto bad=good;bad["tracking"]["own"]=42;if(valid_hud_state(bad))return 2;
    bad=good;bad["visible"]="true";if(valid_hud_state(bad))return 3;
    bad=good;bad["tracking"]["own"].push_back({{"id","A"}});if(valid_hud_state(bad))return 4;
    if(card_count_label(json{{"remaining",nullptr},{"known_in_deck",0}},true)!="?")return 5;
    if(card_count_label(json{{"remaining",nullptr},{"remaining_lower_bound",2}},true)!=">=2")return 6;
    if(card_count_label(json{{"remaining",0}},true)!="0")return 7;
    if(card_count_label(json{{"remaining",1}},true)!="")return 33;
    if(card_count_label(json{{"remaining",2}},true)!="2")return 34;
    if(card_count_label(json{{"remaining",nullptr},{"remaining_lower_bound",1}},true)!=">=1")return 35;
    const auto small=panel_layout(3,22,1,800,0),large=panel_layout(12,22,1,800,0);
    if(small.height>=large.height || small.height>=800 || panel_layout(0,22,1,800,0).height!=0)return 36;
    const auto paged=panel_layout(100,30,1,300,0);
    if(paged.pages<2 || paged.height>300 || paged.per_page<1)return 37;
    auto event=json{{"id","A"},{"card_id","A"},{"name","甲"},{"image",""},{"turn",2},{"order",1},{"origin_label","原始牌"},{"in_starting_deck",true}};
    good["tracking"]["own_played"]=json::array({event,event});
    good["tracking"]["own_added"]=json::array({json{{"id","A"},{"name","甲"},{"image",""},{"remaining",1}}});
    if(!valid_hud_state(good))return 8;
    auto rows=deck_rows(good["tracking"],false);
    if(rows.size()!=2 || !rows[0].value("section",false) || !rows[1].value("deck_row",false))return 9;
    // Group headings come from the backend labels; without them the renderer
    // falls back to English, never to another language.
    if(rows[0].value("name","")!="Added / transformed · currently in deck")return 48;
    const auto localized=deck_rows(good["tracking"],false,json{{"deck_original","原始牌库"},{"deck_added","后加入 / 变形 · 当前在库"}});
    if(localized.size()!=2 || localized[0].value("name","")!="后加入 / 变形 · 当前在库")return 49;
    const auto plain=json{{"own",json::array({json{{"id","B"},{"name","B"},{"image",""},{"remaining",1}}})}};
    if(deck_rows(plain,false)[0].value("name","")!="Original deck")return 50;              // English default.
    if(deck_rows(plain,false,json{{"deck_original","原始牌库"}})[0].value("name","")!="原始牌库")return 51;
    if(deck_rows(plain,false,json{{"deck_added","x"}})[0].value("name","")!="Original deck")return 52; // Missing key.
    auto plays=played_rows(good["tracking"],"own_played");
    if(plays.size()!=2 || !plays[0].value("event",false))return 12;
    good["tracking"]["own"].push_back({{"id","B"},{"name","乙"},{"image",""},{"remaining",0}});
    if(deck_rows(good["tracking"],false).size()!=4 || deck_rows(good["tracking"],true).size()!=2)return 13;
    good["tracking"]["own"].push_back({{"id","C"},{"name","丙"},{"image",""},{"remaining",nullptr}});
    if(deck_rows(good["tracking"],true).size()!=4)return 14; // Unknown is never hidden as exhausted.
    auto both=left_regions(true,true,80,800,8);
    if(!both.own.visible || !both.opponent.visible || both.opponent.height!=396 || both.own.height!=396 || both.own.y!=484)return 15;
    auto one=left_regions(false,true,80,800,8);
    if(one.opponent.visible || !one.own.visible || one.own.height!=800 || one.own.y!=80)return 16;
    one=left_regions(true,false,80,800,8);
    if(!one.opponent.visible || one.own.visible || one.opponent.height!=800)return 17;
    auto none=left_regions(false,false,80,800,8);if(none.own.visible || none.opponent.visible)return 18;
    bad=good;bad["panel_width"]="wide";if(valid_hud_state(bad))return 19;
    bad=good;bad["show_summary"]="yes";if(valid_hud_state(bad))return 20;
    bad=good;bad["font_size"]="large";if(valid_hud_state(bad))return 31;
    good["font_size"]=28;if(!valid_hud_state(good))return 32;
    bad=good;bad["tracking"]["own_played"][0]["turn"]="bad";if(valid_hud_state(bad))return 10;
    bad=good;bad["tracking"]["own_added"][0]["generated"]="bad";if(valid_hud_state(bad))return 11;
    auto rated=json{{"id","A"},{"name","甲"},{"image",""},{"rating_label","80"},{"tier","Good"},{"score",80},{"best",true}};
    auto arena=json{{"visible",true},{"drafting",true},{"exact",false},{"mode","DRAFTING"},{"class_name","法师"},{"count",0},{"candidates",json::array({rated,rated,rated})},{"picks",json::array()},{"redraft_picks",json::array()}};
    good["arena_state"]=arena;if(!valid_hud_state(good))return 21;
    if(arena_rows(arena,true).size()!=3 || !arena_rows(arena,true)[0].value("arena_row",false))return 22;
    bad=good;bad["arena_state"]["candidates"].push_back(rated);if(valid_hud_state(bad))return 23;
    bad=good;bad["arena_state"]["candidates"][0]["score"]="fake";if(valid_hud_state(bad))return 24;
    bad=good;bad["arena_state"]["visible"]="yes";if(valid_hud_state(bad))return 25;
    arena["picks"].push_back(rated);arena["redraft_picks"].push_back(rated);
    const auto picked=arena_rows(arena,false);
    if(picked.size()!=1 || picked[0].value("section",false) || !picked[0].value("arena_row",false) || arena["count"]!=0)return 26; // Flat selected deck, one row per pick; display never mutates counts.
    if(arena_picked_title(arena)!="Selected 0/30")return 40; // English fallback, no hint while exact.
    arena["count"]=6;arena["count_exact"]=false;
    if(arena_picked_title(arena)!="Selected 6/30 (count unconfirmed)")return 41; // Retained deck after a failed read.
    arena["count_exact"]=true;
    if(arena_picked_title(arena)!="Selected 6/30")return 42; // Hint clears when a good read returns.
    arena["history_picks"]=json::array({rated,rated});good["arena_state"]=arena;
    if(!valid_hud_state(good)||arena_rows(arena,false).size()!=1)return 38; // Legacy history rows are accepted but never rendered.
    bad=good;bad["arena_state"]["history_picks"][0]["id"]=42;if(valid_hud_state(bad))return 39;
    good["ui_language"]="zh-CN";good["show_card_names"]=true;good["labels"]=json{{"arena_card","竞技场 · 卡牌选择"}};
    if(!valid_hud_state(good))return 43; // A localized state is still valid.
    bad=good;bad["ui_language"]="frFR";if(valid_hud_state(bad))return 44; // Card locales are not interface locales.
    bad=good;bad["show_card_names"]="yes";if(valid_hud_state(bad))return 45;
    bad=good;bad["labels"]=json::array();if(valid_hud_state(bad))return 46;
    bad=good;bad.erase("show_card_names");bad["chinese_names"]=true;if(!valid_hud_state(bad))return 47; // Legacy flag still parses.
    good["ui_language"]="en";good.erase("labels");good.erase("show_card_names");
    arena["stage"]="hero_selection";arena["show_count"]=false;good["arena_state"]=arena;
    if(!valid_hud_state(good))return 27;
    bad=good;bad["arena_state"]["stage"]="invented";if(valid_hud_state(bad))return 28;
    bad=good;bad["arena_state"]["candidates"][0]["hero_stats"]={{"winrate",2},{"games",10},{"rank",1},{"of",11}};if(valid_hud_state(bad))return 29;
    bad=good;bad["arena_state"]["show_count"]="no";if(valid_hud_state(bad))return 30;
    good["card_locale"]="zhCN";good["idle_visible"]=true;good["tracking"]["deck_name"]="My mage";
    if(!valid_hud_state(good))return 48;
    bad=good;bad["card_locale"]="../x";if(valid_hud_state(bad))return 49;
    bad=good;bad["tracking"]["deck_name"]=123;if(valid_hud_state(bad))return 50;
    auto named=good["tracking"];named["own"]=json::array({{{"id","CARD_A"},{"remaining",2}}});
    if(deck_rows(named,false)[0]["name"]!="My mage")return 51;
    named["deck_name"]="";if(deck_rows(named,false)[0]["name"]!="Original deck")return 52;
    auto point=hover_display_point(640,360,2560,1440,1280,720);
    if(point.x!=320 || point.y!=180)return 53;
    point=hover_display_point(160,90,1280,720,2560,1440,10,20);
    if(point.x!=330 || point.y!=200)return 54;
    if(!hover_contains(330,200,320,190,400,250))return 55;
    if(hover_contains(400,200,320,190,400,250) || hover_contains(330,200,400,190,320,250))return 56;
    if(hover_display_point(10,10,0,0,1280,720).x!=-1)return 57;
    // Arena and match rows append to the same frame; registration is independent
    // of texture availability and ImGui input handling.
    CardRegions regions(123);
    regions.panel("remaining",3);regions.section("remaining");
    regions.add("remaining","CORE_CS2_029",{100,100},{420,132},{0,0},{1920,1080});
    regions.add("remaining","VAC_001t2",{100,134},{420,166},{0,0},{1920,1080});
    regions.panel("arena-offer",3);
    regions.add("arena-offer","HERO_08",{500,100},{820,132},{0,0},{1920,1080});
    regions.add("arena-offer","EDR_001",{500,134},{820,166},{0,0},{1920,1080});
    regions.add("arena-offer","TEST_CARD",{500,168},{820,200},{0,0},{1920,1080});
    if(regions.hits.size()!=5 || regions.diagnostic()["registration_frame"]!=123)return 58;
    if(!regions.hit(110,110) || regions.hit(110,110)->id!="CORE_CS2_029")return 59;
    if(!regions.hit(510,110) || regions.hit(510,110)->source!="arena-offer")return 60;
    if(regions.hit(450,110) || regions.hit(820,110))return 61;
    CardRegions next_frame(124);
    if(!next_frame.hits.empty() || regions.hits.size()!=5)return 62;
    if(next_frame.diagnostic()["registration_state"]!="no_cards")return 63;
    // Invalid IDs and offscreen rows are diagnosed separately; partial clipping
    // uses the visible part of the actual draw rectangle, without rescaling.
    CardRegions filtered(125);filtered.panel("remaining",3);
    filtered.add("remaining","dbf:42",{100,100},{420,132},{0,0},{1920,1080});
    filtered.add("remaining","CARD_A",{100,1100},{420,1132},{0,0},{1920,1080});
    filtered.add("remaining","CARD_B",{100,100},{420,132},{110,110},{400,130});
    const auto registration=filtered.diagnostic();
    if(registration["panels"]["remaining"]["rejected_id"]!=1 || registration["panels"]["remaining"]["clipped"]!=1)return 64;
    if(filtered.hit(105,115) || !filtered.hit(115,115) || filtered.hit(115,131))return 65;
    if(filtered.hits.size()!=1 || registration["registered_ids"][0]!="CARD_B")return 66;
    for(const auto* id:{"HERO_08","CORE_CS2_029","VAC_001t2","BOM_10_Card_001","TOY_123"})if(!safe_card_id(id))return 67;
    for(const auto* id:{"","../CARD","dbf:1","CARD.png"})if(safe_card_id(id))return 68;
    HoverPointerHistory history;
    history.observe(1,true,{1919,1079},true);history.observe(3,true,{1919,1079},true);
    if(history.diagnostic(3)["position_changes_with_cards"]!=0 || history.diagnostic(3)["seconds_since_observed_change"]!=2)return 69;
    history.observe(4,true,{100,110},true);
    if(history.diagnostic(4)["position_changes_with_cards"]!=1)return 70;
    history.observe(5,false,{0,0},true);history.observe(6,true,{0,0},false);
    if(history.diagnostic(6)["samples_with_cards"]!=3)return 71;
    // Regression: seven registered regions were visible, but the renderer :0
    // cursor stayed at (1919,1079). The game's :1 pointer must be selected.
    if(!separate_pointer_display(":1",":0") || separate_pointer_display(":0.0",":0") || separate_pointer_display("",":0"))return 72;
    if(local_x11_display("remote:1") || local_x11_display(":1.") || !local_x11_display(":1.0"))return 73;
    good["game_display"]=":1";if(!valid_hud_state(good))return 74;
    bad=good;bad["game_display"]="remote:1";if(valid_hud_state(bad))return 75;
    bad=good;bad["game_display"]=1;if(valid_hud_state(bad))return 76;
    point=hover_display_point(200,240,3840,2160,1920,1080);
    if(point.x!=100 || point.y!=120 || !hover_contains(point.x,point.y,8,107,258,142))return 77;
    auto preview=preview_size(256,384,1,1920,1080);
    if(preview.width!=256 || preview.height!=384 || preview.padding!=8)return 78;
    auto placeholder=preview_size(256,384,2,240,320);
    if(placeholder.width+2*placeholder.padding>224 || placeholder.height+2*placeholder.padding>304)return 79;
    if(std::abs(placeholder.width/placeholder.height-2.f/3.f)>.0001f)return 80;
    // A cached card and its loading placeholder reserve identical frame geometry.
    auto loaded=preview_size(256,384,2,240,320);
    if(placeholder.width!=loaded.width || placeholder.height!=loaded.height)return 81;
    good["full_card_generation"]=1;if(!valid_hud_state(good))return 82;
    bad=good;bad["full_card_generation"]=-1;if(valid_hud_state(bad))return 83;
    bad=good;bad["full_card_generation"]="1";if(valid_hud_state(bad))return 84;
    std::cout<<"Native HUD state validation: passed\n";
}
