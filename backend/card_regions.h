#pragma once
#include "hud_state.h"
#include <map>
#include <vector>
#include <utility>

struct CardHit {HoverPoint min,max;std::string id,source;};
inline bool safe_card_id(const std::string& id){
    return !id.empty() && id.size()<=128 &&
        id.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")==std::string::npos;
}
// One collector belongs to one render frame. All panels append to it, and the
// preview consumes the very same object after the last panel has finished.
class CardRegions {
    struct Counts {size_t available=0,submitted=0,sections=0,rejected=0,clipped=0,registered=0;bool skipped=false;};
    std::map<std::string,Counts> sources;
    std::vector<std::string> rejected_ids;
    nlohmann::json first_attempt=nlohmann::json::object();
public:
    const unsigned long frame;
    const nlohmann::json context;
    std::vector<CardHit> hits;
    explicit CardRegions(unsigned long frame,nlohmann::json context=nlohmann::json::object()):frame(frame),context(std::move(context)){}
    void panel(const std::string& source,size_t available){sources[source].available=available;}
    void skipped(const std::string& source){sources[source].skipped=true;}
    void section(const std::string& source){++sources[source].sections;}
    void add(const std::string& source,const std::string& id,HoverPoint min,HoverPoint max,
             HoverPoint clip_min,HoverPoint clip_max){
        auto& count=sources[source];++count.submitted;
        if(first_attempt.empty())first_attempt={{"source",source},{"id",id.substr(0,128)},
            {"draw_rect",{min.x,min.y,max.x,max.y}},{"clip_rect",{clip_min.x,clip_min.y,clip_max.x,clip_max.y}}};
        if(!safe_card_id(id)){
            ++count.rejected;if(rejected_ids.size()<4)rejected_ids.push_back(id.substr(0,128));return;
        }
        // Use exactly the origin/extent passed to AddRect/AddImage, intersected
        // with the draw list's render clip. No cursor or item-hover query here.
        min={std::max(min.x,clip_min.x),std::max(min.y,clip_min.y)};
        max={std::min(max.x,clip_max.x),std::min(max.y,clip_max.y)};
        if(!std::isfinite(min.x)||!std::isfinite(min.y)||!std::isfinite(max.x)||!std::isfinite(max.y)||max.x<=min.x||max.y<=min.y){++count.clipped;return;}
        hits.push_back({min,max,id,source});++count.registered;
    }
    const CardHit* hit(float x,float y)const{
        for(auto r=hits.rbegin();r!=hits.rend();++r)
            if(hover_contains(x,y,r->min.x,r->min.y,r->max.x,r->max.y))return &*r;
        return nullptr;
    }
    nlohmann::json diagnostic()const{
        using nlohmann::json;
        auto panels=json::object();size_t submitted=0,available=0;
        for(const auto& entry:sources){const auto& c=entry.second;submitted+=c.submitted;available+=c.available;
            panels[entry.first]={{"available",c.available},{"submitted",c.submitted},{"sections",c.sections},
                {"rejected_id",c.rejected},{"clipped",c.clipped},{"registered",c.registered},{"skipped",c.skipped}};
        }
        auto ids=json::array();for(const auto& r:hits){if(ids.size()>=12)break;ids.push_back(r.id);}
        return {{"registration_frame",frame},{"render_context",context},{"panels",panels},{"card_rows_submitted",submitted},
            {"registration_state",!hits.empty()?"registered":submitted?"all_filtered":available?"no_submitted_cards":"no_cards"},
            {"registered_ids",ids},{"rejected_ids",rejected_ids},{"first_registration_attempt",first_attempt}};
    }
};

// Bounded evidence survives opening Decky to copy diagnostics. This observes the
// existing pointer samples only; it never queries or changes input delivery.
class HoverPointerHistory {
    HoverPoint previous{-1,-1},minimum{0,0},maximum{0,0};
    bool observed=false;
    double last_change=0;
    unsigned long samples=0,changes=0;
public:
    void observe(double now,bool valid,HoverPoint point,bool cards_visible){
        if(!valid || !cards_visible)return;
        ++samples;
        if(!observed){observed=true;minimum=maximum=previous=point;last_change=now;return;}
        if(point.x!=previous.x || point.y!=previous.y){++changes;last_change=now;previous=point;}
        minimum={std::min(minimum.x,point.x),std::min(minimum.y,point.y)};
        maximum={std::max(maximum.x,point.x),std::max(maximum.y,point.y)};
    }
    nlohmann::json diagnostic(double now)const{
        return {{"samples_with_cards",samples},{"position_changes_with_cards",changes},
            {"observed_bounds",observed?nlohmann::json{minimum.x,minimum.y,maximum.x,maximum.y}:nlohmann::json::array()},
            {"seconds_since_observed_change",observed?int(std::max(0.0,now-last_change)):-1}};
    }
};
