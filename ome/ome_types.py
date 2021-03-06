# ome - Object Message Expressions
# Copyright (c) 2015-2016 Luke McCarthy <luke@iogopro.co.uk>

class BuiltIn(object):
    def __init__(self):
        self.code = []
        self.methods = []
        self.messages = []
        self.defaults = {}
        self.constant_names = ['False', 'True', 'Less', 'Equal', 'Greater', 'Empty', 'BuiltIn']
        self.opaque_names = ['Constant', 'Small-Integer']
        self.pointer_names = ['String', 'Array', 'Large-Integer']

class BuiltInMethod(object):
    def __init__(self, tag_name, symbol, arg_names, sent_messages, code):
        self.tag_name = tag_name
        self.symbol = symbol
        self.arg_names = arg_names
        self.sent_messages = sent_messages
        self.code = code

    def generate_target_code(self, label, target):
        return target.generate_builtin_method(label, self.arg_names, self.code)

    def __repr__(self):
        return 'BuiltInMethod(%r, %r, %r, %r, %r)' % (self.tag_name, self.symbol, self.arg_names, self.sent_messages, self.code)

class TraceBackInfo(object):
    def __init__(self, index, method_name, stream_name, source_line, line_number, column, underline):
        self.index = index
        self.method_name = method_name
        self.stream_name = stream_name
        self.source_line = source_line
        self.line_number = line_number
        self.column = column
        self.underline = underline

class CompileOptions(object):
    def __init__(self):
        self.verbose = False
        self.traceback = True
        self.source_traceback = True
