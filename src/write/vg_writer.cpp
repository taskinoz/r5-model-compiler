// Early Apex (S2/S3) revision-1 vertex group.
#include "write/writers.h"
#include "core/buffer.h"
#include "core/log.h"
#include <algorithm>
#include <cmath>
#include <map>

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
    Buffer out, vertices, indices, strips, extraWeights;
    const bool complex=m.HasComplexWeights();
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
            uint64_t flags=(m.packedPositions ? 2 : 1)|0xA40|(uint64_t(2)<<24);
            uint32_t stride=m.packedPositions ? 20 : 24;
            if(weights) { flags|=0x5000; stride+=8; }
            if(m.hasVertexColor) { flags|=0x10; stride+=4; }
            if(m.hasUV2) { flags|=uint64_t(2)<<32; stride+=8; }
            out.PatchAt<uint64_t>(p,flags);
            out.PatchI32(p+8,int(vertices.Size())); out.PatchI32(p+12,stride);
            out.PatchI32(p+16,count);
            size_t extraBase=extraWeights.Size();
            std::map<std::vector<int16_t>,uint16_t> extraLookup;
            out.PatchI32(p+24,int(extraBase));
            out.PatchI32(p+32,int(indices.Size()/2)); out.PatchI32(p+36,int(tris.size()));
            out.PatchI32(p+48,int(strips.Size()/0x23)); out.PatchI32(p+52,1);
            for(uint32_t i=0;i<count;++i) {
                const auto& v=mesh.verts[i];
                if(m.packedPositions) {
                    uint64_t packed=0;
                    for(int axis=0;axis<3;++axis) {
                        double bias=axis==2 ? 2048.0 : 1024.0;
                        double scaled=(double(v.pos[axis])+bias)*1024.0;
                        double quant=std::round(scaled);
                        uint64_t limit=axis==2 ? 0x3FFFFF : 0x1FFFFF;
                        if(!std::isfinite(scaled) || quant<0 || quant>double(limit) ||
                           std::fabs(quant/1024.0-bias-double(v.pos[axis]))>0.0001)
                            Fatal("packed VG position exceeds native range or 0.0001-inch error budget");
                        packed |= uint64_t(quant) << (axis*21);
                    }
                    vertices.Put(packed);
                } else vertices.V3(v.pos);
                if(weights) {
                    const auto packed=PackWeights(v.weight,v.numBones);
                    vertices.I16(packed[0]);
                    if(complex) {
                        std::vector<int16_t> middle;
                        for(int j=1;j<v.numBones-1;++j) {
                            middle.push_back(packed[j]); middle.push_back(v.bone[j]);
                        }
                        uint16_t index=0;
                        if(!middle.empty()) {
                            auto found=extraLookup.find(middle);
                            if(found!=extraLookup.end()) index=found->second;
                            else {
                                size_t next=(extraWeights.Size()-extraBase)/4;
                                if(next>65535) Fatal("VG mesh extra-weight index exceeds uint16 range");
                                index=uint16_t(next); extraLookup.emplace(middle,index);
                                for(int16_t value:middle) extraWeights.I16(value);
                            }
                        }
                        vertices.U16(index);
                        vertices.U8(v.bone[0]); vertices.U8(v.bone[v.numBones-1]); vertices.U8(0);
                    } else {
                        vertices.I16(v.numBones>1?packed[1]:0);
                        for(int j=0;j<3;++j) vertices.U8(v.bone[j]);
                    }
                    vertices.U8(uint8_t(v.numBones-1));
                }
                vertices.U32(Normal(v));
                if(m.hasVertexColor) vertices.Bytes(v.color,4);
                vertices.V2(v.uv); if(m.hasUV2) vertices.V2(v.uv2);
            }
            out.PatchI32(p+28,int(extraWeights.Size()-extraBase));
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
    // Native files reserve one 48-byte auxiliary record per studio mesh, not
    // per LOD. The payload is not preserved data: zero initialization is enough
    // for R5R to render, while omitting the allocation suppresses drawing.
    // Its individual fields remain unknown.
    pair(0x60,out.Size(),meshCount);
    out.Zero(meshCount*48);
    pair(0x10,out.Size(),0);
    if(m.bones.size()>1) {
        pair(0x10,out.Size(),m.bones.size());
        for(size_t bone=0;bone<m.bones.size();++bone) out.U8(static_cast<uint8_t>(bone));
        out.Align(4);
    }
    pair(0x20,meshes,ordinal); pair(0x70,lods,m.numLods);
    pair(0x30,out.Size(),indices.Size()/2); out.Append(indices); out.Align(4);
    pair(0x40,out.Size(),vertices.Size()); out.Append(vertices); out.Align(4);
    pair(0x50,out.Size(),extraWeights.Size());
    out.Append(extraWeights); out.Align(4);
    pair(0x80,out.Size(),0);
    pair(0x90,out.Size(),strips.Size()/0x23); out.Append(strips);
    out.PatchI32(12,int(out.Size()));
    return out.Data();
}
}
