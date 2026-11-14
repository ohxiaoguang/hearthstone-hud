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
        if(ec || path.parent_path()!=root || path.extension()!=".png")return 0;
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
static void panel(const char* id,const std::string& title,const json& rows,bool own,float x,float y,float scale,float opacity,bool images,bool chinese,TextureCache& textures,unsigned long frame,int screen_height){
    const int per_page=std::max(1,int((screen_height-y-110*scale)/(32*scale)));
    const int pages=std::max(1,int((rows.size()+per_page-1)/per_page));
    const auto seconds=std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
    const int page=int(seconds/8)%pages;
    ImGui::SetNextWindowPos({x,y});ImGui::SetNextWindowBgAlpha(opacity);
    ImGui::Begin(id,nullptr,flags);ImGui::SetWindowFontScale(scale*.8f);
    ImGui::TextUnformatted(title.c_str());if(pages>1)ImGui::Text("%d / %d",page+1,pages);
    if(rows.empty())ImGui::TextUnformatted(own?"牌组未知，等待日志证据":"尚无公开卡牌");
    if(ImGui::BeginTable("cards",4,ImGuiTableFlags_SizingFixedFit)){
        ImGui::TableSetupColumn("art",ImGuiTableColumnFlags_WidthFixed,images?64*scale:1);
        ImGui::TableSetupColumn("cost",ImGuiTableColumnFlags_WidthFixed,24*scale);
        ImGui::TableSetupColumn("name",ImGuiTableColumnFlags_WidthFixed,180*scale);
        ImGui::TableSetupColumn("count",ImGuiTableColumnFlags_WidthFixed,46*scale);
        for(size_t i=page*per_page;i<rows.size() && i<size_t((page+1)*per_page);++i){
            const auto& row=rows[i];ImGui::TableNextRow(0,32*scale);ImGui::TableSetColumnIndex(0);
            if(images){auto texture=textures.get(row.value("image",""),frame);if(texture)ImGui::Image(reinterpret_cast<void*>(static_cast<intptr_t>(texture)),{64*scale,25*scale});else ImGui::TextUnformatted("[--]");}
            ImGui::TableSetColumnIndex(1);ImGui::TextUnformatted(number(row.value("cost",json())).c_str());
            ImGui::TableSetColumnIndex(2);ImGui::TextUnformatted(row.value(chinese?"name":"id","").c_str());
            ImGui::TableSetColumnIndex(3);
            auto count=own?row.value("remaining",json()):row.value("count",json());
            std::string label=count.is_null()?">="+number(row.value("known_in_deck",json())):number(count);
            ImGui::TextUnformatted(label.c_str());
        }
        ImGui::EndTable();
    }
    ImGui::End();
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
        ImGui::SetNextWindowPos({sw*.5f,8},ImGuiCond_Always,{.5f,0});ImGui::SetNextWindowBgAlpha(opacity);
        ImGui::Begin("match",nullptr,flags);ImGui::SetWindowFontScale(scale*.8f);
        std::string status=tracking.value("status","")=="playing"?"对局进行中":tracking.value("status","")=="identifying"?"识别玩家身份中":tracking.value("status","")=="unsupported"?"不支持的游戏模式":"等待新对局 / 活动日志";
        std::string summary=status+" · 回合 "+number(tracking.value("turn",json()));
        if(state.value("opponent_hand",true))summary+=" · 对手手牌 "+number(tracking.value("opponent_hand",json()));
        summary+=" · 对手牌库 "+number(tracking.value("opponent_deck",json()));
        ImGui::TextUnformatted(summary.c_str());ImGui::End();
        float maxx=std::max(0.f,sw-340*scale),maxy=std::max(0.f,sh-180*scale);
        if(state.value("own_deck",true))panel("own",tracking.value("own_label","牌组未知"),tracking["own"],true,std::clamp(state.value("x",40.f),0.f,maxx),std::clamp(state.value("y",80.f),0.f,maxy),scale,opacity,state.value("card_images",true),state.value("chinese_names",true),textures,frames,sh);
        if(state.value("opponent_deck",true))panel("opponent","对手公开卡牌 · 未知 "+number(tracking.value("opponent_unknown",json())),tracking["opponent"],false,std::clamp(state.value("right_x",1540.f),0.f,maxx),std::clamp(state.value("right_y",80.f),0.f,maxy),scale,opacity,state.value("card_images",true),state.value("chinese_names",true),textures,frames,sh);
        ImGui::Render();int fw,fh;glfwGetFramebufferSize(w,&fw,&fh);glViewport(0,0,fw,fh);glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT);ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());glfwSwapBuffers(w);
        if(++frames%30==0)write_json(argv[3],{{"display",getenv("DISPLAY")?getenv("DISPLAY"):""},{"window",x},{"external_overlay",atom_ok},{"xshape_input_empty",shape},{"transparent_framebuffer",glfwGetWindowAttrib(w,GLFW_TRANSPARENT_FRAMEBUFFER)==GLFW_TRUE},{"mapped",shown},{"frames",frames},{"compositor_visibility","unverified"},{"touch_passthrough","unverified"},{"state_schema",2}});
        std::this_thread::sleep_for(std::chrono::milliseconds(shown?16:100));
    }
    textures.clear();
    ImGui_ImplOpenGL3_Shutdown();ImGui_ImplGlfw_Shutdown();ImGui::DestroyContext();glfwDestroyWindow(w);glfwTerminate();return 0;
}
