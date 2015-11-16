from .ast import BuiltInMethod
from .constants import *

class Target_x86_64(object):
    stack_pointer = 'rsp'
    context_pointer = 'rbp'
    nursery_bump_pointer = 'rbx'
    nursery_limit_pointer = 'r12'
    arg_registers = ('rdi', 'rsi', 'rdx', 'rcx', 'r8', 'r9')
    return_register = 'rax'
    temp_registers = ('r10', 'r11')

    def __init__(self, emitter):
        self.emit = emitter
        self.num_jumpback_labels = 0

    def emit_enter(self, num_stack_slots):
        if num_stack_slots > 0:
            self.emit('sub rsp, %s', num_stack_slots * 8)

    def emit_leave(self, num_stack_slots):
        if num_stack_slots > 0:
            self.emit('add rsp, %s', num_stack_slots * 8)
        self.emit('ret')

    def emit_dispatch(self, any_constant_tags):
        self.emit('mov rax, %s', self.arg_registers[0])
        self.emit('shr rax, %s', NUM_DATA_BITS)
        if any_constant_tags:
            self.emit('cmp rax, %s', Tag_Constant)
            self.emit('je .constant')
        self.emit.label('.dispatch')
        if any_constant_tags:
            const_emit = self.emit.tail_emitter('.constant')
            const_emit('xor rax, rax')
            const_emit('mov eax, edi')
            const_emit('add rax, 0x%x', 1 << NUM_TAG_BITS)
            const_emit('jmp .dispatch')
        not_understood_emit = self.emit.tail_emitter('.not_understood')
        not_understood_emit('jmp OME_not_understood')

    def emit_dispatch_compare_eq(self, tag, tag_label, exit_label):
        self.emit('cmp rax, 0x%X', tag)
        self.emit('jne %s', exit_label)
        self.emit('jmp %s', tag_label)

    def emit_dispatch_compare_gte(self, tag, gt_label):
        self.emit('cmp rax, 0x%X', tag)
        self.emit('jae %s', gt_label)

    def emit_jump(self, label):
        self.emit('jmp %s', label)

    def MOVE(self, ins):
        self.emit('mov %s, %s', ins.dest_reg, ins.source_reg)

    def SPILL(self, ins):
        self.emit('mov [rsp+%s], %s', ins.stack_slot * 8, ins.register)

    def UNSPILL(self, ins):
        self.emit('mov %s, [rsp+%s]', ins.register, ins.stack_slot * 8)

    def PUSH(self, ins):
        self.emit('push %s', ins.source_reg)

    def CALL(self, ins):
        self.emit('call %s', ins.call_label)
        if ins.num_stack_args > 0:
            self.emit('add rsp, %s', ins.num_stack_args * 8)

    def emit_tag(self, reg, tag):
        self.emit('shl %s, %s', reg, NUM_TAG_BITS - 3)
        self.emit('or %s, %s', reg, tag)
        self.emit('ror %s, %s', reg, NUM_TAG_BITS)

    def TAG(self, ins):
        if ins.dest != ins.source:
            self.emit('mov %s, %s', ins.dest, ins.source)
        self.emit_tag(ins.dest, ins.tag)

    def UNTAG(self, ins):
        if ins.dest != ins.source:
            self.emit('mov %s, %s', ins.dest, ins.source)
        self.emit('shl %s, %s', ins.dest, NUM_TAG_BITS)
        self.emit('shr %s, %s', ins.dest, NUM_TAG_BITS - 3)

    def LOAD_VALUE(self, ins):
        value = encode_tagged_value(ins.value, ins.tag)
        self.emit('mov %s, 0x%x', ins.dest, value)

    def LOAD_STRING(self, ins):
        self.emit('lea %s, [rel %s]', ins.dest, ins.data_label)
        self.emit_tag(ins.dest, Tag_String)

    def GET_SLOT(self, ins):
        self.emit('mov %s, [%s+%s]', ins.dest, ins.object, ins.slot_index * 8)

    def SET_SLOT(self, ins):
        self.emit('mov [%s+%s], %s', ins.object, ins.slot_index * 8, ins.value)

    def emit_create(self, dest, num_slots):
        return_label = '.gc_return_%d' % self.num_jumpback_labels
        full_label = '.gc_full_%d' % self.num_jumpback_labels
        self.num_jumpback_labels += 1

        self.emit.label(return_label)
        self.emit('mov %s, %s', dest, self.nursery_bump_pointer)
        self.emit('add %s, %s', self.nursery_bump_pointer, (num_slots + 1) * 8)
        self.emit('cmp %s, %s', self.nursery_bump_pointer, self.nursery_limit_pointer)
        self.emit('jae %s', full_label)

        tail_emit = self.emit.tail_emitter(full_label)
        tail_emit('call OME_collect_nursery')
        tail_emit('jmp %s', return_label)

    def CREATE(self, ins):
        self.emit_create(ins.dest, ins.num_slots)

    def CREATE_ARRAY(self, ins):
        self.emit_create(ins.dest, ins.size)
        self.emit('mov dword [%s-4], %s', ins.dest, ins.size)

    builtin_code = '''\
%define OME_NUM_TAG_BITS {NUM_TAG_BITS}
%define OME_NUM_DATA_BITS {NUM_DATA_BITS}
%define OME_Value(value, tag) (((tag) << OME_NUM_DATA_BITS) | (value))
%define OME_Constant(value) OME_Value(value, OME_Tag_Constant)
%define OME_Error_Tag(tag) ((tag) | (1 << (OME_NUM_TAG_BITS - 1)))
%define OME_Error_Constant(value) OME_Value(value, OME_Error_Tag(OME_Tag_Constant))

%define OME_Tag_Constant 2
%define OME_Tag_String 256
%define OME_Constant_TopLevel 1
%define OME_Constant_TypeError 2

%define SYS_write 1
%define SYS_mmap 9
%define SYS_mprotect 10
%define SYS_munmap 11
%define SYS_mremap 25
%define SYS_exit 60

%define MAP_PRIVATE 0x2
%define MAP_ANONYMOUS 0x20

%define PROT_READ 0x1
%define PROT_WRITE 0x2
%define PROT_EXEC 0x4

global _start
_start:
	call OME_allocate_thread_context
	lea rsp, [rax+0x1000]  ; stack pointer (grows down)
	mov rbx, rsp           ; GC nursery pointer (grows up)
	lea r12, [rax+0x4000]  ; GC nursery limit
	call OME_toplevel
	mov rdi, rax
	call {MAIN}
	xor rdi, rdi
	test rax, rax
	jns .success
	inc rdi
.success:
	mov rax, SYS_exit
	syscall

OME_allocate_thread_context:
	mov rax, SYS_mmap
	xor rdi, rdi	  ; addr
	mov rsi, 0xA000   ; size
	xor rdx, rdx	  ; PROT_NONE
	mov r10, MAP_PRIVATE|MAP_ANONYMOUS
	mov r8, r8
	dec r8
	xor r9, r9
	syscall
	lea rdi, [rax+0x1000]  ; save pointer returned by mmap
	push rdi
	shr rax, 47   ; test for MAP_FAILED or address that is too big
	jnz .panic
	mov rax, SYS_mprotect
	mov rsi, 0x8000
	mov rdx, PROT_READ|PROT_WRITE
	syscall
	test rax, rax
	js .panic
	pop rax
	ret
.panic:
	mov rsi, OME_message_mmap_failed
	mov rdx, OME_message_mmap_failed.size
	jmp OME_panic

OME_collect_nursery:
	lea rsi, [rel OME_message_collect_nursery]
	mov rdx, OME_message_collect_nursery.size
OME_panic:
	mov rax, SYS_write
	mov rdi, 2
	syscall
	mov rax, SYS_exit
	mov rdi, 1
	syscall

OME_not_understood:
	lea rsi, [rel OME_message_not_understood]
	mov rdx, OME_message_not_understood.size
	jmp OME_panic

'''

    builtin_data = '''\
OME_message_mmap_failed
.str:
	db "Failed to allocate thread context", 10
.size equ $-.str

OME_message_collect_nursery:
.str:
	db "Garbage collector called", 10
.size equ $-.str

OME_message_not_understood:
.str:
	db "Message not understood", 10
.size equ $-.str
'''

    builtin_methods = [
        BuiltInMethod('print:', constant_to_tag(Constant_TopLevel), '''\
	mov rax, rsi
	shr rax, OME_NUM_DATA_BITS
	cmp rax, OME_Tag_String
	jne .type_error
	shl rsi, OME_NUM_TAG_BITS
	shr rsi, OME_NUM_TAG_BITS - 3
	mov rdx, [rsi]
	add rsi, 8
	mov rax, SYS_write
	mov rdi, 1
	syscall
	sub rsp, 8
	mov [rsp], byte 10
	mov rsi, rsp
	mov rdx, 1
	mov rax, SYS_write
	mov rdi, 1
	syscall
	add rsp, 8
	ret
.type_error:
	mov rax, OME_Error_Constant(OME_Constant_TypeError)
	ret
'''),
    ]