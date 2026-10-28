// Fallback for D2R's Renderer Pool (render_pool.cpp; docs/bugs.md #60).
#pragma once

#include <D2RLPlugin/api.h>

#include <cstddef>

// Points the Renderer Pool allocator object (0x2810ff0) at a copy of its vtable whose allocation entries take the block from the
// process heap when the 12 MB pool has no room left (D2R would write through the null pointer: D2R.exe+0xF3D028). Blocks are
// told apart by address: inside the pool they go back to D2R's TLSF functions, outside to the heap. Off word `renderpool`.
auto InstallRenderPool(const D2RL::PluginContext* context, char* report, size_t reportSize) noexcept -> bool;

// Allocations served by the heap, those still live, their bytes, the most bytes at once, the pool's base and size.
struct RenderPoolStats {
	unsigned fallbacks, live;
	size_t liveBytes, peakBytes;
	unsigned long long poolBase;
	size_t poolSize;
};
void GetRenderPoolStats(RenderPoolStats* out) noexcept;

// Harness probe: one heap block through the wrapped vtable (alloc, realloc to a bigger size, size query, free); true when each step
// answered as expected. Does not touch the pool.
auto RenderPoolProbe() noexcept -> bool;
