#include "hud_state.h"
#include <iostream>
int main(){
    using nlohmann::json;
    auto good=json::parse(R"({"updated":1,"tracking":{"status":"playing","turn":2,"own":[],"opponent":[]}})");
    if(!valid_hud_state(good)||valid_hud_state(json::array()))return 1;
    auto bad=good;bad["tracking"]["own"]=42;if(valid_hud_state(bad))return 2;
    bad=good;bad["visible"]="true";if(valid_hud_state(bad))return 3;
    bad=good;bad["tracking"]["own"].push_back({{"id","A"}});if(valid_hud_state(bad))return 4;
    std::cout<<"Native HUD state validation: passed\n";
}
