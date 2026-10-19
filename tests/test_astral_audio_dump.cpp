// Original synthetic host boundary for astral-audio-dump.patch: the composed hle_audio.cpp with a muted host (no
// audio device, as with NX_MUTE), its AudioOut HLE driven through the real registry, and its render-mix dump entry.
// Modes (argv[1]): audioout, renderer, seconds, fail, unset. tests/test_astral_audio_dump.py checks the files.
#include <cassert>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <thread>
#include "kernel.h"
#include "platform.h"
namespace nx {
std::map<uint32_t, std::shared_ptr<KObject>> handles;
std::mutex host_lock;
std::vector<std::pair<uint64_t, uint64_t>> regions;
void region(void* p, size_t n) { regions.push_back({reinterpret_cast<uint64_t>(p), n}); }
VmInfo vm_query(uint64_t a) {
    for (auto [p, n] : regions)
        if (a >= p && a - p < n) return {p, n, kMemHeap, 3};
    return {a, 4096, kMemFree, 0};
}
bool commit(uint64_t, uint64_t) { return true; }
void vm_set(uint64_t, uint64_t, uint32_t, uint32_t) {}
uint64_t kernel_alloc(uint64_t, uint64_t) { throw std::runtime_error("unexpected allocation"); }
void backtrace(CPU&) {}
uint32_t handle_add(std::shared_ptr<KObject> o) {
    static uint32_t next = 1;
    handles[++next] = o;
    return next;
}
void event_signal(const std::shared_ptr<EventState>& e) { std::lock_guard lk(host_lock); e->signaled = true; }
void event_clear(const std::shared_ptr<EventState>& e) { std::lock_guard lk(host_lock); e->signaled = false; }
namespace plat {
bool audio_open(AudioDone) { return false; }  // muted: NX_MUTE / headless / no device
bool audio_submit(const void*, size_t, void*) { throw std::runtime_error("muted host got a submission"); }
uint32_t audio_queued() { return 0; }
uint64_t monotonic_ns() { return 0; }
void sleep_ns(int64_t) {}
std::string data_root() { return "."; }
void log_line(const char* l) { std::cerr << l << "\n"; }
[[noreturn]] void exit_process(int) { throw std::runtime_error("strict fatal"); }
}  // namespace plat
}  // namespace nx
#include "loader.cpp"
#include "hle_audio.cpp"
using namespace nx;
uint64_t invoke(const char* suffix, uint64_t a = 0, uint64_t b = 0, uint64_t d = 0, uint64_t e = 0) {
    auto s = std::string("_ZN2nn5audio") + suffix;
    assert(hle_lookup(s.c_str()));
    CPU c{};
    c.x[0] = a, c.x[1] = b, c.x[2] = d, c.x[3] = e;
    call(c, hle_address(s.c_str()));
    return c.x[0];
}
void attach(CPU& c) {
    st<uint32_t>(c.x[0] + 0x14, uint32_t(c.x[1]));
    st<uint32_t>(c.x[0] + 0x18, uint32_t(c.x[3]));
    st<uint8_t>(c.x[0] + 0x28, 1);
}
// Frame k of the synthetic signal: left k, right -k (never 0 from k = 1).
void fill(int16_t* pcm, size_t frames, int first) {
    for (size_t k = 0; k < frames; k++) pcm[2 * k] = int16_t(first + int(k)), pcm[2 * k + 1] = int16_t(-(first + int(k)));
}
int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "";
    if (mode == "audioout") {  // NX_AUDIO_DUMP_SECONDS=0: the whole session, AudioOut owns the file
        const char* attach_name = "_ZN2nn2os17AttachSystemEventEPNS0_15SystemEventTypeEjbjbNS0_14EventClearModeE";
        HleRegistrar reg(attach_name, attach);
        g_exports[attach_name] = hle_address(attach_name);
        alignas(16) uint8_t out[0x178]{}, event[0x30]{}, param[8]{};
        alignas(4096) static int16_t pcm[4][2048];  // 4 buffers of 1024 frames (4096 bytes)
        alignas(8) uint64_t buffers[4][5]{};
        std::memset(pcm[0], 0, sizeof pcm[0]);  // leading silence: not dumped
        fill(pcm[1], 1024, 1), fill(pcm[2], 1024, 1025), fill(pcm[3], 1024, 2049);
        region(out, sizeof out), region(event, sizeof event), region(param, sizeof param), region(pcm, sizeof pcm),
            region(buffers, sizeof buffers);
        auto o = reinterpret_cast<uint64_t>(out), ev = reinterpret_cast<uint64_t>(event), pa = reinterpret_cast<uint64_t>(param);
        invoke("27InitializeAudioOutParameterEPNS0_17AudioOutParameterE", pa);
        assert(invoke("19OpenDefaultAudioOutEPNS0_8AudioOutEPNS_2os11SystemEventERKNS0_17AudioOutParameterE", o, ev, pa) == 0);
        for (int k = 0; k < 4; k++) {
            auto b = reinterpret_cast<uint64_t>(buffers[k]);
            invoke("21SetAudioOutBufferInfoEPNS0_14AudioOutBufferEPvmm", b, reinterpret_cast<uint64_t>(pcm[k]), 4096, 4096);
            assert(invoke("20AppendAudioOutBufferEPNS0_8AudioOutEPNS0_14AudioOutBufferE", o, b) == 1);
        }
        assert(invoke("13StartAudioOutEPNS0_8AudioOutE", o) == 0);
        int released = 0;
        auto until = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (released < 4) {
            assert(std::chrono::steady_clock::now() < until);
            if (invoke("25GetReleasedAudioOutBufferEPNS0_8AudioOutE", o)) released++;
            else std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        int16_t mix[240 * 2];
        fill(mix, 240, 7000);
        dump_pcm(kDumpRenderer, mix, 240);  // another source while AudioOut owns the file: ignored
        invoke("12StopAudioOutEPNS0_8AudioOutE", o);
        invoke("13CloseAudioOutEPNS0_8AudioOutE", o);
        std::cout << "PASS audioout: 4 buffers played on a muted host\n";
    } else if (mode == "renderer" || mode == "seconds") {  // the renderer's 5 ms frames; 10 s default or 1 s
        int16_t mix[240 * 2] = {};
        for (int k = 0; k < 3; k++) dump_pcm(kDumpRenderer, mix, 240);  // silence first
        for (int k = 0; k < 2100; k++) {
            fill(mix, 240, 1 + (k * 240) % 30000);
            dump_pcm(kDumpRenderer, mix, 240);
        }
        dump_pcm(kDumpAudioOut, mix, 240);  // the renderer owns the file
        std::cout << "PASS " << mode << ": 2100 render frames offered\n";
    } else if (mode == "fail" || mode == "unset") {
        int16_t mix[240 * 2];
        fill(mix, 240, 1);
        for (int k = 0; k < 10; k++) dump_pcm(kDumpRenderer, mix, 240);
        std::cout << "PASS " << mode << ": no dump, no failure\n";
    } else {
        return 2;
    }
    return 0;  // a normal exit: the atexit close makes the header exact
}
