#pragma once
#include <xcb/xcb.h>
#include <cstdlib>
#include "hud_state.h"

// Read only: no window, event selection, focus, pointer grab or pointer warp.
// XCB handles a disappearing game Xwayland connection without Xlib's fatal
// I/O handler terminating the independent HUD rendering connection.
class GamePointer {
    xcb_connection_t* connection=nullptr;
    std::string address;
    xcb_window_t root=0;
    double retry_after=0;
    void close(){if(connection)xcb_disconnect(connection);connection=nullptr;root=0;}
public:
    struct Sample {bool valid=false;int x=0,y=0,width=0,height=0;std::string error;};
    GamePointer()=default;
    GamePointer(const GamePointer&)=delete;
    GamePointer& operator=(const GamePointer&)=delete;
    ~GamePointer(){close();}
    void reset(){close();address.clear();retry_after=0;}
    Sample sample(const std::string& display,double now){
        Sample result;
        if(display!=address){reset();address=display;}
        if(!local_x11_display(display)){result.error="invalid_game_display";return result;}
        if(now<retry_after){result.error="game_display_reconnect_wait";return result;}
        if(!connection){
            int screen_number=0;
            connection=xcb_connect(display.c_str(),&screen_number);
            if(!connection || xcb_connection_has_error(connection)){
                close();retry_after=now+5;result.error="game_display_connect_failed";return result;
            }
            auto screen=xcb_setup_roots_iterator(xcb_get_setup(connection));
            while(screen_number-- > 0 && screen.rem)xcb_screen_next(&screen);
            if(!screen.rem){close();retry_after=now+5;result.error="game_display_screen_missing";return result;}
            root=screen.data->root;
        }
        // Both requests go to the GAME connection. Never pass an overlay XID
        // from the other server to XTranslateCoordinates or any game request.
        auto pointer_cookie=xcb_query_pointer(connection,root);
        auto geometry_cookie=xcb_get_geometry(connection,root);
        xcb_generic_error_t* pointer_error=nullptr; 
        xcb_generic_error_t* geometry_error=nullptr;
        auto pointer=xcb_query_pointer_reply(connection,pointer_cookie,&pointer_error);
        auto geometry=xcb_get_geometry_reply(connection,geometry_cookie,&geometry_error);
        if(pointer && geometry && !pointer_error && !geometry_error && pointer->same_screen && geometry->width && geometry->height){
            result={true,pointer->root_x,pointer->root_y,geometry->width,geometry->height,""};
        }else result.error="game_pointer_query_failed";
        std::free(pointer);std::free(geometry);std::free(pointer_error);std::free(geometry_error);
        if(xcb_connection_has_error(connection)){close();retry_after=now+5;result.error="game_display_disconnected";result.valid=false;}
        return result;
    }
};
