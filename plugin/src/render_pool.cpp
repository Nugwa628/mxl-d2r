// Fallback for D2R's Renderer Pool (docs/bugs.md #60).
//
// A player crashed fighting Griswold: access violation writing address 0 at D2R.exe+0xF3D028. That instruction is in 0xf3cfd0, the
// element move of a vector of 0x80-byte records (D2Render model_instance.cpp, building a model instance; callers 0xf3d587 ->
// 0xf3fef1 -> 0xf3f840). The new buffer came from 0xf6f060, the Renderer Pool's allocate wrapper: it calls the pool object's
// vtable +8 and, when that returns null, only reports "Failed to allocate from Renderer pool!" (0xf6ef40, no break without a
// debugger) and returns null; the caller writes the first element through it (R15 = 0, return address 0xf6f0a2 still on the stack).
// The pool is one fixed 12 MB TLSF arena (0xf6efe0: 0xc00000 from the parent allocator, TLSF handle at 0x2811010), made once at
// renderer start; Median's scenes (Griswold's attack chain spawns eight blade traps per swing, each with a missile and an
// explosion; packs of Median monsters with overlays) can fill it where vanilla does not.
//
// The pool object 0x2810ff0 is { vptr, parent, base, size, tlsf, lock }; its vtable 0x1d6d770 (shared with six other allocators,
// so it is not patched) has six entries: +0 destructor, +8 allocate(size, align), +0x10 reallocate(p, size, align) (new block,
// copy, free), +0x18 TLSF realloc(p, size), +0x20 free(p), +0x28 usable size(p). The plugin points this one object at a copy
// whose allocate / reallocate entries fall back to the process heap when D2R's answer is null, and whose free / size / realloc
// entries send a pointer outside [base, base + size) that carries the fallback header to the heap. Pool blocks never leave D2R's
// functions, so the swap is safe at any moment.
#include "render_pool.h"

#include "render_pool_logic.h"

#include <windows.h>

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>

