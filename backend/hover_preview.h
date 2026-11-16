#pragma once
#include <future>
#include <vector>
#include <iterator>
#include <memory>
#include "card_regions.h"
#include "preview_image.h"

// CPU decode is asynchronous; this object's GL methods run only on the render thread.
class FullTextures {
    struct Pixels {std::string key;int width=0,height=0,source_width=0,source_height=0;std::vector<unsigned char> bytes;std::string error,stage="missing_file";};
    struct Entry {GLuint id;int width,height,source_width,source_height;unsigned long used;};
    std::map<std::string,Entry> cache;
    std::future<Pixels> pending;
    std::map<std::string,double> retry;
    json status={{"stage","idle"}};
public:
    void pump(unsigned long frame){
        if(!pending.valid() || pending.wait_for(std::chrono::seconds(0))!=std::future_status::ready)return;
        auto p=pending.get();status={{"stage",p.stage},{"key",p.key},{"error",p.error}};
        if(p.bytes.empty())return;
        if(cache.size()>=12){auto old=std::min_element(cache.begin(),cache.end(),[](auto& a,auto& b){return a.second.used<b.second.used;});glDeleteTextures(1,&old->second.id);cache.erase(old);}
        for(int i=0;i<16 && glGetError()!=GL_NO_ERROR;++i){}
        GLuint id=0;glGenTextures(1,&id);glBindTexture(GL_TEXTURE_2D,id);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,p.width,p.height,0,GL_RGBA,GL_UNSIGNED_BYTE,p.bytes.data());
        auto error=glGetError();
        if(!id || error!=GL_NO_ERROR){if(id)glDeleteTextures(1,&id);status={{"stage","upload_failed"},{"gl_error",error},{"key",p.key}};return;}
        cache[p.key]={id,p.width,p.height,p.source_width,p.source_height,frame};status={{"stage","resident"},{"key",p.key}};
    }
    GLuint get(const std::filesystem::path& root,const std::string& locale,const std::string& cid,unsigned long frame,int& width,int& height){
        const auto path=root/locale/(cid+".png");
        const auto key=path.string();
        auto it=cache.find(key);if(it!=cache.end()){status={{"stage","resident"},{"key",key},{"source_size",{it->second.source_width,it->second.source_height}},{"visible_size",{it->second.width,it->second.height}}};it->second.used=frame;width=it->second.width;height=it->second.height;return it->second.id;}
        if(pending.valid())return 0;
        double now=ImGui::GetTime();if(retry[key]>now)return 0;
        if(retry.size()>256)retry.clear();retry[key]=now+1;
        status={{"stage","decoding"},{"key",key}};
        pending=std::async(std::launch::async,[path,key]{
            Pixels result;result.key=key;
            try{
                std::error_code ec;
                if(std::filesystem::is_symlink(path,ec) || !std::filesystem::is_regular_file(path,ec) || std::filesystem::file_size(path,ec)>4*1024*1024)return result;
                std::ifstream f(path,std::ios::binary);std::vector<unsigned char> data((std::istreambuf_iterator<char>(f)),{});
                int channels;
                result.stage="decode_failed";
                if(!stbi_info_from_memory(data.data(),int(data.size()),&result.width,&result.height,&channels) || result.width<128 || result.height<128 || result.width>1024 || result.height>1536){result.error="Invalid PNG header or full card dimensions";return result;}
                result.source_width=result.width;result.source_height=result.height;
                std::unique_ptr<unsigned char,decltype(&stbi_image_free)> decoded(
                    stbi_load_from_memory(data.data(),int(data.size()),&result.width,&result.height,nullptr,4),&stbi_image_free);
                auto* pixels=decoded.get();
                if(pixels){
                    const auto bounds=preview_alpha_bounds(pixels,result.width,result.height);
                    result.bytes.resize(size_t(bounds.width)*bounds.height*4);
                    for(int y=0;y<bounds.height;++y)
                        std::copy_n(pixels+(size_t(y+bounds.top)*result.width+bounds.left)*4,size_t(bounds.width)*4,result.bytes.data()+size_t(y)*bounds.width*4);
                    result.width=bounds.width;result.height=bounds.height;
                    result.stage="decoded";
                }
                else result.error=stbi_failure_reason()?stbi_failure_reason():"PNG decode failed";
            }catch(const std::exception& e){result.stage="decode_failed";result.error=e.what();}
            return result;
        });return 0;
    }
    json diagnostic()const{return status;}
    void clear(){if(pending.valid()){pending.wait();pending=std::future<Pixels>();}for(auto& e:cache)glDeleteTextures(1,&e.second.id);cache.clear();retry.clear();status={{"stage","idle"}};}
};
static bool pointer_valid=false;
static json pointer_diagnostic=json::object();
static ImVec2 pointer_position{-1,-1};
class HoverPreview {
    std::string current;
    double since=0,last_write=0;
    FullTextures textures;
    json status={{"stage","idle"}};
    json last_registration=json::object(),last_hit=json::object(),last_request=json::object();
    HoverPointerHistory pointer_history;
    int cache_generation=0;
public:
    json diagnostic()const{return status;}
    void cache_changed(int generation){
        if(generation!=cache_generation){textures.clear();cache_generation=generation;}
    }
    void render_result(GLenum error){
        if(error!=GL_NO_ERROR){status["gl_error"]=error;if(status.value("stage","")=="rendered")status["stage"]="render_failed";}
    }
    void failure(const std::string& error){status["stage"]=status.value("stage","")=="request_write"?"request_write_failed":"render_failed";status["error"]=error.substr(0,300);}
    void render(const std::filesystem::path& runtime,const std::string& locale,const std::string& loading,const std::string& unavailable,unsigned long frame,float sw,float sh,float scale,const CardRegions& regions,float preview_scale=1){
        textures.pump(frame);
        const auto& card_hits=regions.hits;
        const CardHit* hit=pointer_valid?regions.hit(pointer_position.x,pointer_position.y):nullptr;
        status={{"stage",!pointer_valid?"pointer_unavailable":card_hits.empty()?"no_card_regions":hit?"hover_delay":"no_hit"},{"pointer",pointer_diagnostic},{"card_regions",card_hits.size()},{"id",hit?hit->id:""}};
        double now=ImGui::GetTime();
        pointer_history.observe(now,pointer_valid,{pointer_position.x,pointer_position.y},!card_hits.empty());
        status["pointer_history"]=pointer_history.diagnostic(now);
        status["last_request"]=last_request;
        status.update(regions.diagnostic());
        if(!card_hits.empty())last_registration={{"frame",frame},{"card_regions",card_hits.size()},{"ids",status["registered_ids"]}};
        if(hit)last_hit={{"frame",frame},{"id",hit->id},{"source",hit->source}};
        status["last_nonempty_registration"]=last_registration;
        status["last_hit"]=last_hit;
        if(!card_hits.empty())status["first_region"]={card_hits[0].min.x,card_hits[0].min.y,card_hits[0].max.x,card_hits[0].max.y};
        if(hit)status["hit_region"]={hit->min.x,hit->min.y,hit->max.x,hit->max.y};
        std::string key=hit?locale+":"+hit->id:"";
        if(key!=current){status["stage"]="request_write";current=key;since=now;last_write=0;write_json((runtime/"hover.json").string(),{{"id",""},{"updated",0}});}
        if(!hit || now-since<.2){status["stage"]=!pointer_valid?"pointer_unavailable":card_hits.empty()?"no_card_regions":hit?"hover_delay":"no_hit";return;}
        status["stage"]="request_write";
        if(now-last_write>.2){write_json((runtime/"hover.json").string(),{{"id",hit->id},{"locale",locale},{"updated",std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count()}});last_write=now;last_request={{"frame",frame},{"id",hit->id},{"locale",locale}};status["last_request"]=last_request;}
        int iw=256,ih=384;
        GLuint texture=textures.get(runtime/"cache/full-cards/256x",locale,hit->id,frame,iw,ih);
        status["request_written"]=last_write>0;
        status["hover_seconds"]=now-since;
        status["texture"]=textures.diagnostic();
        status["stage"]=texture?"rendered":"awaiting_texture";
        const auto size=preview_size(iw,ih,scale*preview_scale,sw,sh);
        const float w=size.width,h=size.height,padding=size.padding;
        const float outer_width=w+2*padding,outer_height=h+2*padding;
        float y=std::clamp(hit->min.y,8.f,std::max(8.f,sh-outer_height-8));
        // Prefer a side of the hovered row with the least overlap with drawn cards.
        float best_x=8,best_score=FLT_MAX;
        for(float candidate:{hit->min.x-outer_width-12*scale,hit->max.x+12*scale}){
            float x=std::clamp(candidate,8.f,std::max(8.f,sw-outer_width-8));float score=0;
            for(auto& r:card_hits){float area=std::max(0.f,std::min(x+outer_width,r.max.x)-std::max(x,r.min.x))*std::max(0.f,std::min(y+outer_height,r.max.y)-std::max(y,r.min.y));score+=area*(&r==hit?100.f:1.f);}
            if(score<best_score){best_score=score;best_x=x;}
        }
        auto* draw=ImGui::GetForegroundDrawList();
        const ImVec2 image_min(best_x+padding,y+padding),image_max(image_min.x+w,image_min.y+h);
        draw->AddRectFilled({best_x,y},{best_x+outer_width,y+outer_height},IM_COL32(20,25,33,245),4*scale);
        draw->AddRect({best_x,y},{best_x+outer_width,y+outer_height},IM_COL32(115,135,160,210),4*scale,0,scale);
        status["preview_rect"]={best_x,y,best_x+outer_width,y+outer_height};
        status["resolution"]="256x";
        status["preview_scale"]=preview_scale;
        if(texture)draw->AddImage(reinterpret_cast<void*>(static_cast<intptr_t>(texture)),image_min,image_max);
        else{
            draw->AddRect(image_min,image_max,IM_COL32(65,80,100,180),4*scale);
            const bool timed_out=now-since>30;
            const auto& message=timed_out?unavailable:loading;
            float text_size=18*scale;
            auto* font=ImGui::GetFont();
            auto extent=font->CalcTextSizeA(text_size,FLT_MAX,0,message.c_str());
            if(extent.x>w-8*scale && extent.x>0){
                text_size*=std::max(1.f,w-8*scale)/extent.x;
                extent=font->CalcTextSizeA(text_size,FLT_MAX,0,message.c_str());
            }
            const ImVec2 center(image_min.x+w*.5f,image_min.y+h*.5f);
            if(!timed_out){
                const ImVec2 spinner(center.x,center.y-24*scale);
                draw->AddCircle(spinner,10*scale,IM_COL32(70,85,105,220),24,2*scale);
                draw->PathArcTo(spinner,10*scale,float(now*4),float(now*4)+4.4f,24);
                draw->PathStroke(IM_COL32(165,205,245,255),0,2*scale);
            }
            draw->AddText(font,text_size,{center.x-extent.x*.5f,center.y+2*scale},IM_COL32(220,230,240,255),message.c_str());
            status["placeholder"]=timed_out?"unavailable":"loading";
        }
    }
    void clear(){textures.clear();}
};
