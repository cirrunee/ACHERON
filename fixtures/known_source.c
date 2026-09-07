/* SPDX-License-Identifier: MIT
 * Tiny freestanding Windows x86/x64 test corpus. No imports; never run by tests.
 */
__declspec(dllexport) __declspec(noinline)
int add_pair(int a, int b) { return a + b; }

__declspec(dllexport) __declspec(noinline)
int choose(int x) { if (x > 4) return x - 3; return x + 7; }

__declspec(dllexport) __declspec(noinline)
unsigned sum_to(unsigned n) {
    unsigned sum = 0;
    for (unsigned i = 0; i < n; ++i) sum += i;
    return sum;
}

__declspec(dllexport) __declspec(noinline)
int invoke(int x) { return add_pair(choose(x), 3); }

int entry(void) { return invoke(5) + (int)sum_to(6); }
