// Standalone test of the Renderer Pool fallback's block header and pool range (render_pool_logic.h; not part of the plugin DLL).
#include "../src/render_pool_logic.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace {
int failures = 0;
void Check(bool ok, const char* what) {
	if (!ok) {
		++failures;
		std::printf("FAIL: %s\n", what);
	}
}
}  // namespace

int main() {
	using namespace render_pool;
	static_assert(Alignment(8) == 16 && Alignment(16) == 16 && Alignment(64) == 64 && Alignment(24) == 16 && Alignment(0) == 16);
	static_assert(RawSize(100, 8) == 100 + 32 + 16);

	const size_t aligns[] = {8, 16, 32, 64, 4096};
	for (size_t align : aligns) {
		for (size_t shift = 0; shift < 16; ++shift) {
			const size_t size = 0x48 + shift * 7;
			uint8_t* backing = static_cast<uint8_t*>(std::malloc(RawSize(size, align) + 16));
			void* raw = backing + shift;  // the heap's own alignment is not relied on
			void* p = Place(raw, size, align);
			const uintptr_t u = reinterpret_cast<uintptr_t>(p);
			Check(u % Alignment(align) == 0, "user pointer has the asked alignment");
			Check(u >= reinterpret_cast<uintptr_t>(raw) + sizeof(Header), "header fits before the user pointer");
			Check(u + size <= reinterpret_cast<uintptr_t>(raw) + RawSize(size, align), "block fits in the raw size");
			const Header* h = HeaderOf(p);
			Check(h->magic == Magic && h->raw == raw && h->size == size && h->align == Alignment(align), "header read back");
			std::memset(p, 0xab, size);
			Check(HeaderOf(p)->magic == Magic, "writing the block leaves the header alone");
			std::free(backing);
		}
	}

	const uintptr_t base = 0x2afac050;
	const size_t size = 0xc00000;
	Check(InRange(base, base, size), "pool start is in the pool");
	Check(InRange(base + size - 1, base, size), "last pool byte is in the pool");
	Check(!InRange(base + size, base, size), "one past the end is not");
	Check(!InRange(base - 16, base, size), "below the pool is not");
	Check(!InRange(base, 0, 0), "no pool yet: nothing is in it");
	Check(!InRange(0x10, 0, size), "base 0 never matches");

	if (failures) {
		std::printf("%d failure(s)\n", failures);
		return 1;
	}
	std::printf("render pool tests ok\n");
	return 0;
}
