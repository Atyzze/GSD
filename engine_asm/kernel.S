    .section .rodata
    .align 16
.Lsign:
    .quad 0x8000000000000000, 0
.Labs:
    .quad 0x7fffffffffffffff, 0
.Ltwo26:
    .double 67108864.0
.Linv53:
    .double 1.1102230246251565e-16
.Ltiny:
    .double 1e-300
.Lone:
    .double 1.0
.Lshare:
    .double 1e-12

    .text

    .globl gsd_asm_mt_u32
    .type gsd_asm_mt_u32, @function
gsd_asm_mt_u32:
    movq 2496(%rdi), %rax
    cmpq $624, %rax
    jb .Ltemper
    xorl %ecx, %ecx
.Ltwist_low:
    movl (%rdi,%rcx,4), %eax
    andl $0x80000000, %eax
    movl 4(%rdi,%rcx,4), %edx
    andl $0x7fffffff, %edx
    orl %edx, %eax
    movl %eax, %edx
    shrl $1, %edx
    xorl 1588(%rdi,%rcx,4), %edx
    testl $1, %eax
    jz 1f
    xorl $0x9908b0df, %edx
1:
    movl %edx, (%rdi,%rcx,4)
    incl %ecx
    cmpl $227, %ecx
    jb .Ltwist_low
.Ltwist_high:
    movl (%rdi,%rcx,4), %eax
    andl $0x80000000, %eax
    movl 4(%rdi,%rcx,4), %edx
    andl $0x7fffffff, %edx
    orl %edx, %eax
    movl %eax, %edx
    shrl $1, %edx
    xorl -908(%rdi,%rcx,4), %edx
    testl $1, %eax
    jz 2f
    xorl $0x9908b0df, %edx
2:
    movl %edx, (%rdi,%rcx,4)
    incl %ecx
    cmpl $623, %ecx
    jb .Ltwist_high
    movl 2492(%rdi), %eax
    andl $0x80000000, %eax
    movl (%rdi), %edx
    andl $0x7fffffff, %edx
    orl %edx, %eax
    movl %eax, %edx
    shrl $1, %edx
    xorl 1584(%rdi), %edx
    testl $1, %eax
    jz 3f
    xorl $0x9908b0df, %edx
3:
    movl %edx, 2492(%rdi)
    xorl %eax, %eax
.Ltemper:
    movl (%rdi,%rax,4), %edx
    incq %rax
    movq %rax, 2496(%rdi)
    movl %edx, %ecx
    shrl $11, %ecx
    xorl %ecx, %edx
    movl %edx, %ecx
    shll $7, %ecx
    andl $0x9d2c5680, %ecx
    xorl %ecx, %edx
    movl %edx, %ecx
    shll $15, %ecx
    andl $0xefc60000, %ecx
    xorl %ecx, %edx
    movl %edx, %ecx
    shrl $18, %ecx
    xorl %ecx, %edx
    movl %edx, %eax
    ret
    .size gsd_asm_mt_u32, .-gsd_asm_mt_u32

    .globl gsd_asm_mt_random
    .type gsd_asm_mt_random, @function
gsd_asm_mt_random:
    pushq %rbx
    subq $16, %rsp
    movq %rdi, %rbx
    call gsd_asm_mt_u32
    shrl $5, %eax
    cvtsi2sdq %rax, %xmm0
    movsd %xmm0, (%rsp)
    movq %rbx, %rdi
    call gsd_asm_mt_u32
    shrl $6, %eax
    cvtsi2sdq %rax, %xmm1
    movsd (%rsp), %xmm0
    mulsd .Ltwo26(%rip), %xmm0
    addsd %xmm1, %xmm0
    mulsd .Linv53(%rip), %xmm0
    addq $16, %rsp
    popq %rbx
    ret
    .size gsd_asm_mt_random, .-gsd_asm_mt_random

    .globl gsd_asm_mt_bits
    .type gsd_asm_mt_bits, @function
gsd_asm_mt_bits:
    pushq %rbx
    pushq %r12
    pushq %r13
    pushq %r14
    subq $8, %rsp
    movq %rdi, %rbx
    movl %esi, %r13d
    cmpl $32, %r13d
    ja .Lwide
    call gsd_asm_mt_u32
    movl $32, %ecx
    subl %r13d, %ecx
    shrl %cl, %eax
    jmp .Lbits_done
.Lwide:
    xorl %r12d, %r12d
    xorl %r14d, %r14d
.Lword:
    movq %rbx, %rdi
    call gsd_asm_mt_u32
    cmpl $32, %r13d
    jae 4f
    movl $32, %ecx
    subl %r13d, %ecx
    shrl %cl, %eax
4:
    movl %r14d, %ecx
    shlq %cl, %rax
    orq %rax, %r12
    addl $32, %r14d
    cmpl $32, %r13d
    jbe 5f
    subl $32, %r13d
    jmp .Lword
5:
    movq %r12, %rax
.Lbits_done:
    addq $8, %rsp
    popq %r14
    popq %r13
    popq %r12
    popq %rbx
    ret
    .size gsd_asm_mt_bits, .-gsd_asm_mt_bits

    .globl gsd_asm_mt_below
    .type gsd_asm_mt_below, @function
