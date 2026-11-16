#pragma once
#include <future>
#include <vector>
#include <iterator>

// CPU decode is asynchronous; this object's GL methods run only on the render thread.
class FullTextures {
    struct Pixels {std::string key;int width=0,height=0;std::vector<unsigned char> bytes;};
    struct Entry {GLuint id;int width,height;unsigned long used;};
    std::map<std::string,Entry> cache;
    std::future<Pixels> pending;
    std::map<std::string,double> retry;
public:
    void pump(unsigned long frame){
        if(!pending.valid() || pending.wait_for(std::chrono::seconds(0))!=std::future_status::ready)return;
        auto p=pending.get();if(p.bytes.empty())return;
        if(cache.size()>=12){auto old=std::min_element(cache.begin(),cache.end(),[](auto& a,auto& b){return a.second.used<b.second.used;});glDeleteTextures(1,&old->second.id);cache.erase(old);}
        GLuint id;glGenTextures(1,&id);glBindTexture(GL_TEXTURE_2D,id);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,p.width,p.height,0,GL_RGBA,GL_UNSIGNED_BYTE,p.bytes.data());
        cache[p.key]={id,p.width,p.height,frame};
    }
    GLuint get(const std::filesystem::path& root,const std::string& locale,const std::string& cid,unsigned long frame,int& width,int& height){
        const auto path=root/locale/(cid+".png");const auto key=path.string();
        auto it=cache.find(key);if(it!=cache.end()){it->second.used=frame;width=it->second.width;height=it->second.height;return it->second.id;}
        if(pending.valid())return 0;
        double now=ImGui::GetTime();if(retry[key]>now)return 0;
        if(retry.size()>256)retry.clear();retry[key]=now+1;
        pending=std::async(std::launch::async,[path,key]{
            Pixels result;result.key=key;
            try{
                std::error_code ec;
                if(std::filesystem::is_symlink(path,ec) || !std::filesystem::is_regular_file(path,ec) || std::filesystem::file_size(path,ec)>4*1024*1024)return result;
                std::ifstream f(path,std::ios::binary);std::vector<unsigned char> data((std::istreambuf_iterator<char>(f)),{});
                int channels;
                if(!stbi_info_from_memory(data.data(),int(data.size()),&result.width,&result.height,&channels) || result.width<128 || result.height<128 || result.width>1024 || result.height>1536)return result;
                auto* pixels=stbi_load_from_memory(data.data(),int(data.size()),&result.width,&result.height,nullptr,4);
                if(pixels){result.bytes.assign(pixels,pixels+result.width*result.height*4);stbi_image_free(pixels);}
            }catch(const std::exception&){}
            return result;
        });return 0;
    }
    void clear(){if(pending.valid())pending.wait();for(auto& e:cache)glDeleteTextures(1,&e.second.id);cache.clear();}
};
struct CardHit {ImVec2 min,max;std::string id;};
static std::vector<CardHit> card_hits;
static ImVec2 pointer_position{-1,-1};
static bool safe_card_id(const std::string& id){return !id.empty() && id.size()<=128 && id.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")==std::string::npos;}
class HoverPreview {
    std::string current;
    double since=0,last_write=0;
    FullTextures textures;
public:
    void render(const std::filesystem::path& runtime,const std::string& locale,const std::string& loading,const std::string& unavailable,unsigned long frame,float sw,float sh,float scale){
        textures.pump(frame);
        const CardHit* hit=nullptr;
        for(auto& r:card_hits)if(pointer_position.x>=r.min.x && pointer_position.x<r.max.x && pointer_position.y>=r.min.y && pointer_position.y<r.max.y)hit=&r;
        std::string key=hit?locale+":"+hit->id:"";
        double now=ImGui::GetTime();
        if(key!=current){current=key;since=now;last_write=0;write_json((runtime/"hover.json").string(),{{"id",""},{"updated",0}});}
        if(!hit || now-since<.2)return;
        if(now-last_write>.2){write_json((runtime/"hover.json").string(),{{"id",hit->id},{"locale",locale},{"updated",std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count()}});last_write=now;}
        int iw=512,ih=768;
        GLuint texture=textures.get(runtime/"cache/full-cards",locale,hit->id,frame,iw,ih);
        float h=std::min(540.f*scale,std::max(1.f,sh-16));float w=h*float(iw)/float(ih);
        if(w>sw-16){w=std::max(1.f,sw-16);h=w*float(ih)/float(iw);}
        float y=std::clamp(hit->min.y,8.f,std::max(8.f,sh-h-8));
        // Prefer a side of the hovered row with the least overlap with drawn cards.
        float best_x=8,best_score=FLT_MAX;
        for(float candidate:{hit->min.x-w-12,hit->max.x+12}){
            float x=std::clamp(candidate,8.f,std::max(8.f,sw-w-8));float score=0;
            for(auto& r:card_hits){float area=std::max(0.f,std::min(x+w,r.max.x)-std::max(x,r.min.x))*std::max(0.f,std::min(y+h,r.max.y)-std::max(y,r.min.y));score+=area*(&r==hit?100.f:1.f);}
            if(score<best_score){best_score=score;best_x=x;}
        }
        auto* draw=ImGui::GetForegroundDrawList();
        if(texture)draw->AddImage(reinterpret_cast<void*>(static_cast<intptr_t>(texture)),{best_x,y},{best_x+w,y+h});
        else draw->AddText({best_x+8,y+8},IM_COL32(220,220,220,220),(now-since>30?unavailable:loading).c_str());
    }
    void clear(){textures.clear();}
};
