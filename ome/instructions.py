# ome - Object Message Expressions
# Copyright (c) 2015 Luke McCarthy <luke@iogopro.co.uk>. All rights reserved.

def format_instruction_args(args):
    return ' ' + ' '.join('%%%s' % x for x in args) if args else ''

class Instruction(object):
    args = ()
    label = None

    def emit(self, target):
        getattr(target, self.__class__.__name__)(self)

class CALL(Instruction):
    def __init__(self, dest, receiver, args, call_label, traceback_info):
        self.dest = dest
        self.args = [receiver] + args
        self.call_label = call_label
        self.traceback_info = traceback_info

    def __str__(self):
        dest = '%%%s = ' % self.dest if self.dest else ''
        return '%sCALL %s%s' % (dest, self.call_label, format_instruction_args(self.args))

class TAG(Instruction):
    def __init__(self, dest, source, tag):
        self.dest = dest
        self.args = [source]
        self.tag = tag

    def __str__(self):
        return '%%%s = TAG %%%s $%04X' % (self.dest, self.source, self.tag)

    @property
    def source(self):
        return self.args[0]

class UNTAG(Instruction):
    def __init__(self, dest, source):
        self.dest = dest
        self.args = [source]

    def __str__(self):
        return '%%%s = UNTAG %%%s' % (self.dest, self.source)

    @property
    def source(self):
        return self.args[0]

class CREATE(Instruction):
    def __init__(self, dest, tag, num_slots):
        self.dest = dest
        self.tag = tag
        self.num_slots = num_slots

    def __str__(self):
        return '%%%s = CREATE $%04X %d' % (self.dest, self.tag, self.num_slots)

class CREATE_ARRAY(Instruction):
    def __init__(self, dest, size):
        self.dest = dest
        self.size = size

    def __str__(self):
        return '%%%s = CREATE_ARRAY %s' % (self.dest, self.size)

class ALIAS(Instruction):
    def __init__(self, dest, source):
        self.dest = dest
        self.args = [source]

    def __str__(self):
        return '%%%s = %%%s' % (self.dest, self.source)

    @property
    def source(self):
        return self.args[0]

class LOAD_VALUE(Instruction):
    def __init__(self, dest, tag, value):
        self.dest = dest
        self.tag = tag
        self.value = value

    def __str__(self):
        return '%%%s = $%04X:%012X' % (self.dest, self.tag, self.value)

class LOAD_STRING(Instruction):
    def __init__(self, dest, string):
        self.dest = dest
        self.string = string

    def __str__(self):
        return "%%%s = '%s'" % (self.dest, self.string)

class GET_SLOT(Instruction):
    def __init__(self, dest, object, slot_index):
        self.dest = dest
        self.args = [object]
        self.slot_index = slot_index

    def __str__(self):
        return '%%%s = %%%s[%d]' % (self.dest, self.object, self.slot_index)

    @property
    def object(self):
        return self.args[0]

class SET_SLOT(Instruction):
    def __init__(self, object, slot_index, value):
        self.args = [object, value]
        self.slot_index = slot_index

    @property
    def object(self):
        return self.args[0]

    @property
    def value(self):
        return self.args[1]

    def __str__(self):
        return '%%%s[%d] := %%%s' % (self.object, self.slot_index, self.value)

class RETURN(Instruction):
    def __init__(self, source):
        self.args = [source]

    @property
    def source(self):
        return self.args[0]

    def __str__(self):
        return 'RETURN%s' % format_instruction_args(self.args)

# SPILL, UNSPILL, MOVE, and PUSH are generated by the register allocator

class SPILL(Instruction):
    def __init__(self, register, stack_slot):
        self.register = register
        self.stack_slot = stack_slot

    def __str__(self):
        return 'stack[%d] := %%%s' % (self.stack_slot, self.register)

class UNSPILL(Instruction):
    def __init__(self, register, stack_slot):
        self.register = register
        self.stack_slot = stack_slot

    def __str__(self):
        return '%%%s := stack[%d]' % (self.register, self.stack_slot)

class MOVE(Instruction):
    def __init__(self, dest_reg, source_reg):
        self.dest_reg = dest_reg
        self.source_reg = source_reg

    def __str__(self):
        return '%%%s := %%%s' % (self.dest_reg, self.source_reg)

class PUSH(Instruction):
    def __init__(self, source_reg):
        self.source_reg = source_reg

    def __str__(self):
        return 'PUSH %%%s' % self.source_reg
