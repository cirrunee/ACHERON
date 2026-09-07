# AIR contract v1

AIR is architecture-independent in operation vocabulary, while AIR-L intentionally
retains architecture-specific register names and explicit machine widths.

Every operation carries an ID derived from its source VA, source instruction bytes
through its parent instruction, source address, evidence state, opcode, operands,
register reads/writes, memory effects and a supported flag. IDs remain stable within
a binary hash / stage revision. Transformations carry sets of original IDs.

## AIR-L (implemented subset)

Operands are tagged records: `register(name,width,parent,offset)`,
`constant(value,width)`, `memory(base,index,scale,displacement,width,segment)`,
`address(value,width)` and `unknown(text)`. Memory addresses are modulo address
width. RIP-relative operands become absolute addresses. Memory reads and writes
are explicit in load/store operations or memory effect records; arithmetic with
a memory destination is an opaque effect in v0.1.

Operations: copy, load, store, address, add, sub, and, or, xor, compare, test,
branch, jump, call, return, push, pop, nop and opaque. Arithmetic uses fixed-width bitvector
semantics, not C signed overflow. The pseudocode uses width-aware helper notation.
Flag computations and branch predicates are explicit helper expressions. Partial
register writes preserve untouched parent bits; 32-bit GPR writes zero-extend in
64-bit mode. In 32-bit mode they replace the full EAX/etc. parent, while partial
AX/AL/AH writes preserve the other bits. Flags use EFLAGS and call/return effects
use the 32-bit register set. Unsupported instructions preserve decoder effects and remain opaque.
No optimization crosses an opaque instruction or unknown call based on guessed
values. Return type/prototype and ABI names are not inferred in this milestone.

## AIR-M (specified, unsupported in v0.1)

Explicit virtual values with bitvector/float/pointer types, normalized register
slices and memory effects. Nodes include const, extract, insert, zext, sext,
trunc, arithmetic, compare, select, load, store, call, branch, return and phi.
SSA versions all scalar definitions; phi arguments are keyed by predecessor ID.
Memory tokens are versioned separately by conservative alias partition. Effects
order calls, stores, volatile accesses, traps and unknown instructions.
Stack locations and function argument/return values are constraints until proven.

Example: `v3:u64 = zext(v2:u32)` and `v7 = phi(bb1:v3, bb2:v6)` retain origin
sets and rule evidence. Constants are propagated using a bottom/constant/top
lattice. DCE removes only provably effect-free dead values. ABI clobbers are
explicit; unknown callers/callees remain conservative. Invalid or incomplete CFGs
prevent transformations that require complete predecessor sets.

## AIR-H (specified, unsupported in v0.1)

Typed expression and statement AST: identifiers, literals, field/index accesses,
casts, calls, declarations, assignments, if, switch, loops, break, continue,
return, labels and goto. Type and naming annotations reference independent fact
or hypothesis IDs. AST regions map to AIR-M values and original instruction spans.
Structuring requires dominance/postdominance and edge preservation; irreducible or
uncertain regions retain labels. Semantic names never replace deterministic IDs.

All three levels will be independently inspectable. Missing levels must be
reported as unsupported, never populated with fabricated transformed records.