gsd_asm_mt_below:
    testq %rsi, %rsi
    jnz 6f
    xorl %eax, %eax
    ret
6:
    pushq %rbx
    pushq %r12
    pushq %r13
    movq %rdi, %rbx
    movq %rsi, %r12
    bsrq %rsi, %rcx
    incl %ecx
    movl %ecx, %r13d
.Lagain:
    movq %rbx, %rdi
    movl %r13d, %esi
    call gsd_asm_mt_bits
    cmpq %r12, %rax
    jae .Lagain
    popq %r13
    popq %r12
    popq %rbx
    ret
    .size gsd_asm_mt_below, .-gsd_asm_mt_below

    .globl gsd_asm_accept
    .type gsd_asm_accept, @function
gsd_asm_accept:
    pushq %rbx
    subq $16, %rsp
    movq %rdi, %rbx
    movapd %xmm0, %xmm3
    xorpd .Lsign(%rip), %xmm3
    mulsd %xmm1, %xmm3
    addsd %xmm2, %xmm3
    movsd %xmm3, (%rsp)
    call gsd_asm_mt_random
    addsd .Ltiny(%rip), %xmm0
    call log@PLT
    movsd (%rsp), %xmm1
    xorl %eax, %eax
    ucomisd %xmm0, %xmm1
    seta %al
    addq $16, %rsp
    popq %rbx
    ret
    .size gsd_asm_accept, .-gsd_asm_accept

    .globl gsd_asm_energy
    .type gsd_asm_energy, @function
gsd_asm_energy:
    movsd .Lone(%rip), %xmm4
    testl %r8d, %r8d
    jnz 7f
    xorpd .Lsign(%rip), %xmm4
7:
    leaq (%rdx,%rdx), %rax
    leaq 1(%rax), %rax
    leaq 1(%rcx,%rcx), %r10
    addq %r10, %rax
    cvtsi2sdq %rax, %xmm5
    mulsd %xmm4, %xmm5
    leaq (%rdx,%rcx), %rax
    cvtsi2sdq %rax, %xmm6
    mulsd %xmm4, %xmm6
    movsd %xmm4, (%r9)
    movsd %xmm5, 8(%r9)
    movsd %xmm6, 16(%r9)
    xorpd %xmm0, %xmm0
    xorpd %xmm1, %xmm1
    pushq %rbx
    pushq %r12
    pushq %r13
    pushq %r14
    movq %rdi, %r12
    movq %rsi, %r13
    xorl %r14d, %r14d
.Lnode:
    cmpq %r13, %r14
    jae .Lnodes_done
    leaq (%r14,%r14,2), %rax
    leaq (%r12,%rax,8), %rbx
    movq (%rbx), %rax
    cmpq $9, %rax
    je .Lanchor
    cmpq $10, %rax
    je .Lanchor_abs
    jmp .Lnode_next
.Lanchor:
    movq 16(%rbx), %r10
    movq %rdx, %rax
    subq %r10, %rax
    leaq 1(%rax,%rax), %r11
    movq %rcx, %rax
    subq %r10, %rax
    leaq 1(%rax,%rax), %rax
    addq %rax, %r11
    jmp .Lnode_part
.Lanchor_abs:
    movq 16(%rbx), %r10
    movq %rdx, %rax
    subq %r10, %rax
    sarq $63, %rax
    leaq 1(%rax,%rax), %r11
    movq %rcx, %rax
    subq %r10, %rax
    sarq $63, %rax
    leaq 1(%rax,%rax), %rax
    addq %rax, %r11
.Lnode_part:
    movsd 8(%rbx), %xmm2
    mulsd %xmm4, %xmm2
    cvtsi2sdq %r11, %xmm3
    mulsd %xmm3, %xmm2
    addsd %xmm2, %xmm0
    andpd .Labs(%rip), %xmm2
    addsd %xmm2, %xmm1
.Lnode_next:
    incq %r14
    jmp .Lnode
.Lnodes_done:
    xorl %r14d, %r14d
.Lterm:
    cmpq %r13, %r14
    jae .Lterms_done
    leaq (%r14,%r14,2), %rax
    leaq (%r12,%rax,8), %rbx
    movq (%rbx), %rax
    cmpq $2, %rax
    ja .Lterm_next
    movsd 8(%rbx), %xmm2
    mulsd (%r9,%rax,8), %xmm2
    addsd %xmm2, %xmm0
    andpd .Labs(%rip), %xmm2
    addsd %xmm2, %xmm1
.Lterm_next:
    incq %r14
    jmp .Lterm
.Lterms_done:
    popq %r14
    popq %r13
    popq %r12
    popq %rbx
    mulsd .Lshare(%rip), %xmm1
    movapd %xmm0, %xmm2
    andpd .Labs(%rip), %xmm2
    ucomisd %xmm1, %xmm2
    ja 8f
    jp 8f
    xorpd %xmm0, %xmm0
8:
    ret
    .size gsd_asm_energy, .-gsd_asm_energy

    .section .note.GNU-stack,"",@progbits
