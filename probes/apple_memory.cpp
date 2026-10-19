// Original Apple portability probe. Constants describe the Apple branch of
// BelmanteGu/SuperMarioWonderRecomp@010ed7a596a621c15d3a8dfa5795ca8c3668b066.
// No upstream code, generated game code, or game data is linked.
#include <TargetConditionals.h>
#include <mach/mach.h>
#include <pthread.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/utsname.h>
#include <unistd.h>

#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <cstring>
#include <cstdlib>

#ifdef APPLE_MEMORY_PATCH_HEADER
#include APPLE_MEMORY_PATCH_HEADER
#endif
#include <initializer_list>

namespace {
constexpr uint64_t guest_page = 0x1000;
struct Range { const char* name; uint64_t base, size; bool required; bool owned = false; };
// runtime/include/nx/{cpu,runtime}.h and runtime/src/memory.cpp; __APPLE__ layout.
#ifdef APPLE_MEMORY_HIGH_PROFILE
constexpr Range layout[] = {
    {"modules", 0x7000000000, 0x20000000, true},
    {"heap",    0x7100000000, 0x180000000, true},
    {"alias",   0x7300000000, 0x400000000, true},
    {"stack",   0x7800000000, 0x100000000, true},
    {"kernel",  0x7900000000, 0x100000000, true},
    {"thunk",   0x7B00000000, 0x100000, false},
};
constexpr const char* profile = "apple-high-v1";
#else
constexpr const char* profile = "upstream-baseline";
constexpr Range layout[] = {
    {"modules", 0x300000000, 0x20000000, true},
    {"heap",    0x400000000, 0x180000000, true},
    {"alias",   0x600000000, 0x400000000, true},
    {"stack",   0xA00000000, 0x100000000, true},
    {"kernel",  0xB00000000, 0x100000000, true},
    {"thunk",   0xE00000000, 0x100000, false},
};
#endif
constexpr uint64_t address_space_base = 0x8000000;
constexpr uint64_t address_space_size = 0x7FF8000000;

// A hint plus exact equality never destroys an existing mapping. No MAP_FIXED.
void describe_overlaps(FILE* out, const Range& r) {
    vm_address_t cursor = r.base;
    unsigned count_regions = 0;
    while (cursor < r.base + r.size) {
        vm_address_t start = cursor;
        vm_size_t size = 0;
        vm_region_basic_info_data_64_t info{};
        mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
        mach_port_t object = MACH_PORT_NULL;
        kern_return_t kr = vm_region_64(mach_task_self(), &start, &size,
            VM_REGION_BASIC_INFO_64, reinterpret_cast<vm_region_info_t>(&info), &count, &object);
        if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
        if (kr != KERN_SUCCESS) {
            std::fprintf(out, "overlap_scan name=%s kr=%d\n", r.name, kr);
            return;
        }
        if (start >= r.base + r.size) break;
        vm_region_extended_info_data_t extended{};
        mach_msg_type_number_t extended_count = VM_REGION_EXTENDED_INFO_COUNT;
        vm_address_t extended_start = start;
        vm_size_t extended_size = 0;
        mach_port_t extended_object = MACH_PORT_NULL;
        kern_return_t extended_kr = vm_region_64(mach_task_self(), &extended_start, &extended_size,
            VM_REGION_EXTENDED_INFO, reinterpret_cast<vm_region_info_t>(&extended),
            &extended_count, &extended_object);
        if (extended_object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), extended_object);
        std::fprintf(out, "overlap_tag name=%s start=0x%" PRIx64 " kr=%d user_tag=%u\n",
                     r.name, uint64_t(start), extended_kr, extended.user_tag);
        ++count_regions;
        std::fprintf(out, "overlap name=%s start=0x%" PRIx64 " size=0x%" PRIx64 " protection=%d max_protection=%d\n",
                     r.name, uint64_t(start), uint64_t(size), info.protection, info.max_protection);
        if (size == 0 || start + size <= cursor) break;
        cursor = start + size;
    }
    std::fprintf(out, "overlap_count name=%s count=%u\n", r.name, count_regions);
}

