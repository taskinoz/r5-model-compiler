// r5studiomdl: early Apex (MDL v54) model compiler.
//
// Command line mirrors Valve's studiomdl so Crowbar can drive it:
//   r5studiomdl --target s0 [-game <dir>] [-o <out.rmdl>] model.qc
// Output goes to <game>/models/<$modelname>, or next to the QC when -game is absent.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include <map>

#include "build/context.h"
#include "core/log.h"
#include "core/strings.h"
#include "qc/qc.h"
#include "write/writers.h"

using namespace r2c;

static void Usage() {
    std::printf(
        "r5studiomdl - Apex early-season model compiler (MDL v54)\n"
        "usage: r5studiomdl --target <s0|s1|s2|s3> [options] <file.qc>\n"
        "  --target       required season; s0/s1 use VTX/VVD, s2/s3 use VG rev1\n"
        "  --material-guid <name=hex> bind a material to an existing RPak asset\n"
        "  --list-targets show supported compiler profiles\n"
        "  -game <dir>     game/mod directory; output is written to <dir>/models/<$modelname>\n"
        "  -o <file>       write the .mdl to this exact path\n"
        "  -outdir <dir>   write to <dir>/<$modelname>\n"
        "  -path <dir>     extra directory to search for SMD/DMX files (repeatable)\n"
        "  -verbose        more output\n"
        "  -quiet          errors and warnings only\n"
        "  -nop4, -nox360, -fullcollide and other studiomdl flags are accepted and ignored\n");
}

