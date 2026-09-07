/* ACHERON: reconstructed machine-state pseudocode; NOT original source.
 * Registers alias state; bitvector helpers preserve widths and flags.
 * Prototype, memory types and semantic names remain unknown. */
void choose(machine_state &state) {
L_401020:
    push64(state, rbp); /* 0x401020 */
    push64(state, rax); /* 0x401021 */
    rbp = rsp; /* 0x401022 */
    store32(wrap64(rbp), bits32(rcx, 0)); /* 0x401025 */
    rflags = flags_sub32(rflags, load32(wrap64(rbp)), 0x4); /* 0x401028 */
    if (condition_le(rflags)) { goto L_401040; } /* 0x40102c */
    goto L_401032; /* 0x40102c */
L_401032:
    rax = zext64(load32(wrap64(rbp))); /* 0x401032 */
    u32 t_401035 = sub32(bits32(rax, 0), 0x3); /* 0x401035 */
    rflags = flags_sub32(rflags, bits32(rax, 0), 0x3); /* 0x401035 */
    rax = zext64(t_401035); /* 0x401035 */
    store32(wrap64(rbp + 0x4), bits32(rax, 0)); /* 0x401038 */
    goto L_401049; /* 0x40103b */
L_401040:
    rax = zext64(load32(wrap64(rbp))); /* 0x401040 */
    u32 t_401043 = add32(bits32(rax, 0), 0x7); /* 0x401043 */
    rflags = flags_add32(rflags, bits32(rax, 0), 0x7); /* 0x401043 */
    rax = zext64(t_401043); /* 0x401043 */
    store32(wrap64(rbp + 0x4), bits32(rax, 0)); /* 0x401046 */
    goto L_401049; /* 0x401046 */
L_401049:
    rax = zext64(load32(wrap64(rbp + 0x4))); /* 0x401049 */
    u64 t_40104c = add64(rsp, 0x8); /* 0x40104c */
    rflags = flags_add64(rflags, rsp, 0x8); /* 0x40104c */
    rsp = t_40104c; /* 0x40104c */
    u64 t_401050 = pop64(state); /* 0x401050 */
    rbp = t_401050; /* 0x401050 */
    return_to_caller(state, 0); /* 0x401051 */
    return; /* 0x401051 */
}
