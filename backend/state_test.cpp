#include "hud_state.h"
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
    if(arena_rows(arena,false).size()!=4 || arena["count"]!=0)return 26; // Display never mutates counts.
    arena["history_picks"]=json::array({rated,rated});good["arena_state"]=arena;
    if(!valid_hud_state(good)||arena_rows(arena,false).size()!=7)return 38;
    bad=good;bad["arena_state"]["history_picks"][0]["id"]=42;if(valid_hud_state(bad))return 39;
    arena["stage"]="hero_selection";arena["show_count"]=false;good["arena_state"]=arena;
    if(!valid_hud_state(good))return 27;
    bad=good;bad["arena_state"]["stage"]="invented";if(valid_hud_state(bad))return 28;
    bad=good;bad["arena_state"]["candidates"][0]["hero_stats"]={{"winrate",2},{"games",10},{"rank",1},{"of",11}};if(valid_hud_state(bad))return 29;
    bad=good;bad["arena_state"]["show_count"]="no";if(valid_hud_state(bad))return 30;
    std::cout<<"Native HUD state validation: passed\n";
}
