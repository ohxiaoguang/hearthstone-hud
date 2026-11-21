#pragma once
#include <nlohmann/json.hpp>
#include <cmath>
#include <string>
#include <algorithm>
// Only local addresses are allowed for the optional read-only game connection.
inline bool local_x11_display(const std::string& value){
    if(value.empty() || value.size()>32 || value[0]!=':')return false;
    bool digit=false,dot=false;
    for(size_t i=1;i<value.size();++i){
        if(value[i]>='0' && value[i]<='9'){digit=true;continue;}
        if(value[i]=='.' && !dot && digit){dot=true;digit=false;continue;}
        return false;
    }
    return digit;
}
inline bool separate_pointer_display(const std::string& game,const std::string& renderer){
    if(!local_x11_display(game))return false;
    const auto canonical=[](const std::string& value){return value.find('.')==std::string::npos?value+".0":value;};
    return canonical(game)!=canonical(renderer);
}
inline bool valid_arena_state(const nlohmann::json& a){
    if(!a.is_object())return false;
    for(const auto* k:{"visible","drafting","exact"})if(!a.contains(k)||!a[k].is_boolean())return false;
    for(const auto* k:{"mode","class_name"})if(!a.contains(k)||!a[k].is_string()||a[k].get_ref<const std::string&>().size()>256)return false;
    if(a.contains("count_exact")&&!a["count_exact"].is_boolean())return false;
    if(a.contains("show_count")&&!a["show_count"].is_boolean())return false;
    if(a.contains("stage")&&(!a["stage"].is_string() || (a["stage"]!="none" && a["stage"]!="hero_selection" && a["stage"]!="card_selection" && a["stage"]!="hero_power_selection" && a["stage"]!="drafting" && a["stage"]!="redrafting" && a["stage"]!="removal")))return false;
    if(!a.contains("count")||!a["count"].is_number_integer())return false;
    for(const auto* k:{"candidates","picks","redraft_picks","history_picks"}){
        if(std::string(k)=="history_picks"&&!a.contains(k))continue;
        if(!a.contains(k)||!a[k].is_array()||a[k].size()>(std::string(k)=="candidates"?3:100))return false;
        for(const auto& r:a[k]){
            if(!r.is_object())return false;
            for(const auto* field:{"id","name","image","rating_label","tier"})if(!r.contains(field)||!r[field].is_string()||r[field].get_ref<const std::string&>().size()>4096)return false;
            if(r.contains("hero_row")&&!r["hero_row"].is_boolean())return false;
            if(r.contains("suggest_remove")&&!r["suggest_remove"].is_boolean())return false;
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
inline bool valid_language(const nlohmann::json& s){
    if(s.contains("ui_language") && (!s["ui_language"].is_string() || (s["ui_language"]!="en" && s["ui_language"]!="zh-CN")))return false;
    // `show_card_names` supersedes the former `chinese_names` flag; either may be
    // present so an older state.json still parses.
    if(s.contains("show_card_names") && !s["show_card_names"].is_boolean())return false;
    if(s.contains("chinese_names") && !s["chinese_names"].is_boolean())return false;
    if(s.contains("labels") && !s["labels"].is_object())return false;
    return true;
}

inline bool valid_hud_state(const nlohmann::json& s) {
    if(!s.is_object() || !s.contains("updated") || !s["updated"].is_number())return false;
    if(!valid_language(s))return false;
    if(s.contains("full_card_generation") && (!s["full_card_generation"].is_number_integer() || s["full_card_generation"]<0 || s["full_card_generation"]>2147483647))return false;
    if(s.contains("game_display") && (!s["game_display"].is_string() ||
        (!s["game_display"].get_ref<const std::string&>().empty() && !local_x11_display(s["game_display"].get_ref<const std::string&>()))))return false;
    if(s.contains("idle_visible")&&!s["idle_visible"].is_boolean())return false;
    if(s.contains("card_locale")&&(!s["card_locale"].is_string() || s["card_locale"].get<std::string>().size()!=4 || s["card_locale"].get<std::string>().find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")!=std::string::npos))return false;
    for(const auto* k:{"scale","preview_scale","opacity","x","y","right_x","right_y","panel_width","font_size"})
        if(s.contains(k) && (!s[k].is_number() || !std::isfinite(s[k].get<double>())))return false;
    for(const auto* k:{"visible","own_deck","opponent_deck","opponent_hand","card_images","own_played","opponent_played","show_summary","hide_exhausted"})
        if(s.contains(k) && !s[k].is_boolean())return false;
    if(s.contains("arena_state")&&!valid_arena_state(s["arena_state"]))return false;
    if(!s.contains("tracking") || !s["tracking"].is_object())return false;
    const auto& t=s["tracking"];
    if(!t.contains("status") || !t["status"].is_string() || !t.contains("turn") || !t["turn"].is_number_integer())return false;
    for(const auto* k:{"own_label","own_class","opponent_class","deck_name"})if(t.contains(k) && !t[k].is_string())return false;
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
// Group headings are localized by the backend; the strings below are the English
// defaults used when an older state.json carries no `labels` object.
inline nlohmann::json deck_rows(const nlohmann::json& t,bool hide_exhausted,const nlohmann::json& labels=nlohmann::json::object()){
    using nlohmann::json;
    auto rows=json::array();
    for(const auto* key:{"own","own_added"}){
        if(!t.contains(key))continue;
        bool heading=false;
        for(const auto& r:t[key]){
            if(hide_exhausted && r.value("remaining",json())==json(0))continue;
            if(!heading){
                const std::string name=std::string(key)=="own"?
                    (t.value("deck_name",std::string()).empty()?labels.value("deck_original","Original deck"):t.value("deck_name",std::string())):
                    labels.value("deck_added","Added / transformed · currently in deck");
                rows.push_back({{"section",true},{"name",name}});heading=true;
            }
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

inline std::string arena_picked_title(const nlohmann::json& a){
    // English fallback only: the backend normally supplies a localized
    // `picked_title`. The count is exact only while the last snapshot was read
    // successfully, and a deck kept after a failed read must say so.
    const auto count=a.value("count",nlohmann::json());
    std::string title="Selected "+(count.is_number_integer()?std::to_string(count.get<int>()):"?")+"/30";
    if(!a.value("count_exact",true))title+=" (count unconfirmed)";
    return title;
}

inline nlohmann::json arena_rows(const nlohmann::json& a,bool candidates){
    using nlohmann::json;auto rows=json::array();
    const auto append=[&](const char* key){for(const auto& r:a[key]){auto row=r;row["arena_row"]=true;rows.push_back(row);}};
    // One flat list: the selected deck (mana order) or the three candidates.
    // No section headers, order markers or recovery groups are rendered.
    append(candidates?"candidates":"picks");
    return rows;
}

// X11 client geometry and ImGui display units can differ under compositor/DPI
// scaling. HUD scale is already included in row rectangles: never apply it here.
struct HoverPoint {float x,y;};
inline HoverPoint hover_display_point(float x,float y,float client_width,float client_height,
                                     float display_width,float display_height,float origin_x=0,float origin_y=0){
    if(client_width<=0 || client_height<=0 || display_width<=0 || display_height<=0)return {-1,-1};
    return {origin_x+x*display_width/client_width,origin_y+y*display_height/client_height};
}
inline bool hover_contains(float x,float y,float left,float top,float right,float bottom){
    return right>left && bottom>top && x>=left && x<right && y>=top && y<bottom;
}

struct PreviewSize {float width,height,padding;};
inline PreviewSize preview_size(int width,int height,float scale,float screen_width,float screen_height){
    const float padding=2*scale;
    const float available_width=std::max(1.f,screen_width-16-2*padding);
    const float available_height=std::max(1.f,screen_height-16-2*padding);
    const float ratio=float(std::max(1,width))/float(std::max(1,height));
    float h=std::min(384*scale,available_height),w=h*ratio;
    if(w>available_width){w=available_width;h=w/ratio;}
    return {w,h,padding};
}