namespace {

constexpr uint64_t PoolObjectRva = 0x2810ff0;
constexpr uint64_t VtableRva = 0x1d6d770;
constexpr uint64_t VtableEntries[6] = {0x82dcf0, 0x82dad0, 0x82db40, 0x82dbf0, 0x82dc60, 0x82dcb0};
constexpr size_t BaseField = 0x10, SizeField = 0x18;

using AllocFn = void* (*)(void* self, size_t size, size_t align);
using ReallocFn = void* (*)(void* self, void* p, size_t size, size_t align);
using TlsfReallocFn = void* (*)(void* self, void* p, size_t size);
using FreeFn = void (*)(void* self, void* p);
using SizeFn = size_t (*)(void* self, void* p);

const D2RL::PluginContext* g_context = nullptr;
uint8_t* g_object = nullptr;
AllocFn g_alloc = nullptr;
ReallocFn g_realloc = nullptr;
TlsfReallocFn g_tlsfRealloc = nullptr;
FreeFn g_free = nullptr;
SizeFn g_size = nullptr;
alignas(16) void* g_vtable[6] = {};

std::atomic<unsigned> g_fallbacks{0}, g_live{0};
std::atomic<size_t> g_liveBytes{0}, g_peakBytes{0};
std::atomic<uintptr_t> g_base{0};
std::atomic<size_t> g_poolSize{0};

// The pool's range (kept from the last time it was set: D2R zeroes it when the renderer shuts down).
void PoolRange(uintptr_t* base, size_t* size) noexcept {
	const uintptr_t b = *reinterpret_cast<uintptr_t*>(g_object + BaseField);
	const size_t s = *reinterpret_cast<size_t*>(g_object + SizeField);
	if (b != 0 && s != 0) {
		g_base.store(b);
		g_poolSize.store(s);
	}
	*base = g_base.load();
	*size = g_poolSize.load();
}

auto IsFallback(const void* p) noexcept -> bool {
	if (p == nullptr || g_live.load() == 0) {
		return false;
	}
	uintptr_t base = 0;
	size_t size = 0;
	PoolRange(&base, &size);
	if (render_pool::InRange(reinterpret_cast<uintptr_t>(p), base, size)) {
		return false;
	}
	return render_pool::HeaderOf(p)->magic == render_pool::Magic;
}

void Note(const char* what, size_t size) noexcept {
	const unsigned n = g_fallbacks.load();
	if (g_context == nullptr || !(n == 1 || n == 100 || n == 10000 || n == 1000000)) {
		return;
	}
	char line[260];
	std::snprintf(line, sizeof(line),
	              "mxl-core: render pool: the Renderer Pool is full; %s of %zu bytes taken from the heap (%u so far, %zu bytes live) instead of "
	              "D2R's null write at D2R.exe+0xF3D028 (docs/bugs.md #60)",
	              what, size, n, g_liveBytes.load());
	g_context->LogWarn(line);
}

auto HeapBlock(size_t size, size_t align) noexcept -> void* {
	void* raw = HeapAlloc(GetProcessHeap(), 0, render_pool::RawSize(size, align));
	if (raw == nullptr) {
		return nullptr;
	}
	g_fallbacks.fetch_add(1);
	g_live.fetch_add(1);
	const size_t now = g_liveBytes.fetch_add(size) + size;
	size_t peak = g_peakBytes.load();
	while (now > peak && !g_peakBytes.compare_exchange_weak(peak, now)) {
	}
	return render_pool::Place(raw, size, align);
}

void HeapRelease(void* p) noexcept {
	render_pool::Header* h = const_cast<render_pool::Header*>(render_pool::HeaderOf(p));
	g_liveBytes.fetch_sub(h->size);
	void* raw = h->raw;
	h->magic = 0;
	HeapFree(GetProcessHeap(), 0, raw);
	g_live.fetch_sub(1);
}

void* Alloc(void* self, size_t size, size_t align) noexcept {
	void* p = g_alloc(self, size, align);
	if (p == nullptr && size != 0) {
		p = HeapBlock(size, align);
		Note("an allocation", size);
	}
	return p;
}

// New block (pool first, heap when it is full), old contents copied, old block freed where it came from. Null (old block kept)
// only when the heap is out too.
auto Move(void* self, void* old, size_t oldSize, size_t size, size_t align) noexcept -> void* {
	void* p = g_alloc(self, size, align);
	if (p == nullptr) {
		p = HeapBlock(size, align);
		Note("a reallocation", size);
	}
	if (p == nullptr) {
		return nullptr;
	}
	std::memcpy(p, old, oldSize < size ? oldSize : size);
	if (IsFallback(old)) {
		HeapRelease(old);
	} else {
		g_free(self, old);
	}
	return p;
}

void* Realloc(void* self, void* p, size_t size, size_t align) noexcept {
	if (IsFallback(p)) {
		return Move(self, p, render_pool::HeaderOf(p)->size, size, align);
	}
	void* q = g_realloc(self, p, size, align);
	if (q == nullptr && size != 0) {
		q = p != nullptr ? Move(self, p, g_size(self, p), size, align) : Alloc(self, size, align);
	}
	return q;
}

void* TlsfRealloc(void* self, void* p, size_t size) noexcept {
	if (IsFallback(p)) {
		if (size == 0) {
			HeapRelease(p);
			return nullptr;
		}
		return Move(self, p, render_pool::HeaderOf(p)->size, size, render_pool::HeaderOf(p)->align);
	}
	void* q = g_tlsfRealloc(self, p, size);
	if (q == nullptr && size != 0) {
		// TLSF leaves the old block alone when it cannot place the new size
		q = p != nullptr ? Move(self, p, g_size(self, p), size, 16) : Alloc(self, size, 16);
	}
	return q;
}

void Free(void* self, void* p) noexcept {
	if (IsFallback(p)) {
		HeapRelease(p);
		return;
	}
	g_free(self, p);
}

size_t Size(void* self, void* p) noexcept {
	if (IsFallback(p)) {
		return render_pool::HeaderOf(p)->size;
	}
	return g_size(self, p);
}

}  // namespace

