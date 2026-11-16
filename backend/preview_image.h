#pragma once
#include <algorithm>
#include <cstddef>

struct PreviewAlphaBounds {int left,top,width,height;};
// Remove only fully transparent canvas. Keep every nonzero-alpha pixel (including
// mana crystals, shadows and decorative glows), plus one source pixel of guard.
// Called during background decode; original cached PNGs remain untouched.
inline PreviewAlphaBounds preview_alpha_bounds(const unsigned char* rgba,int width,int height){
    if(!rgba || width<=0 || height<=0)return {0,0,0,0};
    int left=width,top=height,right=-1,bottom=-1;
    for(int y=0;y<height;++y)for(int x=0;x<width;++x){
        if(rgba[(size_t(y)*width+x)*4+3]){
            left=std::min(left,x);right=std::max(right,x);top=std::min(top,y);bottom=std::max(bottom,y);
        }
    }
    if(right<left)return {0,0,width,height};
    left=std::max(0,left-1);top=std::max(0,top-1);
    right=std::min(width-1,right+1);bottom=std::min(height-1,bottom+1);
    return {left,top,right-left+1,bottom-top+1};
}
