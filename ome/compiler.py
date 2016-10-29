# ome - Object Message Expressions
# Copyright (c) 2015-2016 Luke McCarthy <luke@iogopro.co.uk>. All rights reserved.

import io
import os
import re
import subprocess
import sys

from . import constants
from .ast import Block, BuiltInBlock, Method, Send, Sequence
from .constants import *
from .dispatcher import generate_dispatcher, generate_lookup_dispatcher
from .error import OmeError
from .labels import *
from .parser import Parser
from .target import target_platform_map, default_target_platform

class TraceBackInfo(object):
    def __init__(self, index, method_name, stream_name, source_line, line_number, column, underline):
        self.index = index
        self.method_name = method_name
        self.stream_name = stream_name
        self.source_line = source_line
        self.line_number = line_number
        self.column = column
        self.underline = underline

def collect_nodes_of_type(ast, node_type):
    nodes = []
    def append_block(node):
        if isinstance(node, node_type):
            nodes.append(node)
    ast.walk(append_block)
    return nodes

class IdAllocator(object):
    def __init__(self, opaque_tag_names=(), pointer_tag_names=(), constant_names=()):
        self.opaque_tag_names = list(opaque_tag_names)
        self.pointer_tag_names = list(pointer_tag_names)
        self.constant_names = list(constant_names)

    def allocate_ids(self, block_list):
        self.tags = {}
        self.tag_list = []
        tag_id = 0
        for name in self.opaque_tag_names:
            self.tags[name] = tag_id
            self.tag_list.append((name, tag_id))
            tag_id += 1
        self.pointer_tag_id = tag_id
        for name in self.pointer_tag_names:
            self.tags[name] = tag_id
            self.tag_list.append((name, tag_id))
            tag_id += 1
        for block in block_list:
            if not block.is_constant:
                block.tag = tag_id
                tag_id += 1
        if tag_id > MAX_TAG:
            raise OmeError('exhausted all tag IDs')

        self.constants = {}
        self.constant_list = []
        constant_id = 0
        for name in self.constant_names:
            self.constants[name] = constant_id
            self.constant_list.append((name, constant_id))
            self.tags[name] = constant_to_tag(constant_id)
            constant_id += 1
        for block in block_list:
            if block.is_constant:
                block.tag = constant_to_tag(constant_id)
                block.tag_constant = constant_id
                constant_id += 1
        if constant_id > MAX_CONSTANT_TAG:
            raise OmeError('exhausted all constant tag IDs')

        self.last_tag_id = tag_id
        self.last_constant_id = constant_id

        assert Tag_Constant == self.tags['Constant']
        assert Constant_BuiltIn == self.constants['BuiltIn']

