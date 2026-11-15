#pragma once
#include <nlohmann/json.hpp>
#include <cmath>
#include <algorithm>
inline bool valid_arena_state(const nlohmann::json& a){
    if(!a.is_object())return false;
    for(const auto* k:{"visible","drafting","exact"})if(!a.contains(k)||!a[k].is_boolean())return false;
    for(const auto* k:{"mode","class_name"})if(!a.contains(k)||!a[k].is_string()||a[k].get_ref<const std::string&>().size()>256)return false;
    if(a.contains("count_exact")&&!a["count_exact"].is_boolean())return false;
    if(a.contains("show_count")&&!a["show_count"].is_boolean())return false;
    if(a.contains("stage")&&(!a["stage"].is_string() || (a["stage"]!="none" && a["stage"]!="hero_selection" && a["stage"]!="card_selection" && a["stage"]!="hero_power_selection" && a["stage"]!="drafting" && a["stage"]!="redrafting")))return false;
    if(!a.contains("count")||!a["count"].is_number_integer())return false;
    for(const auto* k:{"candidates","picks","redraft_picks","history_picks"}){
        if(std::string(k)=="history_picks"&&!a.contains(k))continue;
        if(!a.contains(k)||!a[k].is_array()||a[k].size()>(std::string(k)=="candidates"?3:100))return false;
        for(const auto& r:a[k]){
            if(!r.is_object())return false;
            for(const auto* field:{"id","name","image","rating_label","tier"})if(!r.contains(field)||!r[field].is_string()||r[field].get_ref<const std::string&>().size()>4096)return false;
            if(r.contains("hero_row")&&!r["hero_row"].is_boolean())return false;
            if(r.contains("class_name")&&(!r["class_name"].is_string()||r["class_name"].get_ref<const std::string&>().size()>256))return false;
            if(r.contains("hero_stats")&&!r["hero_stats"].is_null()){
                const auto& stats=r["hero_stats"];
                if(!stats.is_object()||!stats.contains("winrate")||!stats["winrate"].is_number()||!std::isfinite(stats["winrate"].get<double>())||stats["winrate"].get<double>()<0||stats["winrate"].get<double>()>1)return false;
                for(const auto* key:{"games","rank","of"})if(!stats.contains(key)||!stats[key].is_number_integer()||stats[key].get<long long>()<1)return false;
                if(stats["rank"].get<long long>()>stats["of"].get<long long>())return false;
            }
            if(!r.contains("best")||!r["best"].is_boolean())return false;
            if(!r.contains("score")||(!r["score"].is_null()&&(!r["score"].is_number()||!std::isfinite(r["score"].get<double>()))))return false;
        }
    }
    return true;
}
inline bool valid_hud_state(const nlohmann::json& s) {
    if(!s.is_object() || !s.contains("updated") || !s["updated"].is_number())return false;
    for(const auto* k:{"scale","opacity","x","y","right_x","right_y","panel_width","font_size"})
        if(s.contains(k) && (!s[k].is_number() || !std::isfinite(s[k].get<double>())))return false;
    for(const auto* k:{"visible","own_deck","opponent_deck","opponent_hand","card_images","chinese_names","own_played","opponent_played","show_summary","hide_exhausted"})
        if(s.contains(k) && !s[k].is_boolean())return false;
    if(s.contains("arena_state")&&!valid_arena_state(s["arena_state"]))return false;
    if(!s.contains("tracking") || !s["tracking"].is_object())return false;
    const auto& t=s["tracking"];
    if(!t.contains("status") || !t["status"].is_string() || !t.contains("turn") || !t["turn"].is_number_integer())return false;
    for(const auto* k:{"own_label","own_class","opponent_class"})if(t.contains(k) && !t[k].is_string())return false;
    for(const auto* k:{"opponent_hand","opponent_deck","own_deck","own_remaining","opponent_unknown"})if(t.contains(k) && !t[k].is_null() && !t[k].is_number_integer())return false;
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
    if(value.is_number_integer())return value.get<int>()==1?"":std::to_string(value.get<int>());
    const auto lower=row.value("remaining_lower_bound",nlohmann::json());
    if(own && lower.is_number_integer() && lower.get<int>()>0)return ">="+std::to_string(lower.get<int>());
    return "?";
}

// Presentation only: model rows/events keep their independent quantities.
inline nlohmann::json deck_rows(const nlohmann::json& t,bool hide_exhausted){
    using nlohmann::json;
    auto rows=json::array();
    for(const auto* key:{"own","own_added"}){
        if(!t.contains(key))continue;
        bool heading=false;
        for(const auto& r:t[key]){
            if(hide_exhausted && r.value("remaining",json())==json(0))continue;
            if(!heading){rows.push_back({{"section",true},{"name",std::string(key)=="own"?"原始牌库":"后加入 / 变形 · 当前在库"}});heading=true;}
            auto row=r;row["deck_row"]=true;rows.push_back(row);
        }
    }
    return rows;
}
inline nlohmann::json played_rows(const nlohmann::json& t,const char* key){
    auto rows=nlohmann::json::array();
    if(t.contains(key))for(auto it=t[key].rbegin();it!=t[key].rend();++it){auto r=*it;r["event"]=true;rows.push_back(r);}
    return rows;
}
struct HudRegion {float y=0,height=0;bool visible=false;};
struct PanelLayout {int per_page,pages,page;float height;};
inline PanelLayout panel_layout(size_t rows,float font_size,float scale,float available,long long tick,float padding=16){
    const float stride=(std::max(32.f,font_size+8)+2)*scale;
    const float heading=(19.2f+2)*scale;
    const int per_page=std::max(1,int((available-padding-heading*2)/stride));
    const int pages=std::max(1,int((rows+per_page-1)/per_page));
    const int page=int(tick%pages);
    const size_t shown=std::min(size_t(per_page),rows-size_t(page*per_page));
    return {per_page,pages,page,rows?std::min(available,padding+heading*(pages>1?2:1)+shown*stride-2*scale):0.f};
}
struct LeftRegions {HudRegion opponent,own;};
inline LeftRegions left_regions(bool opponent,bool own,float y,float height,float gap){
    if(opponent && own){const float half=std::max(0.f,(height-gap)/2);return {{y,half,true},{y+half+gap,half,true}};}
    if(opponent)return {{y,height,true},{}};
    if(own)return {{},{y,height,true}};
    return {};
}

inline nlohmann::json arena_rows(const nlohmann::json& a,bool candidates){
    using nlohmann::json;auto rows=json::array();
    const auto append=[&](const char* key){for(const auto& r:a[key]){auto row=r;row["arena_row"]=true;rows.push_back(row);}};
    // One flat list: the selected deck (mana order) or the three candidates.
    // No section headers, order markers or recovery groups are rendered.
    append(candidates?"candidates":"picks");
    return rows;
}
