// Early Apex (S2/S3) revision-1 vertex group. Positions stay float32.
#include "write/writers.h"
#include "core/buffer.h"
#include "core/log.h"
#include <algorithm>
#include <cmath>

namespace r2c {
namespace {
uint32_t Normal(const CVertex& v) {
    Vec3 n = v.normal;
    int major = 0;
    for (int i = 1; i < 3; ++i) if (std::fabs(n[i]) > std::fabs(n[major])) major = i;
    if (std::fabs(n[major]) < 1e-12f) Fatal("cannot pack a zero vertex normal");
    int a=(major+1)%3, b=(major+2)%3;
    auto quant = [&](int axis) { return uint32_t(std::clamp(std::lround(n[axis]*255.f/std::fabs(n[major])+256.f),0L,511L)); };
    // Frisvad basis; tangent is represented by its angle around the normal.
    Vec3 u, w;
    if (n.z < -.9999f) { u=Vec3(0,-1,0); w=Vec3(-1,0,0); }
    else {
        float k=1.f/(1.f+n.z);
        u=Vec3(1-n.x*n.x*k,-n.x*n.y*k,-n.x);
        w=Vec3(-n.x*n.y*k,1-n.y*n.y*k,-n.y);
    }
    Vec3 t(v.tangent.x,v.tangent.y,v.tangent.z);
    float angle=std::atan2(Dot(t,w),Dot(t,u));
    if (angle < 0) angle += 2*kPi;
    uint32_t tangent=uint32_t(std::lround(angle*1023.f/(2*kPi))) & 1023;
    return tangent | (quant(b)<<10) | (quant(a)<<19) | (uint32_t(n[major]<0)<<28)
        | (uint32_t(major)<<29) | (uint32_t(v.tangent.w<0)<<31);
}
}
std::vector<uint8_t> WriteVG(const CompiledModel& m) {
    Buffer out, vertices, indices, strips;
    out.Reserve(0x100);
    out.PatchI32(0,0x47567430); out.PatchI32(4,1);
    size_t meshCount=0;
    for (auto& bp:m.bodyParts) for (auto& md:bp.models) meshCount+=md.meshes.size();
    size_t meshes=out.Reserve(meshCount*m.numLods*0x48);
    size_t lods=out.Reserve(m.numLods*8);
    size_t ordinal=0;
    for (int lod=0; lod<m.numLods; ++lod) {
        if (ordinal > 65535 || meshCount > 65535) Fatal("VG mesh count exceeds uint16 range");
        out.PatchAt<uint16_t>(lods+lod*8,uint16_t(ordinal));
        out.PatchAt<uint16_t>(lods+lod*8+2,uint16_t(meshCount));
        out.PatchAt<float>(lods+lod*8+4,lod<int(m.lodSwitch.size())?m.lodSwitch[lod]:0.f);
        for (auto& bp:m.bodyParts) for (auto& md:bp.models) for (auto& mesh:md.meshes) {
            size_t p=meshes+ordinal*0x48;
            const auto& tris=mesh.lods[lod].indices;
            uint32_t count=uint32_t(mesh.lodVertexCount[lod]);
            if (count>65535) Fatal("VG mesh exceeds 65535 vertices");
            bool weights=m.bones.size()>1;
            uint64_t flags=1|0x200|(uint64_t(2)<<24);
            uint32_t stride=24;
            if(weights) { flags|=0x5000; stride+=8; }
            if(m.hasVertexColor) { flags|=0x10; stride+=4; }
            if(m.hasUV2) { flags|=uint64_t(2)<<32; stride+=8; }
            out.PatchAt<uint64_t>(p,flags);
            out.PatchI32(p+8,int(vertices.Size())); out.PatchI32(p+12,stride);
            out.PatchI32(p+16,count);
            out.PatchI32(p+32,int(indices.Size()/2)); out.PatchI32(p+36,int(tris.size()));
            out.PatchI32(p+48,int(strips.Size()/0x23)); out.PatchI32(p+52,1);
            for(uint32_t i=0;i<count;++i) {
                const auto& v=mesh.verts[i]; vertices.V3(v.pos);
                if(weights) {
                    int w0=int(std::lround(v.weight[0]*32767));
                    int w1=v.numBones>1?std::min(32767-w0,int(std::lround(v.weight[1]*32767))):0;
                    vertices.U16(uint16_t(w0)); vertices.U16(uint16_t(w1));
                    for(int j=0;j<3;++j) vertices.U8(v.bone[j]);
                    vertices.U8(uint8_t(v.numBones-1));
                }
                vertices.U32(Normal(v));
                if(m.hasVertexColor) vertices.Bytes(v.color,4);
                vertices.V2(v.uv); if(m.hasUV2) vertices.V2(v.uv2);
            }
            for(uint32_t i:tris) {
                if(i>=count) Fatal("VG triangle index outside LOD vertex span");
                indices.U16(uint16_t(i));
            }
            strips.I32(int(tris.size())); strips.I32(0); strips.I32(count); strips.I32(0);
            strips.I16(int16_t(m.bones.size())); strips.U8(1); strips.Zero(16);
            ++ordinal;
        }
    }
    auto pair=[&](size_t field,size_t offset,size_t count) {
        out.PatchAt<uint64_t>(field,offset); out.PatchAt<uint64_t>(field+8,count);
    };
    pair(0x20,meshes,ordinal); pair(0x70,lods,m.numLods);
    pair(0x30,out.Size(),indices.Size()/2); out.Append(indices); out.Align(4);
    pair(0x40,out.Size(),vertices.Size()); out.Append(vertices); out.Align(4);
    pair(0x90,out.Size(),strips.Size()/0x23); out.Append(strips);
    out.PatchI32(12,int(out.Size()));
    return out.Data();
}
}