class Program(object):
    def __init__(self, filename, ast, builtin, target, debug=True):
        self.filename = filename
        self.toplevel_method = ast
        self.builtin = builtin
        self.target = target
        self.debug = debug

        self.code_table = []  # list of (symbol, [list of (tag, method)])
        self.data_table = target.DataTable()
        self.traceback_table = {}
        self.block_list = collect_nodes_of_type(ast, Block)
        self.send_list = collect_nodes_of_type(ast, Send)

        toplevel_block = ast.expr
        if isinstance(toplevel_block, Sequence):
            toplevel_block = self.toplevel_block.statements[-1]
        if 'main' not in toplevel_block.symbols:
            self.error('no main method defined')

        self.ids = IdAllocator(opaque_type_names, pointer_type_names, constant_names)
        self.ids.allocate_ids(self.block_list)
        self.compile_traceback_info()
        self.find_used_methods()
        self.build_code_table()

    def error(self, message):
        raise OmeError(message, self.filename)

    def warning(self, message):
        sys.stderr.write('\x1b[1m{0}: \x1b[35mwarning:\x1b[0m {1}\n'.format(self.filename, message))

    def compile_traceback_info(self):
        for send in self.send_list:
            if send.parse_state:
                ps = send.parse_state
                key = (ps.stream_name, ps.line_number, ps.column)
                if key in self.traceback_table:
                    tbinfo = self.traceback_table[key]
                else:
                    line_unstripped = ps.current_line.rstrip()
                    line = line_unstripped.lstrip()
                    column = ps.column - (len(line_unstripped) - len(line))
                    underline = send.symbol.find(':') + 1
                    if underline < 1:
                        underline = max(len(send.symbol), 1)
                    tbinfo = TraceBackInfo(
                        index = len(self.traceback_table),
                        method_name = send.method.symbol,
                        stream_name = ps.stream_name,
                        source_line = line,
                        line_number = ps.line_number,
                        column = column,
                        underline = underline)
                    self.traceback_table[key] = tbinfo
                send.traceback_info = tbinfo

    def find_used_methods(self):
        self.sent_messages = set(['main', 'string'])
        self.sent_messages.update(
            send.symbol for send in self.send_list if send.receiver and not send.receiver_block)

        called_methods = set(
            (send.receiver_block.tag, send.symbol) for send in self.send_list
            if send.receiver_block and send.symbol not in self.sent_messages)

        for method in self.target.builtin_methods:
            method_tag = self.ids.tags[method.tag_name]
            if method.sent_messages and (method.symbol in self.sent_messages or (method_tag, method.symbol) in called_methods):
                self.sent_messages.update(method.sent_messages)

        self.called_methods = set(
            (send.receiver_block.tag, send.symbol) for send in self.send_list
            if send.receiver_block and send.symbol not in self.sent_messages)

    def should_include_method(self, method, tag):
        return method.symbol in self.sent_messages or (tag, method.symbol) in self.called_methods

    def compile_method(self, method):
        return method.generate_code(self)

    def build_code_table(self):
        methods = {}

        for method in self.target.builtin_methods:
            if self.should_include_method(method, self.builtin.tag):
                if method.symbol not in methods:
                    methods[method.symbol] = []
                method_tag = self.ids.tags[method.tag_name]
                methods[method.symbol].append((method_tag, method))

        for block in self.block_list:
            for method in block.methods:
                if self.should_include_method(method, block.tag):
                    if method.symbol not in methods:
                        methods[method.symbol] = []
                    code = self.compile_method(method)
                    methods[method.symbol].append((block.tag, code))

        for symbol in sorted(methods.keys()):
            self.code_table.append((symbol, methods[symbol]))

    def emit_constants(self, out):
        define_format = self.target.define_constant_format
        for name, value in sorted(constants.__dict__.items()):
            if isinstance(value, int) and not name.startswith(('Tag_', 'Constant_')):
                out.write(define_format.format('OME_' + name, value))
        for name, value in self.ids.tag_list:
            out.write(define_format.format('OME_Tag_' + name.replace('-', '_'), value))
        out.write(define_format.format('OME_Pointer_Tag', self.ids.pointer_tag_id))
        for name, value in self.ids.constant_list:
            out.write(define_format.format('OME_Constant_' + name.replace('-', '_'), value))
        out.write('\n')
        out.write(self.target.builtin_macros)

    def emit_data(self, out):
        out.write(self.target.builtin_data)
        out.write('\n')
        self.data_table.emit(out)
        out.write('\n')
        traceback_entries = sorted(self.traceback_table.values(), key=lambda tb: tb.index)
        self.target.emit_traceback_table(out, traceback_entries)
        out.write('\n')

    def emit_code_declarations(self, out):
        self.target.emit_declaration(out, 'OME_toplevel', 1)
        method_decls = set()
        message_decls = set(self.sent_messages)
        for symbol, methods in self.code_table:
            message_decls.add(symbol)
            for tag, code in methods:
                method_decls.add((symbol, tag))
        for symbol, tag in sorted(method_decls):
            self.target.emit_declaration(out, make_method_label(tag, symbol), symbol_arity(symbol))
        for symbol in sorted(message_decls):
            self.target.emit_declaration(out, make_message_label(symbol), symbol_arity(symbol))
        for symbol in sorted(message_decls):
            self.target.emit_lookup_declaration(out, make_lookup_label(symbol), symbol_arity(symbol))
        out.write('\n')

    def emit_code_definitions(self, out):
        out.write(self.target.builtin_code)
        out.write('\n')

        dispatchers = set()
        for symbol, methods in self.code_table:
            for tag, code in methods:
                out.write(code.generate_target_code(make_method_label(tag, symbol), self.target))
                out.write('\n')
            if symbol in self.sent_messages:
                tags = [tag for tag, code in methods]
                out.write(generate_dispatcher(symbol, tags, self.target))
                out.write('\n')
                out.write(generate_lookup_dispatcher(symbol, tags, self.target))
                out.write('\n')
                dispatchers.add(symbol)

        optional_messages = ['return']
        for symbol in sorted(self.sent_messages):
            if symbol not in dispatchers:
                if symbol not in optional_messages:
                    self.warning("no methods defined for message '%s'" % symbol)
                out.write(generate_dispatcher(symbol, [], self.target))
                out.write('\n')
                out.write(generate_lookup_dispatcher(symbol, [], self.target))
                out.write('\n')

    def emit_toplevel(self, out):
        code = self.compile_method(self.toplevel_method)
        out.write(code.generate_target_code('OME_toplevel', self.target))
        out.write(self.target.builtin_code_main)

    def emit_program_text(self, out):
        self.emit_constants(out)
        self.emit_data(out)
        self.emit_code_declarations(out)
        self.emit_code_definitions(out)
        self.emit_toplevel(out)

def parse_file(filename):
    try:
        with open(filename) as f:
            source = f.read()
    except FileNotFoundError:
        raise OmeError('file does not exist: ' + filename)
    except UnicodeDecodeError as e:
        raise OmeError('utf-8 decoding failed at position {0.start}: {0.reason}'.format(e), filename)
    except Exception as e:
        raise OmeError(str(e), filename)
    return Parser(source, filename).toplevel()

def compile_file_to_code(filename, target):
    builtin = BuiltInBlock(target)
    ast = parse_file(filename)
    ast = Method('', [], ast)
    ast = ast.resolve_free_vars(builtin)
    ast = ast.resolve_block_refs(builtin)
    program = Program(filename, ast, builtin, target)
    out = io.StringIO()
    program.emit_program_text(out)
    asm = out.getvalue()
    return asm.encode('utf8')

def run_assembler(target, input, outfile):
    p = subprocess.Popen(target.get_assembler_args(outfile), stdin=subprocess.PIPE)
    p.communicate(input)
    if p.returncode != 0:
        sys.exit(p.returncode)

def run_linker(target, infile, outfile):
    p = subprocess.Popen(target.get_linker_args(infile, outfile))
    p.communicate()
    if p.returncode != 0:
        sys.exit(p.returncode)

def compile_file(filename, target_platform=default_target_platform):
    if target_platform not in target_platform_map:
        raise OmeError('unsupported target platform: {0}-{1}'.format(*target_platform))
    target = target_platform_map[target_platform]
    asm = compile_file_to_code(filename, target)
    exe_file = os.path.splitext(filename)[0]
    obj_file = exe_file + '.o'
    run_assembler(target, asm, obj_file)
    run_linker(target, obj_file, exe_file)