bool reserve_exact(FILE* out, const Range& r, bool collision_test = false) {
    if (!collision_test) describe_overlaps(out, r);
    errno = 0;
    void* p = mmap(reinterpret_cast<void*>(r.base), r.size, PROT_NONE,
                   MAP_PRIVATE | MAP_ANON | MAP_NORESERVE, -1, 0);
    int error = errno;
    bool exact = p != MAP_FAILED && reinterpret_cast<uint64_t>(p) == r.base;
    std::fprintf(out, "reserve name=%s base=0x%" PRIx64 " size=0x%" PRIx64
                 " required=%d exact=%d returned=%p errno=%d error=%s collision_test=%d\n",
                 r.name, r.base, r.size, r.required, exact, p, error,
                 error ? std::strerror(error) : "none", collision_test);
    if (p != MAP_FAILED && !exact) {
        if (munmap(p, r.size) != 0) {
            std::fprintf(out, "FAIL alternate_mapping_cleanup errno=%d\n", errno);
            return false;
        }
        std::fprintf(out, "alternate_mapping_rejected name=%s\n", r.name);
    }
    return exact;
}

int protection(uint64_t addr) {
    vm_address_t start = addr;
    vm_size_t size = 0;
    vm_region_basic_info_data_64_t info{};
    mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t object = MACH_PORT_NULL;
    kern_return_t kr = vm_region_64(mach_task_self(), &start, &size,
        VM_REGION_BASIC_INFO_64, reinterpret_cast<vm_region_info_t>(&info), &count, &object);
    if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
    return kr == KERN_SUCCESS && start <= addr && addr - start < size ? info.protection : -1;
}

bool commit(uint64_t addr, uint64_t size, uint64_t page) {
    const uint64_t begin = addr & ~(page - 1);
    const uint64_t end = (addr + size + page - 1) & ~(page - 1);
    return mprotect(reinterpret_cast<void*>(begin), end - begin, PROT_READ | PROT_WRITE) == 0;
}

// Exercise the pinned platform's page policy using independently written code.
bool page_checks(FILE* out, uint64_t base, uint64_t page) {
    bool ok = commit(base, page * 2, page);
    if (!ok) { std::fprintf(out, "FAIL page_commit errno=%d\n", errno); return false; }
    auto* bytes = reinterpret_cast<unsigned char*>(base);
    std::memset(bytes, 0x5a, page * 2);
    // kernel_alloc aligns sizes/addresses to 4 KiB. The second allocation may
    // share a host page with the first: partial decommit must preserve it.
    const uint64_t begin = base + guest_page;
    const uint64_t end = begin + guest_page;
    const uint64_t whole_begin = (begin + page - 1) & ~(page - 1);
    const uint64_t whole_end = end & ~(page - 1);
    if (whole_begin >= whole_end) {
        std::memset(reinterpret_cast<void*>(begin), 0, guest_page);
        bool zero = true, neighbors = true;
        for (uint64_t i = 0; i < guest_page; ++i) zero &= bytes[guest_page + i] == 0;
        for (uint64_t i = 0; i < guest_page; ++i) neighbors &= bytes[i] == 0x5a;
        for (uint64_t i = 2 * guest_page; i < page * 2; ++i) neighbors &= bytes[i] == 0x5a;
        std::fprintf(out, "partial_decommit guest_bytes=4096 zero=%d neighbors_preserved=%d\n", zero, neighbors);
        ok &= zero && neighbors;
    } else {
        std::fprintf(out, "partial_decommit not_shared host_page_equals_guest=%d\n", page == guest_page);
    }
    int advice = madvise(reinterpret_cast<void*>(base), page * 2, MADV_FREE);
    int advice_error = advice ? errno : 0;
    int protect = mprotect(reinterpret_cast<void*>(base), page * 2, PROT_NONE);
    int protect_error = protect ? errno : 0;
    int after_free = protection(base);
    bool recommit = commit(base, page * 2, page);
    int after_commit = protection(base);
    // MADV_FREE is lazy: report observed bytes; do not promise zero-on-reuse.
    int reused_byte = recommit ? bytes[0] : -1;
    std::fprintf(out, "full_decommit madvise_rc=%d madvise_errno=%d mprotect_rc=%d mprotect_errno=%d"
                 " protection=%d recommit=%d recommit_protection=%d reused_first_byte=%d\n",
                 advice, advice_error, protect, protect_error, after_free, recommit, after_commit, reused_byte);
    return ok && advice == 0 && protect == 0 && after_free == PROT_NONE && recommit &&
        after_commit == (PROT_READ | PROT_WRITE);
}

