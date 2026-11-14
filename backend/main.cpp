#include <GLFW/glfw3.h>
#define GLFW_EXPOSE_NATIVE_X11
#include <GLFW/glfw3native.h>
#include <X11/Xatom.h>
#include <X11/Xutil.h>
#include <X11/extensions/shape.h>
#include <imgui.h>
#include <backends/imgui_impl_glfw.h>
#include <backends/imgui_impl_opengl3.h>
#include <nlohmann/json.hpp>
#define STB_IMAGE_IMPLEMENTATION
#include <stb_image.h>
#include <atomic>
#include <cfloat>
#include <map>
#include <algorithm>
#include "hud_state.h"
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <chrono>
#include <thread>
#include <sys/prctl.h>
#include <unistd.h>
using json=nlohmann::json;
static volatile std::sig_atomic_t quitting=0;
static void stop(int){quitting=1;}
static void write_json(const std::string& path,const json& j){
    std::ofstream f(path+".tmp"); f<<j.dump(); f.close(); std::filesystem::rename(path+".tmp",path);
}
struct Texture { GLuint id=0; unsigned long used=0; };
class TextureCache {
    std::map<std::string,Texture> items;
    std::map<std::string,unsigned long> rejected;
    std::filesystem::path root;
public:
    explicit TextureCache(const std::filesystem::path& state):root(std::filesystem::weakly_canonical(state.parent_path()/"cache/images")){}
    GLuint get(const std::string& name,unsigned long frame){
        if(name.empty())return 0;
        auto it=items.find(name);
        if(it!=items.end()){it->second.used=frame;return it->second.id;}
        if(rejected.count(name) && frame-rejected[name]<3600)return 0;
        if(rejected.size()>256)rejected.clear();
        rejected[name]=frame;
        std::error_code ec;auto path=std::filesystem::weakly_canonical(name,ec);
        if(ec || (path.parent_path()!=root && path.parent_path()!=root/"manual") || path.extension()!=".png")return 0;
        int width,height,channels;
        if(!stbi_info(name.c_str(),&width,&height,&channels) || width>1024 || height>1024)return 0;
        auto pixels=stbi_load(name.c_str(),&width,&height,nullptr,4);if(!pixels)return 0;
        if(items.size()>=128){auto oldest=std::min_element(items.begin(),items.end(),[](auto& a,auto& b){return a.second.used<b.second.used;});glDeleteTextures(1,&oldest->second.id);items.erase(oldest);}
        GLuint texture;glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,width,height,0,GL_RGBA,GL_UNSIGNED_BYTE,pixels);stbi_image_free(pixels);
        items[name]={texture,frame};return texture;
    }
    void clear(){for(auto& entry:items)glDeleteTextures(1,&entry.second.id);items.clear();}
};
static std::string number(const json& value){return value.is_number_integer()?std::to_string(value.get<int>()):"?";}
static constexpr auto flags=ImGuiWindowFlags_NoDecoration|ImGuiWindowFlags_AlwaysAutoResize|ImGuiWindowFlags_NoInputs|ImGuiWindowFlags_NoFocusOnAppearing;
static void panel(const char* id,const std::string& title,const json& rows,bool own,float x,float y,float scale,float opacity,bool images,bool chinese,TextureCache& textures,unsigned long frame,float width,float height,float font_size){
    if(rows.empty())return;
    const float row_height=std::max(32.f,font_size+8)*scale;
    const auto seconds=std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
    const auto padding=ImGui::GetStyle().WindowPadding;
    const auto layout=panel_layout(rows.size(),font_size,scale,height,seconds/8,padding.y*2);
    const int per_page=layout.per_page,pages=layout.pages,page=layout.page;
    height=layout.height;
    ImGui::SetNextWindowPos({x,y});ImGui::SetNextWindowSize({width+padding.x*2,height});ImGui::SetNextWindowBgAlpha(opacity);
    ImGui::Begin(id,nullptr,flags & ~ImGuiWindowFlags_AlwaysAutoResize);
    ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing,ImVec2(0,2*scale));ImGui::SetWindowFontScale(scale*.8f);
    ImGui::TextUnformatted(title.c_str());if(pages>1)ImGui::Text("%d / %d",page+1,pages);
    if(rows.empty())ImGui::TextUnformatted(own?"无剩余行或等待日志证据":"尚无出牌记录");
    auto* draw=ImGui::GetWindowDrawList();
    for(size_t i=page*per_page;i<rows.size() && i<size_t((page+1)*per_page);++i){
        const auto& row=rows[i];
        const auto pos=ImGui::GetCursorScreenPos();
        ImGui::Dummy({width,row_height});
        if(row.value("section",false)){
            draw->AddText(pos,IM_COL32(255,215,135,255),row.value("name","").c_str());continue;
        }
        const bool event=row.value("event",false),deck=row.value("deck_row",false),arena=row.value("arena_row",false);
        const auto label=arena?row.value("rating_label","暂无评分"):event?"":card_count_label(row,deck);
        const float rating_width=ImGui::GetFont()->CalcTextSizeA(24*scale,FLT_MAX,0,label.c_str()).x+12*scale;
        const float count_width=arena?std::min(width*.45f,std::max(36*scale,rating_width)):label.empty()?0:36*scale;
        const bool exhausted=deck && row.value("remaining",json())==json(0);
        const auto white=exhausted?IM_COL32(170,170,170,200):IM_COL32(255,255,255,255);
        draw->AddRectFilled(pos,{pos.x+width,pos.y+row_height},IM_COL32(24,30,39,230));
        if(images){auto texture=textures.get(row.value("image",""),frame);if(texture)
            draw->AddImage(reinterpret_cast<void*>(static_cast<intptr_t>(texture)),pos,{pos.x+width,pos.y+row_height},{0,.29f},{1,.71f},exhausted?IM_COL32(170,170,170,110):IM_COL32_WHITE);}
        draw->AddRectFilledMultiColor(pos,{pos.x+width,pos.y+row_height},IM_COL32(0,0,0,210),IM_COL32(0,0,0,70),IM_COL32(0,0,0,70),IM_COL32(0,0,0,210));
        draw->AddRectFilled({pos.x+width-count_width,pos.y},{pos.x+width,pos.y+row_height},IM_COL32(0,0,0,190));
        const bool hero=row.value("hero_row",false);
        const float name_left=(hero?8:38)*scale;
        const ImVec4 clip(pos.x+name_left,pos.y,pos.x+width-count_width-4*scale,pos.y+row_height);
        if(!hero){
            const ImVec2 center(pos.x+17*scale,pos.y+row_height*.5f);
            const float radius=14*scale;
            draw->AddCircleFilled(center,radius,exhausted?IM_COL32(45,65,90,220):IM_COL32(20,92,185,245),6);
            draw->AddCircle(center,radius,IM_COL32(135,205,255,240),6,1.5f*scale);
            const auto cost=number(row.value("cost",json()));const float size=22*scale;
            const auto extent=ImGui::GetFont()->CalcTextSizeA(size,FLT_MAX,0,cost.c_str());
            draw->AddText(ImGui::GetFont(),size,{center.x-extent.x*.5f,center.y-extent.y*.5f},white,cost.c_str());
        }
        const auto name=hero&&chinese?row.value("class_name",row.value("name","")):row.value(chinese?"name":"id","");
        const ImVec2 name_pos(pos.x+name_left,pos.y+(row_height-font_size*scale)*.5f);
        draw->AddText(ImGui::GetFont(),font_size*scale,{name_pos.x+scale,name_pos.y+scale},IM_COL32(0,0,0,230),name.c_str(),nullptr,0,&clip);
        draw->AddText(ImGui::GetFont(),font_size*scale,name_pos,white,name.c_str(),nullptr,0,&clip);
        if(arena&&row.value("best",false))draw->AddRect(pos,{pos.x+width,pos.y+row_height},IM_COL32(255,215,90,255),0,0,2*scale);
        const ImVec4 count_clip(pos.x+width-count_width+scale,pos.y,pos.x+width,pos.y+row_height);
        float label_size=(arena?24.f:22.f)*scale;
        const auto extent=ImGui::GetFont()->CalcTextSizeA(label_size,FLT_MAX,0,label.c_str());
        if(extent.x>count_width-8*scale&&extent.x>0)label_size*=std::max(1.f,count_width-8*scale)/extent.x;
        const auto fitted=ImGui::GetFont()->CalcTextSizeA(label_size,FLT_MAX,0,label.c_str());
        if(!event)draw->AddText(ImGui::GetFont(),label_size,{pos.x+width-count_width+(count_width-fitted.x)*.5f,pos.y+(row_height-label_size)*.5f},white,label.c_str(),nullptr,0,&count_clip);
    }
    ImGui::PopStyleVar();ImGui::End();
}
int main(int argc,char** argv){
    if(argc!=4) return 2;
    // Kill orphan window even if Decky's backend is killed without _unload.
    auto parent=getppid(); prctl(PR_SET_PDEATHSIG,SIGTERM);
    if(getppid()!=parent || parent==1) return 3;
    std::signal(SIGTERM,stop); std::signal(SIGINT,stop);
    glfwSetErrorCallback([](int code,const char* msg){std::cerr<<code<<": "<<msg<<'\n';});
    if(!glfwInit()) return 4;
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR,3); glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR,0);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER,GLFW_TRUE);
    glfwWindowHint(GLFW_DECORATED,GLFW_FALSE); glfwWindowHint(GLFW_FOCUSED,GLFW_FALSE);
    glfwWindowHint(GLFW_FOCUS_ON_SHOW,GLFW_FALSE); glfwWindowHint(GLFW_FLOATING,GLFW_TRUE);
    glfwWindowHint(GLFW_VISIBLE,GLFW_FALSE);
    GLFWwindow* w=glfwCreateWindow(1280,720,"Hearthstone HUD",nullptr,nullptr);
    if(!w){glfwTerminate();return 5;}
    Display* d=glfwGetX11Display(); Window x=glfwGetX11Window(w);
    unsigned long one=1;
    Atom atom=XInternAtom(d,"GAMESCOPE_EXTERNAL_OVERLAY",False);
    XChangeProperty(d,x,atom,XA_CARDINAL,32,PropModeReplace,reinterpret_cast<unsigned char*>(&one),1);
    XWMHints hints{}; hints.flags=InputHint; hints.input=False; XSetWMHints(d,x,&hints);
    int shape_event,shape_error;
    bool shape=XShapeQueryExtension(d,&shape_event,&shape_error);
    if(shape) XShapeCombineRectangles(d,x,ShapeInput,0,0,nullptr,0,ShapeSet,Unsorted);
    XSync(d,False);
    Atom actual; int format; unsigned long count,remain; unsigned char* value=nullptr;
    XGetWindowProperty(d,x,atom,0,1,False,XA_CARDINAL,&actual,&format,&count,&remain,&value);
    bool atom_ok=actual==XA_CARDINAL && format==32 && count==1 && value && *reinterpret_cast<unsigned long*>(value)==1;
    if(value) XFree(value);
    glfwMakeContextCurrent(w); glfwSwapInterval(1);
    ImGui::CreateContext(); auto& io=ImGui::GetIO(); io.IniFilename=nullptr;
    std::string assets=argv[2];
    if(!io.Fonts->AddFontFromFileTTF((assets+"/fonts/NotoSansCJKsc-Regular.otf").c_str(),24,nullptr,io.Fonts->GetGlyphRangesChineseFull())) {
        std::cerr<<"Missing Chinese font\n"; ImGui::DestroyContext();glfwDestroyWindow(w);glfwTerminate();return 6;
    }
    ImGui_ImplGlfw_InitForOpenGL(w,false); ImGui_ImplOpenGL3_Init("#version 130");
    TextureCache textures{std::filesystem::path(argv[1])};
    json state; bool shown=false; auto last=std::chrono::steady_clock::now();
    unsigned long frames=0;
    while(!quitting && !glfwWindowShouldClose(w)){
        glfwPollEvents();
        auto now=std::chrono::steady_clock::now();
        if(now-last>std::chrono::milliseconds(100) || state.is_null()){
            try{std::ifstream f(argv[1]);json next;f>>next;if(valid_hud_state(next))state=next;}catch(const std::exception& e){std::cerr<<"state: "<<e.what()<<'\n';}
            last=now;
        }
        // Stale backend state must never leave a persistent HUD.
        auto age=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count()-state.value("updated",0.0);
        if(age>10) break;
        bool visible=state.value("visible",true);
        if(visible!=shown){if(visible)glfwShowWindow(w);else glfwHideWindow(w);shown=visible;}
        if(auto m=glfwGetPrimaryMonitor()) if(auto mode=glfwGetVideoMode(m)){int width,height;glfwGetWindowSize(w,&width,&height);if(width!=mode->width||height!=mode->height)glfwSetWindowSize(w,mode->width,mode->height);}
        ImGui_ImplOpenGL3_NewFrame();ImGui_ImplGlfw_NewFrame();ImGui::NewFrame();
        float scale=std::clamp(state.value("scale",1.0f),.5f,3.f);
        float opacity=std::clamp(state.value("opacity",.85f),.1f,1.f);
        int sw,sh;glfwGetWindowSize(w,&sw,&sh);
        const auto& tracking=state["tracking"];
        const float font_size=std::clamp(state.value("font_size",22.f),14.f,30.f);
        const float width=std::min(std::max(1.f,sw-20.f),std::clamp(state.value("panel_width",320.f),180.f,640.f)*scale);
        const float maxx=std::max(0.f,sw-width-20),maxy=std::max(0.f,sh-180*scale);
        const float lx=std::clamp(state.value("x",40.f),0.f,maxx),ly=std::clamp(state.value("y",80.f),0.f,maxy);
        const float rx=std::clamp(state.value("right_x",1540.f),0.f,maxx),ry=std::clamp(state.value("right_y",80.f),0.f,maxy);
        if(visible){
        if(state.contains("arena_state")&&state["arena_state"].value("visible",false)){
            const auto& arena=state["arena_state"];
            const std::string count=number(arena.value("count",json()))+"/30";
            const auto stage=arena.value("stage","");
            const bool hero=stage=="hero_selection",power=stage=="hero_power_selection";
            const bool show_count=arena.value("show_count",true)&&!hero&&!power;
            const std::string title=hero?"竞技场 · 英雄选择":power?"竞技场 · 英雄技能选择":"竞技场 · 卡牌选择"+(show_count?" · "+count:"");
            const float available=std::max(80.f,sh-ly-16*scale);
            panel("arena-offer",title+(show_count&&!arena.value("count_exact",false)?"（份数待确认）":""),arena_rows(arena,true),false,lx,ly,scale,opacity,state.value("card_images",true),state.value("chinese_names",true),textures,frames,width,std::min(available,230*scale),font_size);
            if(show_count)panel("arena-picked",arena.value("mode","")=="REDRAFTING"?"重选中 · 旧牌组不追加":"已选牌 · "+count,arena_rows(arena,false),false,rx,ry,scale,opacity,state.value("card_images",true),state.value("chinese_names",true),textures,frames,width,std::max(80.f,sh-ry-16*scale),font_size);
        }else{
        if(state.value("show_summary",true)){
        ImGui::SetNextWindowPos({sw*.5f,8},ImGuiCond_Always,{.5f,0});ImGui::SetNextWindowBgAlpha(opacity);
        ImGui::Begin("match",nullptr,flags);ImGui::SetWindowFontScale(scale*.8f);
        std::string status=tracking.value("status","")=="playing"?"对局进行中":tracking.value("status","")=="identifying"?"识别玩家身份中":tracking.value("status","")=="unsupported"?"不支持的游戏模式":"等待新对局 / 活动日志";
        std::string summary=status+" · 回合 "+number(tracking.value("turn",json()));
        if(state.value("opponent_hand",true))summary+=" · 对手手牌 "+number(tracking.value("opponent_hand",json()));
        summary+=" · 对手牌库 "+number(tracking.value("opponent_deck",json()));
        ImGui::TextUnformatted(summary.c_str());ImGui::End();
        }
        const auto opponent_rows=played_rows(tracking,"opponent_played"),own_rows=played_rows(tracking,"own_played");
        const auto left=left_regions(state.value("opponent_played",true)&&!opponent_rows.empty(),state.value("own_played",true)&&!own_rows.empty(),ly,std::max(80.f,sh-ly-16*scale),8*scale);
        const auto render=[&](const char* id,const std::string& title,const json& rows,bool deck,float x,float y,float height){
            panel(id,title,rows,deck,x,y,scale,opacity,state.value("card_images",true),state.value("chinese_names",true),textures,frames,width,height,font_size);
        };
        if(left.opponent.visible)render("opponent-played","对手已打出 · 最近在前",opponent_rows,false,lx,left.opponent.y,left.opponent.height);
        const auto tick=std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now().time_since_epoch()).count()/8;
        const float own_y=ly+(left.opponent.visible&&!opponent_rows.empty()?panel_layout(opponent_rows.size(),font_size,scale,left.opponent.height,tick,ImGui::GetStyle().WindowPadding.y*2).height+8*scale:0);
        if(left.own.visible)render("own-played","我方已打出 · 最近在前",own_rows,false,lx,own_y,left.own.height);
        if(state.value("own_deck",true))render("remaining","我方剩余牌库 · "+number(tracking.value("own_remaining",json())),deck_rows(tracking,state.value("hide_exhausted",false)),true,rx,ry,std::max(80.f,sh-ry-16*scale));
        }
        } // Hidden HUD submits an empty transparent frame.
        ImGui::Render();int fw,fh;glfwGetFramebufferSize(w,&fw,&fh);glViewport(0,0,fw,fh);glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT);ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());glfwSwapBuffers(w);
        if(++frames%30==0)write_json(argv[3],{{"display",getenv("DISPLAY")?getenv("DISPLAY"):""},{"window",x},{"external_overlay",atom_ok},{"xshape_input_empty",shape},{"transparent_framebuffer",glfwGetWindowAttrib(w,GLFW_TRANSPARENT_FRAMEBUFFER)==GLFW_TRUE},{"mapped",shown},{"frames",frames},{"compositor_visibility","unverified"},{"touch_passthrough","unverified"},{"state_schema",2}});
        std::this_thread::sleep_for(std::chrono::milliseconds(shown?16:100));
    }
    textures.clear();
    ImGui_ImplOpenGL3_Shutdown();ImGui_ImplGlfw_Shutdown();ImGui::DestroyContext();glfwDestroyWindow(w);glfwTerminate();return 0;
}
