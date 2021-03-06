"""
Author:@Tera0017
"""
import yara
import struct
import pefile
from ta505_gen_funcs import *

rules = {
    # Finds encoded code PART 1 + its length then can find exec code and xor key (strict rule)
    '$code1': '{68 F4 0B 00 00 68 [4] 8B ?? [4] 5? E8}',
    # // Finds encoded code PART 1 + its length then can find exec code and xor key (wider rule)
    '$code2': '{68 [4] 68 [4] 8B 85 [4] 50 E8}',
    # // Getting exec code PART I + size
    '$code3': '{C7 45 ?? [4] C7 45 ?? 00 00 00 00 C7 45 ?? 00 00 00 00 EB [10] 81 [2] 84 03 00 00}',
    # // Getting directly code and size
    '$code4': '{A3 [4] C7 05 [8] C7 05 [8] (8?| A1)}',
    # // Getting directly code and size
    '$code5': '{89 [2] C7 45 ?? [4] C7 45 ?? [4] 8? 15 [4] 8?}',
    # // check which code decrypts code (which usually is the same as exec layer 1)
    '$code6': '{E8 03 00 00 89 [2] C1 [2] FF FF FF 07}',
}

tmp_rule = '''
rule match_rule
{
    strings:
        %s = %s
    condition:
        any of them
}'''.strip()


class TA505Packer:

    def __init__(self, file_data):
        self.file_data = file_data
        self.layer1_encryption = ''

    def match_rule(self, rule):
        myrules = tmp_rule % (rule, rules[rule])
        yararules = yara.compile(source=myrules)
        return yararules.match(data=self.file_data)

    def find_exec_xor_addr(self):
        # finds the encoded code PART I and from that gets xor and executable code (Getandgo)
        for rule in ['$code1', '$code2']:
            match = self.match_rule(rule)
            if match and len(match) == 1:
                opcodes = match[0].strings[0][2]
                size = struct.unpack('I', opcodes[1:1+4])[0]
                encoded_code_addr = struct.unpack('I', opcodes[6:6+4])[0]
                xor_key_addr = encoded_code_addr + size
                executable_addr = xor_key_addr + 4
                return xor_key_addr, executable_addr
        # gets encrypted code and adding its size get the exe enc code + xor key (rest Silence/Azorult/Miner)
        for rule in ['$code3']:
            match = self.match_rule(rule)
            if match and len(match) == 1:
                opcodes = match[0].strings[0][2]
                encoded_code_addr = struct.unpack('I', opcodes[3:3 + 4])[0]
                executable_addr = encoded_code_addr + 0x384 * 4 + 4
                xor_key_addr = executable_addr - 4
                return xor_key_addr, executable_addr
        # gets directly the encrypted and size
        for rule in ['$code4']:
            match = self.match_rule(rule)
            if match and len(match) == 1:
                opcodes = match[0].strings[0][2]
                executable_addr = struct.unpack('I', opcodes[11: 11 + 4])[0]
                xor_key_addr = executable_addr - 4
                return xor_key_addr, executable_addr

        # gets directly the encrypted and size
        for rule in ['$code5']:
            match = self.match_rule(rule)
            if match and len(match) == 1:
                opcodes = match[0].strings[0][2]
                executable_addr = struct.unpack('I', opcodes[6: 6 + 4])[0]
                xor_key_addr = executable_addr - 4
                return xor_key_addr, executable_addr

        return None, None

    def get_layer1_encyption(self):
        if len(self.match_rule('$code6')) == 1:
            self.layer1_encryption = 'rol_7'
        else:
            self.layer1_encryption = 'rol_4'

    def get_enc_size(self, executable_address):
        exec_addr_op = struct.pack('I', executable_address)
        # finds address opcodes in executable, and after is the size
        exec_addr_op_usage = self.file_data.index(exec_addr_op)
        exec_addr_op_usage += self.file_data[exec_addr_op_usage:exec_addr_op_usage + 20].index('\xC7')
        spl_op = self.file_data[exec_addr_op_usage:exec_addr_op_usage + 2]
        # gets last for bytes of next instruction (size)
        size_data = self.file_data[exec_addr_op_usage: exec_addr_op_usage + 20].split(spl_op)[1]
        # C7 (05|85) -> 4
        pos = 1 if spl_op == '\xC7\x45' else 4
        return struct.unpack('I', size_data[pos: pos + 4])[0]

    def pickup_exact_code(self, temp_code):
        enc_exec_code = ''
        mod_val = 2 if self.layer1_encryption == 'rol_4' else 3
        pos_counter = 0
        counter = 0
        while pos_counter < len(temp_code):
            if not counter % mod_val:
                pos_counter += 2
            enc_exec_code += temp_code[pos_counter]
            pos_counter += 1
            counter += 1
        return enc_exec_code

    def get_exec_xor(self):
        xor_key_addr, exec_addr = self.find_exec_xor_addr()
        if not exec_addr and not xor_key_addr:
            return ['Error', ERROR01, None]

        # pefile works with RVA so changing the addresses.
        pe = pefile.PE(data=self.file_data)
        xor_key_addr -= pe.OPTIONAL_HEADER.ImageBase
        exec_addr -= pe.OPTIONAL_HEADER.ImageBase
        xor_key = struct.unpack('I', pe.get_data(rva=xor_key_addr, length=4))[0]

        self.get_layer1_encyption()
        exec_size = self.get_enc_size(exec_addr + pe.OPTIONAL_HEADER.ImageBase)
        message('Encrypted Layer One size: {}'.format(hex(exec_size).upper()))

        # For getandgodll mod is 2, for silence/miner/azorult its 3
        encoded_exec_code = self.pickup_exact_code(pe.get_data(rva=exec_addr, length=exec_size))

        encoded_exec_code = fix_dword(encoded_exec_code)

        return [encoded_exec_code, xor_key, self.layer1_encryption]