#ifdef APPLE_MEMORY_PATCH_HEADER
// Invoke the actual patched upstream functions, not another implementation.
bool fixed_page_checks(FILE* out, uint64_t base, uint64_t page) {
    if (!nx::plat::commit(base, page * 5)) return false;
    auto* bytes = reinterpret_cast<unsigned char*>(base);
    std::memset(bytes, 0x5a, page * 5);
    bool ok = true;
    if (page > guest_page) {
        nx::plat::decommit(base + guest_page, guest_page);
        bool neighbors = true, zero = true;
        for (uint64_t i = 0; i < page * 5; ++i) {
            if (i >= guest_page && i < guest_page * 2) zero &= bytes[i] == 0;
            else neighbors &= bytes[i] == 0x5a;
        }
        std::fprintf(out, "fixed_partial zero=%d neighbors_preserved=%d protection=%d\n",
                     zero, neighbors, protection(base));
        ok &= zero && neighbors && protection(base) == (PROT_READ | PROT_WRITE);
    }
    // Cross two shared edges and two complete host pages in the middle.
    const uint64_t start = base + page + guest_page;
    const uint64_t size = page * 3;
    nx::plat::decommit(start, size);
    bool guards = protection(base + page * 2) == PROT_NONE &&
                  protection(base + page * 3) == PROT_NONE;
    unsigned char readback = 0;
    vm_size_t copied = 0;
    kern_return_t read = vm_read_overwrite(mach_task_self(), base + page * 2,
        1, reinterpret_cast<vm_address_t>(&readback), &copied);
    bool denied = read != KERN_SUCCESS;
    bool recommit = nx::plat::commit(start, size);
    bool zero = recommit, neighbors = recommit;
    if (recommit) for (uint64_t i = page; i < page * 5; ++i) {
        if (i >= page + guest_page && i < page * 4 + guest_page) zero &= bytes[i] == 0;
        else neighbors &= bytes[i] == 0x5a;
    }
    std::fprintf(out, "fixed_mixed whole_pages_zero=%d neighbors_preserved=%d guard_none=%d guard_read_denied=%d recommit=%d\n",
                 zero, neighbors, guards, denied, recommit);
    ok &= zero && neighbors && guards && denied && recommit;
    std::memset(bytes, 0x5a, page * 5);
    nx::plat::decommit(base, page * 5);
    guards = protection(base) == PROT_NONE && protection(base + page * 4) == PROT_NONE;
    recommit = nx::plat::commit(base, page * 5);
    zero = recommit;
    if (recommit) for (uint64_t i = 0; i < page * 5; ++i) zero &= bytes[i] == 0;
    std::fprintf(out, "fixed_whole all_bytes_zero=%d guard_none=%d recommit=%d\n", zero, guards, recommit);
    return ok && zero && guards && recommit;
}
#endif

void* stack_worker(void* arg) {
    *static_cast<size_t*>(arg) = pthread_get_stacksize_np(pthread_self());
    volatile unsigned char touch[4096]{};
    touch[0] = 1;
    return nullptr;
}

void limits(FILE* out) {
    for (int kind : {RLIMIT_AS, RLIMIT_DATA, RLIMIT_STACK}) {
        rlimit value{};
        int rc = getrlimit(kind, &value);
        std::fprintf(out, "rlimit kind=%d rc=%d soft=%" PRIu64 " hard=%" PRIu64 " infinity=%" PRIu64 "\n",
            kind, rc, uint64_t(value.rlim_cur), uint64_t(value.rlim_max), uint64_t(RLIM_INFINITY));
    }
    task_vm_info_data_t vm{};
    mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
    kern_return_t kr = task_info(mach_task_self(), TASK_VM_INFO, reinterpret_cast<task_info_t>(&vm), &count);
    std::fprintf(out, "task_vm_info kr=%d virtual_bytes=%" PRIu64 " resident_bytes=%" PRIu64
                 " phys_footprint=%" PRIu64 "\n", kr, uint64_t(vm.virtual_size),
                 uint64_t(vm.resident_size), uint64_t(vm.phys_footprint));
}
} // namespace

