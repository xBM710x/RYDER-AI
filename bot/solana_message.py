"""Bounded legacy/v0 message inspection, NOT swap authorization.

No signing or RPC calls. Lookup keys and instruction semantics still require
independent validation before any future signing implementation.
"""
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


class InvalidMessage(ValueError):
    pass


def encode_key(raw):
    number = int.from_bytes(raw, 'big')
    text = ''
    while number:
        number, remainder = divmod(number, 58)
        text = ALPHABET[remainder] + text
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + text


class Reader:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def take(self, length):
        if length < 0 or self.pos + length > len(self.data):
            raise InvalidMessage('Truncated transaction')
        chunk = self.data[self.pos:self.pos + length]
        self.pos += length
        return chunk

    def byte(self):
        return self.take(1)[0]

    def length(self):
        value = 0
        for index in range(3):
            byte = self.byte()
            if index == 2 and byte > 3:
                raise InvalidMessage('Invalid compact length')
            value |= (byte & 127) << (7 * index)
            if not byte & 128:
                if index and byte == 0:
                    raise InvalidMessage('Noncanonical compact length')
                return value
        raise InvalidMessage('Invalid compact length')


def inspect_unsigned(data, wallet):
    if not isinstance(data, bytes) or not 65 <= len(data) <= 1232:
        raise InvalidMessage('Unsupported transaction size')
    reader = Reader(data)
    signature_count = reader.length()
    if not 1 <= signature_count <= 16:
        raise InvalidMessage('Invalid signature count')
    signatures = reader.take(signature_count * 64)
    # Only completely unsigned inputs are accepted by this preflight path.
    if any(signatures):
        raise InvalidMessage('Expected unsigned transaction')
    first = reader.byte()
    version = 'legacy'
    if first & 128:
        if first != 128:
            raise InvalidMessage('Unsupported transaction version')
        version = 'v0'
        required = reader.byte()
    else:
        required = first
    readonly_signed, readonly_unsigned = reader.byte(), reader.byte()
    key_count = reader.length()
    if not 1 <= required == signature_count <= key_count <= 256:
        raise InvalidMessage('Invalid signer/account counts')
    if readonly_signed >= required or readonly_unsigned > key_count - required:
        raise InvalidMessage('Invalid readonly account counts')
    keys = [encode_key(reader.take(32)) for _ in range(key_count)]
    if len(set(keys)) != len(keys):
        raise InvalidMessage('Duplicate static accounts')
    if keys[0] != wallet:
        raise InvalidMessage('Transaction fee payer does not match configured wallet')
    # Additional signers need their own explicit policy; never infer consent.
    if required != 1:
        raise InvalidMessage('Additional required signers are not supported')
    reader.take(32)  # recent blockhash; freshness is checked separately by RPC
    instructions = []
    for _ in range(reader.length()):
        program = reader.byte()
        accounts = list(reader.take(reader.length()))
        payload = reader.take(reader.length())
        instructions.append((program, accounts, len(payload)))
    if not instructions:
        raise InvalidMessage('Transaction has no instructions')
    loaded_count = 0
    lookups = []
    if version == 'v0':
        for _ in range(reader.length()):
            table = encode_key(reader.take(32))
            writable = list(reader.take(reader.length()))
            readonly = list(reader.take(reader.length()))
            if not writable and not readonly:
                raise InvalidMessage('Empty lookup table reference')
            if len(set(writable + readonly)) != len(writable + readonly):
                raise InvalidMessage('Duplicate lookup indices')
            loaded_count += len(writable) + len(readonly)
            lookups.append(table)
    if reader.pos != len(data):
        raise InvalidMessage('Trailing transaction bytes')
    if key_count + loaded_count > 256 or len(set(lookups)) != len(lookups):
        raise InvalidMessage('Invalid lookup account count or duplicate table')
    programs = []
    for program, accounts, _ in instructions:
        # Invoked program IDs must be static, readonly nonsigners.
        if not key_count - readonly_unsigned <= program < key_count:
            raise InvalidMessage('Program must be a readonly static nonsigner')
        if any(index >= key_count + loaded_count for index in accounts):
            raise InvalidMessage('Instruction account index out of range')
        programs.append(keys[program])
    return dict(version=version, fee_payer=keys[0], signer_count=required,
        instruction_count=len(instructions), program_ids=sorted(set(programs)),
        lookup_table_count=len(lookups), unresolved_lookup_accounts=loaded_count,
        authorized_to_sign=False)
