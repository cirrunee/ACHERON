# Pseudocode semantics and limitations

The renderer consumes AIR-L; it does not parse assembly text to fabricate source.
Output is C-style **machine-state notation**, not compilable C, a recovered ABI,
or a claim about original variable names. Register names alias the fields of the
`machine_state &state` argument. Labels and all line mappings refer to source VAs.

## Bitvectors and state

`uN` is an unsigned N-bit bitvector. `addN`, `subN`, `andN`, `orN` and `xorN`
truncate operands/results to N bits. `bitsN(parent, offset)` extracts a slice.
`insert_bits(parent, offset, width, value)` replaces only that slice.
`zext64(value:u32)` models the x64 zero-extension of a 32-bit GPR destination.
In x86 mode, EAX/ECX/etc. are full 32-bit parents and assignments do not introduce
64-bit zero-extension. The function's persisted `bitness` selects EFLAGS versus
RFLAGS and the machine-state stack width. Legacy x64 projects default to 64 bits.
`truncN` and `wrapN` truncate to the stated width. These helpers avoid undefined
signed overflow and implementation-dependent C casts.

`loadN(address)` and `storeN(address,value)` refer to little-endian target memory,
never host memory. Effective-address arithmetic wraps to its address size. FS/GS
bases are retained; LEA computes an offset without a segment base. Arithmetic
with a memory source captures that source once before computing result and flags.
This preserves the number of memory reads. Faulting memory, volatile behavior and
precise exception edges require a richer effect model before optimization.

`flags_addN(old,a,b)` updates CF/PF/AF/ZF/SF/OF using x86 addition rules while
preserving other flags. `flags_subN` uses subtraction/borrow rules. Logical flags
helpers clear CF/OF, update PF/ZF/SF, mark AF undefined and preserve other flags.
Undefined values remain unknown; they must not be silently set to zero.
Flag helpers run before destination writeback, using original operands.
Conditions `e/ne` test ZF, `a/be` test CF/ZF, `b/ae` test CF, `g/le` test ZF and
SF==OF, `ge/l` test SF==OF, and `o/no`, `s/ns`, `p/np` test their respective flags.

`pushN(state,value)` captures value, decrements RSP (x64) or ESP (x86) by N/8,
then stores N bits. `popN` reads at that stack pointer and advances it before the
destination is assigned. x86 operand/address-size overrides retain 16-bit widths.
Ordinary Windows flat CS/DS/ES/SS segments are assumed; FS/GS offsets remain
explicit. Non-flat segmentation, far transfers and complete exception semantics
are not reconstructed. Far calls/jumps remain opaque operations.
`return_to_caller(state,adjustment)` pops the near return address and adds the
RET immediate stack adjustment. `call_machine(target,state)` represents call and
return effects with unknown prototype/memory changes. Data flow conservatively
kills all tracked caller register definitions; it does not infer ABI preservation.

## Unsupported semantics and control flow

`opaque_instruction(bytes,state)` denotes an unimplemented machine operation,
including its unknown effects. It is **not** a no-op and is not executable helper
code. The disassembly, effects and original bytes remain inspectable. There is
no claim of complete semantic reconstruction for functions containing it.

For unimplemented branch semantics, the opaque operation supplies an abstract
`opaque_branch_decision()`; no ordinary flag predicate is asserted. An unresolved
indirect/external edge uses `unresolved_transfer` or `transfer_to` and terminates
the current reconstruction. These helpers are markers of incomplete recovery.

The renderer does not fold conditions, remove effects, infer source types, invent
function parameters or force reducible-looking structures onto uncertain CFGs.
They are future AIR-M/SSA and AIR-H features. Full instruction semantics and
formal equivalence are outside v0.1's supported subset.
