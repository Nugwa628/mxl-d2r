// Pure parts of the Renderer Pool fallback (render_pool.cpp; docs/bugs.md #60): the header in front of a fallback block and the
// pool range test. No Windows headers, so plugin/tests builds it anywhere.
#pragma once

#include <cstddef>
#include <cstdint>

namespace render_pool {

constexpr uint64_t Magic = 0x31424650524C584DULL;  // "MXLRPFB1"

// Written just before every pointer the fallback hands out (32 bytes, so a 16-aligned block stays 16-aligned).
struct Header {
	uint64_t magic;
	void* raw;    // what the heap returned
	size_t size;  // what the caller asked for
	size_t align;
};
static_assert(sizeof(Header) == 32, "header keeps 16-byte alignment");

// D2R asks for 8 or 16; anything that is not a power of two counts as 16.
constexpr auto Alignment(size_t align) noexcept -> size_t {
	if (align < 16 || (align & (align - 1)) != 0) {
		return 16;
	}
	return align;
}

// Bytes to take from the heap for a block of `size` aligned to `align`.
constexpr auto RawSize(size_t size, size_t align) noexcept -> size_t {
	return size + sizeof(Header) + Alignment(align);
}

// The user pointer inside `raw` (RawSize bytes), with its header written in front of it.
inline auto Place(void* raw, size_t size, size_t align) noexcept -> void* {
	const size_t a = Alignment(align);
	const uintptr_t first = reinterpret_cast<uintptr_t>(raw) + sizeof(Header);
	const uintptr_t user = (first + a - 1) & ~(uintptr_t)(a - 1);
	Header* h = reinterpret_cast<Header*>(user) - 1;
	h->magic = Magic;
	h->raw = raw;
	h->size = size;
	h->align = a;
	return reinterpret_cast<void*>(user);
}

inline auto HeaderOf(const void* p) noexcept -> const Header* {
	return reinterpret_cast<const Header*>(p) - 1;
}

constexpr auto InRange(uintptr_t p, uintptr_t base, size_t size) noexcept -> bool {
	return base != 0 && p >= base && p - base < size;
}

}  // namespace render_pool
