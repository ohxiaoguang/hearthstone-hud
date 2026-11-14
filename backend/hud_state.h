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
    for(const auto* k:{"own","opponent"}) {
        if(!t.contains(k) || !t[k].is_array() || t[k].size()>256)return false;
        for(const auto& r:t[k]) {
            if(!r.is_object())return false;
            for(const auto* field:{"id","name","image"})if(!r.contains(field)||!r[field].is_string()||r[field].get_ref<const std::string&>().size()>4096)return false;
            for(const auto* field:{"cost","count","remaining","initial","drawn","used","known_in_deck","remaining_lower_bound"})
                if(r.contains(field)&&!r[field].is_null()&&!r[field].is_number_integer())return false;
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