int run_apple_memory(FILE* out) {
    std::setvbuf(out, nullptr, _IOLBF, 0);
    utsname system{};
    uname(&system);
    const uint64_t page = static_cast<uint64_t>(getpagesize());
    std::fprintf(out, "apple_memory schema=1 source=010ed7a596a621c15d3a8dfa5795ca8c3668b066"
                 " simulator=%d ios=%d arch=%s host_release=%s host_page=%" PRIu64
                 " sysconf_page=%ld guest_page=%" PRIu64 " pointer_bits=%zu\n",
                 TARGET_OS_SIMULATOR, TARGET_OS_IOS, system.machine, system.release, page,
                 sysconf(_SC_PAGESIZE), guest_page, sizeof(void*) * 8);
    std::fprintf(out, "guest_address_space base=0x%" PRIx64 " size=0x%" PRIx64
                 " end=0x%" PRIx64 " reserved_total=32750174208 thunk_optional=1\n",
                 address_space_base, address_space_size, address_space_base + address_space_size);
    bool ok = page >= guest_page && (page & (page - 1)) == 0 && page == uint64_t(sysconf(_SC_PAGESIZE));
    if (!ok) { std::fprintf(out, "FAIL unsupported_host_page\nRESULT status=FAIL exit_code=1\n"); return 1; }
    std::fprintf(out, "memory_profile=%s\n", profile);
    limits(out);
    Range ranges[sizeof(layout) / sizeof(layout[0])];
    std::memcpy(ranges, layout, sizeof(layout));
    for (auto& r : ranges) {
        r.owned = reserve_exact(out, r);
        if (!r.owned) {
            std::fprintf(out, "%s reservation name=%s\n", r.required ? "FAIL" : "OPTIONAL_UNAVAILABLE", r.name);
            if (r.required) ok = false;
            continue;
        }
    }
    // Match memory_init's reservation order before committing any guest memory.
    for (const auto& r : ranges) {
        if (!r.owned || !r.required) continue; // thunk stays address-only.
        bool first = commit(r.base, guest_page, page);
        bool last = commit(r.base + r.size - guest_page, guest_page, page);
        if (first) *reinterpret_cast<volatile unsigned char*>(r.base) = 0x37;
        if (last) *reinterpret_cast<volatile unsigned char*>(r.base + r.size - 1) = 0x73;
        bool values = first && last && *reinterpret_cast<volatile unsigned char*>(r.base) == 0x37 &&
            *reinterpret_cast<volatile unsigned char*>(r.base + r.size - 1) == 0x73;
        std::fprintf(out, "boundary_commit name=%s first=%d last=%d readback=%d\n", r.name, first, last, values);
        ok &= values;
    }
    if (ranges[0].owned && protection(ranges[0].base) == (PROT_READ | PROT_WRITE)) {
        bool incorrectly_replaced = reserve_exact(out, ranges[0], true);
        bool intact = *reinterpret_cast<volatile unsigned char*>(ranges[0].base) == 0x37;
        std::fprintf(out, "occupied_range_rejected=%d original_byte_intact=%d\n", !incorrectly_replaced, intact);
        ok &= !incorrectly_replaced && intact;
    }
    if (ranges[0].owned) {
        std::fprintf(out, "page_policy_test region=modules offset=0x%" PRIx64 "\n", page * 4);
        ok &= page_checks(out, ranges[0].base + page * 4, page);
#ifdef APPLE_MEMORY_PATCH_HEADER
        ok &= fixed_page_checks(out, ranges[0].base + page * 8, page);
#endif
    }
    pthread_attr_t attr;
    int init = pthread_attr_init(&attr);
    int set = init == 0 ? pthread_attr_setstacksize(&attr, 64ull << 20) : init;
    size_t actual = 0;
    pthread_t worker{};
    int create = set == 0 ? pthread_create(&worker, &attr, stack_worker, &actual) : set;
    int join = create == 0 ? pthread_join(worker, nullptr) : create;
    if (init == 0) pthread_attr_destroy(&attr);
    bool stack_ok = init == 0 && set == 0 && create == 0 && join == 0 && actual >= (64ull << 20);
    std::fprintf(out, "thread_stack requested=67108864 actual=%zu init=%d set=%d create=%d join=%d pass=%d\n",
                 actual, init, set, create, join, stack_ok);
    ok &= stack_ok;
    limits(out); // while all successful reservations are simultaneously live
    for (const auto& r : ranges) if (r.owned && munmap(reinterpret_cast<void*>(r.base), r.size) != 0) {
        std::fprintf(out, "FAIL cleanup name=%s errno=%d\n", r.name, errno); ok = false;
    }
    std::fprintf(out, "RESULT status=%s exit_code=%d\n", ok ? "PASS" : "FAIL", ok ? 0 : 1);
    return ok ? 0 : 1;
}

#ifndef APPLE_MEMORY_NO_MAIN
int main() { return run_apple_memory(stdout); }
#endif
