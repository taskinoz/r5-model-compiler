// Early Apex frame movement: section-relative channels, native scalar packets.
// Independent implementation from measured layout/packet facts, not TF2 RLE.
#include "build/frame54.h"
#include "core/buffer.h"
#include "core/log.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>

namespace r2c {
Vec4 NativeFrameScales54(const std::vector<Vec4>& frames) {
    Vec4 scales;
    for (int c=0;c<4;++c) {
        float maxValue=0;
        for (const auto& frame:frames) {
            float value=(&frame.x)[c];
            if (!std::isfinite(value)) Fatal("non-finite native frame-movement sample");
            maxValue=std::max(maxValue,std::fabs(value));
        }
        (&scales.x)[c]=maxValue ? std::nextafter(maxValue/32767.f,std::numeric_limits<float>::infinity()) : 1.f/32768.f;
    }
    return scales;
}

int RetailSectionFrames54(int frames, bool clip) {
    int sections=(frames+32)/64;
    if (sections<=1 || (clip && frames<=96)) return 0;
    return (frames+sections-1)/sections;
}

std::vector<uint8_t> EncodeFrameMovement54(const std::vector<Vec4>& frames,const Vec4& scales,int requested) {
    if (frames.empty() || frames.size()>1000000) Fatal("invalid native frame-movement frame count");
    const size_t sectionFrames=requested>0 ? static_cast<size_t>(requested) : frames.size();
    if (sectionFrames+1>255) Fatal("native frame-movement section exceeds 254 frames; set sectionframes");
    const size_t sections=(frames.size()+sectionFrames-1)/sectionFrames;
    Buffer b;
    for (int c=0;c<4;++c) {
        float scale=(&scales.x)[c];
        if (!std::isfinite(scale) || scale<0) Fatal("invalid native frame-movement scale");
        b.F32(scale);
    }
    b.I32(static_cast<int32_t>(sectionFrames));
    size_t table=b.Reserve(sections*4);
    for (size_t s=0;s<sections;++s) {
        size_t first=s*sectionFrames, count=std::min(sectionFrames,frames.size()-first);
        size_t section=b.Reserve(8);
        b.PatchI32(table+s*4,static_cast<int32_t>(section));
        for (int c=0;c<4;++c) {
            std::vector<int16_t> samples;
            bool zero=true;
            // Include the next sample for interpolation across a section boundary.
            for (size_t i=0;i<=count;++i) {
                float value=(&frames[std::min(first+i,frames.size()-1)].x)[c], step=(&scales.x)[c];
                float q=step ? std::round(value/step) : 0;
                if (!std::isfinite(value) || !std::isfinite(q) || q < -32768 || q > 32767)
                    Fatal("native frame-movement sample exceeds signed 16-bit range");
                if (std::fabs(value-q*step)>(c<3 ? .001f : .005f))
                    Fatal("native frame-movement quantization budget exceeded");
                samples.push_back(static_cast<int16_t>(q)); zero &= q==0;
            }
            if (zero) continue;
            size_t offset=b.Tell()-section;
            if (offset>65535) Fatal("native frame-movement channel offset overflow");
            b.PatchAt<uint16_t>(section+c*2,static_cast<uint16_t>(offset));
            b.U8(0); b.U8(static_cast<uint8_t>(samples.size()));
            for (auto q:samples) b.I16(q);
        }
    }
    b.Align(4);
    return b.Data();
}

void ValidateFrameMovement54(const std::vector<uint8_t>& data,int frames) {
    auto span=[&](size_t p,size_t n) {
        if (p>data.size() || n>data.size()-p) Fatal("native frame-movement span outside file");
    };
    auto i32=[&](size_t p) { span(p,4); int32_t v; std::memcpy(&v,data.data()+p,4); return v; };
    auto u16=[&](size_t p) { span(p,2); uint16_t v; std::memcpy(&v,data.data()+p,2); return v; };
    span(0,20);
    if (frames<1 || frames>1000000) Fatal("invalid native frame-movement frame count");
    float scales[4]; std::memcpy(scales,data.data(),16);
    for (float scale:scales) if (!std::isfinite(scale) || scale<0) Fatal("invalid native frame-movement scale");
    int sf=i32(16);
    if (sf<1 || sf>1000000) Fatal("invalid native frame-movement section size");
    size_t sections=(static_cast<size_t>(frames)-1)/sf+1, header=20+sections*4;
    span(20,sections*4);
    for (size_t s=0;s<sections;++s) {
        int32_t section=i32(20+s*4);
        if (section<0 || static_cast<size_t>(section)<header) Fatal("invalid native frame-movement section offset");
        span(section,8);
        int count=std::min(sf,frames-static_cast<int>(s)*sf);
        for (int c=0;c<4;++c) {
            size_t off=u16(section+c*2);
            if (!off) continue;
            if (off<8) Fatal("invalid native frame-movement channel offset");
            size_t p=static_cast<size_t>(section)+off;
            int covered=0;
            while (covered<count) {
                span(p,2); int mode=data[p],total=data[p+1];
                if (mode>19 || !total) Fatal("invalid native frame-movement packet");
                int coefficients=mode>=2 ? (mode-2)%6 : 0;
                int bits=mode>=14 ? 4 : mode>=8 ? 2 : 0;
                size_t words=mode==0 ? 1+total : mode==1 ? 2+total/2 : 2+coefficients+(bits*total+15)/16;
                span(p,words*2);
                if (mode==1) {
                    int base=static_cast<int16_t>(u16(p+2));
                    for (int f=1; f<total; ++f) {
                        int value=base+static_cast<int8_t>(data[p+3+f]);
                        if (value < -32768 || value > 32767) Fatal("native frame-movement byte-delta overflow");
                    }
                }
                // A conservative finite-value bound also rejects scale overflow.
                double bound=32768.0*(1+coefficients)+15;
                if (bound*scales[c]>std::numeric_limits<float>::max()) Fatal("native frame-movement value overflow");
                covered+=total; p+=words*2;
            }
        }
    }
}
}
