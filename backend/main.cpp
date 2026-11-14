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
    int iw=0,ih=0; GLuint image=0;
    unsigned char* pixels=stbi_load((assets+"/test.png").c_str(),&iw,&ih,nullptr,4);
    if(pixels){glGenTextures(1,&image);glBindTexture(GL_TEXTURE_2D,image);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,iw,ih,0,GL_RGBA,GL_UNSIGNED_BYTE,pixels);stbi_image_free(pixels);}
    json state; bool shown=false; auto last=std::chrono::steady_clock::now();
    unsigned long frames=0;
    while(!quitting && !glfwWindowShouldClose(w)){
        glfwPollEvents();
        auto now=std::chrono::steady_clock::now();
        if(now-last>std::chrono::milliseconds(100) || state.is_null()){
            try{std::ifstream f(argv[1]);json next;f>>next;if(next.is_object())state=next;}catch(const std::exception& e){std::cerr<<"state: "<<e.what()<<'\n';}
            last=now;
        }
        // Stale backend state must never leave a persistent HUD.
        auto age=std::chrono::duration<double>(std::chrono::system_clock::now().time_since_epoch()).count()-state.value("updated",0.0);
        if(age>10) break;
        bool visible=state.value("visible",true);
        if(visible!=shown){if(visible)glfwShowWindow(w);else glfwHideWindow(w);shown=visible;}
        if(auto m=glfwGetPrimaryMonitor()) if(auto mode=glfwGetVideoMode(m)){int width,height;glfwGetWindowSize(w,&width,&height);if(width!=mode->width||height!=mode->height)glfwSetWindowSize(w,mode->width,mode->height);}
        ImGui_ImplOpenGL3_NewFrame();ImGui_ImplGlfw_NewFrame();ImGui::NewFrame();
        float scale=state.value("scale",1.0f);
        ImGui::SetNextWindowPos(ImVec2(state.value("x",40.0f),state.value("y",80.0f)));
        ImGui::SetNextWindowBgAlpha(state.value("opacity",.85f));
        ImGui::Begin("HUD",nullptr,ImGuiWindowFlags_NoDecoration|ImGuiWindowFlags_AlwaysAutoResize|ImGuiWindowFlags_NoInputs|ImGuiWindowFlags_NoFocusOnAppearing);
        ImGui::SetWindowFontScale(scale);
        if(state.contains("widgets")) for(auto& widget:state["widgets"]){
            if(widget.value("type","")=="text")ImGui::TextUnformatted(widget.value("content","").c_str());
            else if(widget.value("type","")=="image" && image)ImGui::Image(reinterpret_cast<void*>(static_cast<intptr_t>(image)),ImVec2(96*scale,96*scale));
        }
        ImGui::End();ImGui::Render();int fw,fh;glfwGetFramebufferSize(w,&fw,&fh);glViewport(0,0,fw,fh);glClearColor(0,0,0,0);glClear(GL_COLOR_BUFFER_BIT);ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());glfwSwapBuffers(w);
        if(++frames%30==0)write_json(argv[3],{{"display",getenv("DISPLAY")?getenv("DISPLAY"):""},{"window",x},{"external_overlay",atom_ok},{"xshape_input_empty",shape},{"transparent_framebuffer",glfwGetWindowAttrib(w,GLFW_TRANSPARENT_FRAMEBUFFER)==GLFW_TRUE},{"mapped",shown},{"frames",frames},{"compositor_visibility","unverified"},{"touch_passthrough","unverified"},{"image_loaded",image!=0}});
        std::this_thread::sleep_for(std::chrono::milliseconds(shown?16:100));
    }
    if(image)glDeleteTextures(1,&image);
    ImGui_ImplOpenGL3_Shutdown();ImGui_ImplGlfw_Shutdown();ImGui::DestroyContext();glfwDestroyWindow(w);glfwTerminate();return 0;
}