int main(int argc, char** argv) {
    std::string qc, game, outFile, outDir, target;
    std::map<std::string,uint64_t> materials;
    QcOptions opt;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) {
                std::fprintf(stderr, "ERROR: %s needs a value\n", a.c_str());
                std::exit(1);
            }
            return argv[++i];
        };
        if (a.size() > 1 && a[0] == '-') {
            std::string l = ToLower(a);
            if (l == "--target") target = ToLower(next());
            else if (l == "--list-targets") {
                std::puts("s0  MDL54 / mdl_ v8 / VTX7 + VVD4\ns1  MDL54 / mdl_ v8 / VTX7 + VVD4\ns2  MDL54 / mdl_ v9 / VG rev1\ns3  MDL54 / mdl_ v10 / VG rev1\nretail: planned; unavailable");
                return 0;
            }
            else if (l == "--material-guid") {
                auto value=next(); auto eq=value.find('=');
                if(eq==std::string::npos) { std::fprintf(stderr,"ERROR: material binding needs name=hex\n"); return 1; }
                try {
                    size_t used=0; auto hex=value.substr(eq+1);
                    auto guid=std::stoull(hex,&used,16);
                    if(used!=hex.size() || eq==0 || !guid) throw std::invalid_argument("GUID");
                    materials[value.substr(0,eq)]=guid;
                } catch(...) { std::fprintf(stderr,"ERROR: invalid material GUID\n"); return 1; }
            }
            else if (l == "-game") game = next();
            else if (l == "-o" || l == "-out") outFile = next();
            else if (l == "-outdir") outDir = next();
            else if (l == "-path") opt.searchPaths.push_back(next());
            else if (l == "-verbose" || l == "-v") SetLogLevel(LogLevel::Verbose);
            else if (l == "-quiet") SetLogLevel(LogLevel::Quiet);
            else if (l == "-h" || l == "-help" || l == "--help") {
                Usage();
                return 0;
            } else if (l == "-t" || l == "-a" || l == "-minlod") {
                next();
            } else {
                // -nop4, -nox360, -fullcollide, -allowdebug, ... : not applicable
            }
        } else {
            qc = a;
        }
    }
    if (qc.empty()) {
        Usage();
        return 1;
    }
    if(target!="s0" && target!="s1" && target!="s2" && target!="s3") {
        std::fprintf(stderr,"ERROR: choose --target s0, s1, s2 or s3; retail is not implemented\n");
        return 1;
    }
    if (GetExtension(qc).empty()) qc += ".qc";
    auto t0 = std::chrono::steady_clock::now();
    try {
        Info("qdir:    \"%s\"", DirName(std::filesystem::absolute(std::filesystem::u8path(qc)).u8string()).c_str());
        if (!game.empty()) Info("gamedir: \"%s\"", game.c_str());
        Info("Working on \"%s\"", qc.c_str());
        auto def = ParseQC(qc, opt);
        if(def->collision.present) Fatal("Apex native physics/BVH compilation is not implemented yet");
        CompiledModel model = Build(*def);
        model.name = def->modelName;
        if(EndsWithI(model.name,".mdl")) model.name.resize(model.name.size()-4);
        if(!EndsWithI(model.name,".rmdl")) model.name += ".rmdl";
        if(model.flags & 0x4000) Fatal("Apex complex skinning is not implemented yet");
        for(const auto& binding:materials) {
            bool found=false;
            for(const auto& name:model.textures) if(name==binding.first) found=true;
            if(!found) Fatal("material binding '%s' does not match a texture slot",binding.first.c_str());
        }
        if (!model.physics.phy.empty()) Fatal("Apex native physics/BVH compilation is not implemented yet");
        if (!model.uiPanels.empty()) Fatal("Apex RUI compilation is not implemented yet");
        for(auto& bone:model.bones) if(bone.proctype || bone.jiggle>=0)
            Fatal("Apex procedural-bone compilation is not implemented yet");
        for(auto& anim:model.animations) if(!anim.ikRules.empty() || !anim.frameMovement.empty() || !anim.movements.empty())
            Fatal("Apex IK rules and root-motion tracks are not implemented yet");
        if(!model.boneFollowers.empty() || !model.includeModels.empty())
            Fatal("Apex followers and external animation rigs are not implemented yet");
        if(!model.nodeNames.empty()) Fatal("Apex transition nodes are not implemented yet");
        std::vector<uint8_t> mdl = WriteMDL(model);
        auto read32=[&](size_t p) { int32_t v; std::memcpy(&v,mdl.data()+p,4); return v; };
        int checksum=read32(8);
        int textures=read32(0xD4);
        for(size_t i=0;i<model.textures.size();++i) {
            auto it=materials.find(model.textures[i]);
            if(it!=materials.end()) std::memcpy(mdl.data()+textures+i*12+4,&it->second,8);
        }
        std::vector<uint8_t> vg;
        if(target=="s2" || target=="s3") {
            vg=WriteVG(model);
            // Baked VG profiles have no legacy component spans.
            std::memset(mdl.data()+0x1C0,0,12);
            std::memset(mdl.data()+0x1D0,0,12);
        }

        std::filesystem::path out;
        if (!outFile.empty())
            out = std::filesystem::u8path(outFile);
        else if (!outDir.empty())
            out = std::filesystem::u8path(outDir) / std::filesystem::u8path(FixSlashes(model.name));
        else if (!game.empty())
            out = std::filesystem::u8path(game) / "models" / std::filesystem::u8path(FixSlashes(model.name));
        else
            out = std::filesystem::u8path(def->qcDir) / std::filesystem::u8path(FileBase(FixSlashes(model.name)) + ".mdl");
        out.replace_extension(".rmdl");
        std::error_code ec;
        if (out.has_parent_path()) std::filesystem::create_directories(out.parent_path(), ec);
        Info("---------------------");
        Info("writing %s:", out.u8string().c_str());
        std::ofstream f(out, std::ios::binary);
        if (!f) Fatal("could not write %s", out.u8string().c_str());
        f.write(reinterpret_cast<const char*>(mdl.data()), static_cast<std::streamsize>(mdl.size()));
        f.close();
        auto write=[&](const char* extension,const std::vector<uint8_t>& data) {
            auto path=out; path.replace_extension(extension);
            std::ofstream stream(path,std::ios::binary);
            if(!stream) Fatal("could not write %s",path.u8string().c_str());
            stream.write(reinterpret_cast<const char*>(data.data()),std::streamsize(data.size()));
            if(!stream) Fatal("failed writing %s",path.u8string().c_str());
        };
        if(!vg.empty()) write(".vg",vg);
        else if(read32(0x1D0)>0) {
            write(".dx11.vtx",WriteVTX(model,checksum));
            write(".vvd",WriteVVD(model,checksum));
            if(model.hasVertexColor || model.hasUV2) write(".vvc",WriteVVC(model,checksum));
        }
        if(!f) Fatal("failed writing model");
        int verts = 0, tris = 0;
        for (auto& bp : model.bodyParts)
            for (auto& md : bp.models) {
                verts += md.NumVerts();
                for (auto& me : md.meshes)
                    if (!me.lods.empty()) tris += static_cast<int>(me.lods[0].indices.size() / 3);
            }
        Info("bones       %7d", static_cast<int>(model.bones.size()));
        Info("vertices    %7d", verts);
        Info("triangles   %7d", tris);
        Info("sequences   %7d", static_cast<int>(model.sequences.size()));
        Info("animations  %7d", static_cast<int>(model.animations.size()));
        Info("total       %7d", static_cast<int>(mdl.size()));
        double secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        Info("Completed \"%s\" in %.2f seconds (%d warnings)", qc.c_str(), secs, WarningCount());
    } catch (const CompileError& e) {
        std::printf("ERROR: %s\n", e.what());
        return 1;
    } catch (const std::exception& e) {
        std::printf("ERROR: internal: %s\n", e.what());
        return 2;
    }
    return 0;
}
