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
    auto event=json{{"id","A"},{"card_id","A"},{"name","甲"},{"image",""},{"turn",2},{"order",1},{"origin_label","原始牌"},{"in_starting_deck",true}};
    good["tracking"]["own_played"]=json::array({event,event});
    good["tracking"]["own_added"]=json::array({json{{"id","A"},{"name","甲"},{"image",""},{"remaining",1}}});
    if(!valid_hud_state(good))return 8;
    auto rows=hud_sections(good["tracking"],true);
    if(rows.size()!=5 || !rows[0].value("section",false) || !rows[3].value("event",false))return 9;
    bad=good;bad["tracking"]["own_played"][0]["turn"]="bad";if(valid_hud_state(bad))return 10;
    bad=good;bad["tracking"]["own_added"][0]["generated"]="bad";if(valid_hud_state(bad))return 11;
    std::cout<<"Native HUD state validation: passed\n";
}
