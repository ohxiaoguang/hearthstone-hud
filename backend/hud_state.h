#pragma once
#include <nlohmann/json.hpp>
#include <cmath>
inline bool valid_hud_state(const nlohmann::json& s) {
    if(!s.is_object() || !s.contains("updated") || !s["updated"].is_number())return false;
    for(const auto* k:{"scale","opacity","x","y","right_x","right_y"})
        if(s.contains(k) && (!s[k].is_number() || !std::isfinite(s[k].get<double>())))return false;
    for(const auto* k:{"visible","own_deck","opponent_deck","opponent_hand","card_images","chinese_names"})
        if(s.contains(k) && !s[k].is_boolean())return false;
    if(!s.contains("tracking") || !s["tracking"].is_object())return false;
    const auto& t=s["tracking"];
    if(!t.contains("status") || !t["status"].is_string() || !t.contains("turn") || !t["turn"].is_number_integer())return false;
    for(const auto* k:{"own_label","own_class","opponent_class"})if(t.contains(k) && !t[k].is_string())return false;
    for(const auto* k:{"opponent_hand","opponent_deck","own_deck","opponent_unknown"})if(t.contains(k) && !t[k].is_null() && !t[k].is_number_integer())return false;
    for(const auto* k:{"own","opponent","own_added","own_played","opponent_seen","opponent_played"}) {
        const bool events=std::string(k)=="own_played" || std::string(k)=="opponent_played";
        if(!t.contains(k) && std::string(k)!="own" && std::string(k)!="opponent")continue;
        if(!t.contains(k) || !t[k].is_array() || t[k].size()>(events?65536:256))return false;
        for(const auto& r:t[k]) {
            if(!r.is_object())return false;
            for(const auto* field:{"id","name","image"})if(!r.contains(field)||!r[field].is_string()||r[field].get_ref<const std::string&>().size()>4096)return false;
            for(const auto* field:{"cost","count","remaining","initial","drawn","used","known_in_deck","remaining_lower_bound","turn","game_turn","order","entity_id","player_id","source_entity_id"})
                if(r.contains(field)&&!r[field].is_null()&&!r[field].is_number_integer())return false;
            for(const auto* field:{"origin","origin_label","source_card_id","card_id"})
                if(r.contains(field)&&(!r[field].is_string()||r[field].get_ref<const std::string&>().size()>4096))return false;
            for(const auto* field:{"generated","foreign","returned","shuffled_in","in_starting_deck","source_known"})
                if(r.contains(field)&&!r[field].is_boolean())return false;
        }
    }
    return true;
}

inline std::string card_count_label(const nlohmann::json& row,bool own){
    const auto value=row.value(own?"remaining":"count",nlohmann::json());
    if(value.is_number_integer())return std::to_string(value.get<int>());
    const auto lower=row.value("remaining_lower_bound",nlohmann::json());
    if(own && lower.is_number_integer() && lower.get<int>()>0)return ">="+std::to_string(lower.get<int>());
    return "?";
}

// Presentation only: event arrays stay unaggregated in IPC. Sections share the
// existing timed paging and never contribute to each other's quantities.
inline nlohmann::json hud_sections(const nlohmann::json& t,bool own){
    using nlohmann::json;
    auto rows=json::array();
    const auto section=[&](const char* key,const char* title,bool events){
        if(!t.contains(key)||t[key].empty())return;
        rows.push_back({{"section",true},{"name",title}});
        if(events){
            for(auto it=t[key].rbegin();it!=t[key].rend();++it){auto r=*it;r["event"]=true;rows.push_back(r);}
        }else for(const auto& r:t[key]){auto row=r;row["deck_row"]=own;rows.push_back(row);}
    };
    if(own){section("own","原始牌库",false);section("own_added","后加入 / 变形 · 当前在库",false);section("own_played","我方已打出（最近在前）",true);}
    else {section(t.contains("opponent_seen")?"opponent_seen":"opponent","对手公开卡牌",false);section("opponent_played","对手实际打出（最近在前）",true);}
    return rows;
}
