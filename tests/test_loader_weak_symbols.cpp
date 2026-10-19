// Synthetic host boundary for the actual patched loader, not a second resolver.
// The Python integration test extracts the full loader target from the patch.
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
namespace nx {
struct CPU { uint64_t x[32]{}; };
using Fn = void (*)(CPU&);
using HleFn = Fn;
struct FuncEntry { uint64_t offset; Fn fn; };
struct Reloc { uint64_t offset; uint32_t type, sym; int64_t addend; };
struct Symbol { const char* name; uint64_t value, size; uint8_t type, bind, imported; };
struct ModuleInfo {
    const char* name; uint64_t base, text, text_size, ro, ro_size, data, data_size, bss, bss_size;
    const FuncEntry* funcs; size_t func_count; const Reloc* relocs; size_t reloc_count;
    const Symbol* symbols; size_t symbol_count; const uint64_t* init_array; size_t init_count;
    const uint64_t* fini_array; size_t fini_count;
};
struct LoadedModule { const ModuleInfo* info; uint64_t base, size; Fn* table; };
struct HleRegistrar { HleRegistrar(const char*, HleFn); };
constexpr uint64_t kThunkBase = 0x2000000000ull, kThunkSize = 0x1000;
constexpr uint32_t R_AARCH64_ABS64=257, R_AARCH64_GLOB_DAT=1025,
    R_AARCH64_JUMP_SLOT=1026, R_AARCH64_RELATIVE=1027;
constexpr int kMemCode=1, kMemCodeData=2;
bool commit(uint64_t, uint64_t) { return true; }
void vm_set(uint64_t, uint64_t, int, int) {}
void backtrace(CPU&) {}
std::string describe(uint64_t);
namespace plat {
std::string data_root() { return "."; }
void log_line(const char* s) { std::cout << s << '\n'; }
[[noreturn]] void exit_process(int) { throw std::runtime_error("loader fatal"); }
}
}
#include "loader.cpp"

void check(bool value) { if (!value) throw std::logic_error("fixture assertion failed"); }
void hle(nx::CPU& c) { c.x[0] = 73; }
int main(int argc, char** argv) {
    using namespace nx;
    if (argc != 3) return 2;
    std::string mode=argv[1], dir=argv[2];
    alignas(4096) uint64_t memory[512]{};
    for (auto& word : memory) word=0xfefefefefefefefeull; // Prove zero overwrites the initial PLT/GOT.
    std::ofstream file(dir+"/fixture.bin", std::ios::binary);
    file.write(reinterpret_cast<char*>(memory), sizeof memory); file.close();
    Symbol symbol{"optional", 0, 0, 0, 2, 1};
    Reloc relocs[16]{}; size_t nr=0;
    ModuleInfo mod{"fixture", reinterpret_cast<uint64_t>(memory), 0, 16, 16, 16,
        32, 4064, 4096, 0, nullptr, 0, relocs, 0, &symbol, 1, nullptr, 0, nullptr, 0};
    alignas(4096) uint64_t provider_memory[512]{};
    std::ofstream provider_file(dir+"/provider.bin", std::ios::binary);
    provider_file.write(reinterpret_cast<char*>(provider_memory), sizeof provider_memory); provider_file.close();
    Symbol definition{"optional",128,0,1,1,0};
    ModuleInfo provider=mod;
    provider.name="provider"; provider.base=reinterpret_cast<uint64_t>(provider_memory);
    provider.symbols=&definition; provider.reloc_count=0;
    const ModuleInfo* mods[]={&mod,&provider};
    size_t module_count=1;
    bool fatal_expected=false;
    if (mode=="weak") {
        for (auto type : {R_AARCH64_GLOB_DAT, R_AARCH64_JUMP_SLOT, R_AARCH64_ABS64})
            for (int64_t addend : {0, 7, -8}) {
                relocs[nr]={64+nr*8, type, 0, addend}; ++nr;
            }
    } else {
        relocs[nr++]={64,R_AARCH64_GLOB_DAT,0,0};
        if (mode=="strong-data") { symbol.bind=1; symbol.type=1; fatal_expected=true; }
        else if (mode=="strong-function") { symbol.bind=1; symbol.type=2;
            relocs[0].type=R_AARCH64_JUMP_SLOT; fatal_expected=true; }
        else if (mode=="strong-notype") { symbol.bind=1; fatal_expected=true; }
        else if (mode=="unknown") { relocs[0].type=9999; fatal_expected=true; }
        else if (mode=="defined") { symbol.imported=0; symbol.value=128; }
        else if (mode=="hle") { symbol.type=2; HleRegistrar reg("optional", hle); }
        else if (mode=="export") module_count=2;
        else if (mode=="missing-call") symbol.type=2;
        else if (mode=="weak-function" || mode=="null-call") symbol.type=2;
        else if (mode=="weak-object") symbol.type=1;
        else return 2;
    }
    mod.reloc_count=nr;
    bool failed=false;
    try { load_modules(mods,module_count,dir); }
    catch (const std::runtime_error&) { failed=true; }
    check(failed==fatal_expected);
    if (!failed) {
        for (size_t i=0;i<nr;++i) {
            uint64_t expected=uint64_t(relocs[i].addend);
            if (mode=="defined") expected=mod.base+128;
            if (mode=="hle") expected=kThunkBase;
            if (mode=="export") expected=provider.base+128;
            check(memory[relocs[i].offset/8]==expected);
        }
        if (mode=="null-call") {
            CPU c{}; bool trapped=false;
            try { call(c,memory[8]); } catch (const std::runtime_error&) { trapped=true; }
            check(trapped);
        }
        if (mode=="missing-call") {
            CPU c{}; bool trapped=false;
            try { call(c,hle_address("unimplemented")); }
            catch (const std::runtime_error&) { trapped=true; }
            check(trapped);
        }
        if (mode=="hle") { CPU c{}; call(c,memory[8]); check(c.x[0]==73); }
    }
    std::cout << "PASS " << mode << '\n';
}