void GetRenderPoolStats(RenderPoolStats* out) noexcept {
	out->fallbacks = g_fallbacks.load();
	out->live = g_live.load();
	out->liveBytes = g_liveBytes.load();
	out->peakBytes = g_peakBytes.load();
	uintptr_t base = 0;
	size_t size = 0;
	if (g_object != nullptr) {
		PoolRange(&base, &size);
	}
	out->poolBase = base;
	out->poolSize = size;
}

auto RenderPoolProbe() noexcept -> bool {
	if (g_object == nullptr) {
		return false;
	}
	const unsigned live0 = g_live.load();
	void* p = HeapBlock(100, 16);
	if (p == nullptr) {
		return false;
	}
	std::memset(p, 0x5a, 100);
	bool ok = IsFallback(p) && (reinterpret_cast<uintptr_t>(p) & 15) == 0 && Size(g_object, p) == 100;
	// moves into the pool when it has room, else to a new heap block; the bytes come along and the old heap block is gone
	void* q = Realloc(g_object, p, 200, 16);
	ok = ok && q != nullptr && static_cast<uint8_t*>(q)[99] == 0x5a && Size(g_object, q) >= 200;
	if (q != nullptr) {
		Free(g_object, q);
	}
	return ok && g_live.load() == live0;
}

auto InstallRenderPool(const D2RL::PluginContext* context, char* report, size_t reportSize) noexcept -> bool {
	g_context = context;
	const uint64_t base = context->exeBase;
	void** object = reinterpret_cast<void**>(base + PoolObjectRva);
	void** vtable = reinterpret_cast<void**>(base + VtableRva);
	if (*object != static_cast<void*>(vtable)) {
		std::snprintf(report, reportSize, "off: the Renderer Pool object 0x2810ff0 does not point at vtable 0x1d6d770 (%p)", *object);
		return false;
	}
	for (int i = 0; i < 6; ++i) {
		if (vtable[i] != reinterpret_cast<void*>(base + VtableEntries[i])) {
			std::snprintf(report, reportSize, "off: vtable 0x1d6d770 entry %d differs", i);
			return false;
		}
	}
	g_object = reinterpret_cast<uint8_t*>(object);
	g_alloc = reinterpret_cast<AllocFn>(vtable[1]);
	g_realloc = reinterpret_cast<ReallocFn>(vtable[2]);
	g_tlsfRealloc = reinterpret_cast<TlsfReallocFn>(vtable[3]);
	g_free = reinterpret_cast<FreeFn>(vtable[4]);
	g_size = reinterpret_cast<SizeFn>(vtable[5]);
	g_vtable[0] = vtable[0];
	g_vtable[1] = reinterpret_cast<void*>(&Alloc);
	g_vtable[2] = reinterpret_cast<void*>(&Realloc);
	g_vtable[3] = reinterpret_cast<void*>(&TlsfRealloc);
	g_vtable[4] = reinterpret_cast<void*>(&Free);
	g_vtable[5] = reinterpret_cast<void*>(&Size);
	InterlockedExchangePointer(object, static_cast<void*>(g_vtable));
	uintptr_t b = 0;
	size_t s = 0;
	PoolRange(&b, &s);
	if (s != 0) {
		std::snprintf(report, reportSize, "on: Renderer Pool 0x2810ff0 (%zu MB) falls back to the heap when full (D2R.exe+0xF3D028, docs/bugs.md #60)", s >> 20);
	} else {
		std::snprintf(report, reportSize, "on: Renderer Pool 0x2810ff0 (not made yet) falls back to the heap when full (D2R.exe+0xF3D028, docs/bugs.md #60)");
	}
	return true;
}
