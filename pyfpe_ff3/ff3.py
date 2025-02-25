"""

SPDX-Copyright: Copyright (c) Schoening Consulting, LLC
SPDX-License-Identifier: Apache-2.0
Copyright 2021 Schoening Consulting, LLC

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and limitations under the License.

"""

# Package pyfpe_ff3 implements the FF3-1 format-preserving encryption algorithm/scheme

import logging
import math
from Crypto.Cipher import AES
import string

DOMAIN_MIN = 1000000  # 1M is currently recommended in FF3-1
NUM_ROUNDS = 8 # below 19 rounds cipher is breakable but sticking with 8 for NIST tests vector compatibility
BLOCK_SIZE = 16  # aes.BlockSize
TWEAK_LEN = 8  # Original FF3 tweak length
TWEAK_LEN_NEW = 7  # FF3-1 tweak length
HALF_TWEAK_LEN = TWEAK_LEN // 2
MAX_RADIX = 64  # python int supports radix 2..36


def reverse_string(str):
    """func defined for clarity"""
    return str[::-1]


"""
FF3 encodes a string within a range of minLen..maxLen. The spec uses an alternating Feistel
with the following parameters:
    128 bit key length
    Cipher Block Chain (CBC-MAC) round function
    64-bit (FF3) or 56-bit (FF3-1)tweak
    eight (8) rounds
    Modulo addition

An encoded string representation of x is in the given integer base, which must be between 2 and 36, inclusive. The 
result uses the lower-case letters 'a' to 'z' for digit values 10 to 35.  Currently unimplemented, the
upper-case letters 'A' to 'Z' would represent digit values 36 to 61.

FF3Cipher initializes a new FF3 Cipher object for encryption or decryption with key, tweak and radix parameters. The
default radix is 10, supporting encryption of decimal numbers.

AES ECB is used as the cipher round value for XORing. ECB has a block size of 128 bits (i.e 16 bytes) and is 
padded with zeros for blocks smaller than this size. ECB is used only in encrypt mode to generate this XOR value. A Feistel 
decryption uses the same ECB encrypt value to decrypt the text. XOR is trivially invertible when you know two of the 
arguments.
"""


class FF3Cipher:
    """Class FF3Cipher implements the FF3 format-preserving encryption algorithm"""
    def __init__(self, key, tweak, radix=10, allow_small_domain=False, num_rounds=8, ):

        keyBytes = bytes.fromhex(key)
        self.tweak = tweak
        self.radix = radix
        domain_min= 10 if allow_small_domain else DOMAIN_MIN

        # Calculate range of supported message lengths [minLen..maxLen]
        # per original spec, radix^minLength >= 100.
        self.minLen = math.ceil(math.log(domain_min) / math.log(radix))

        # We simplify the specs log[radix](2^96) to 96/log2(radix) using the log base change rule
        self.maxLen = 2 * math.floor(96/math.log2(radix))

        klen = len(keyBytes)

        # Check if the key is 128, 192, or 256 bits = 16, 24, or 32 bytes
        if klen not in (16, 24, 32):
            raise ValueError(f'key length is {klen} but must be 128, 192, or 256 bits')

        # While FF3 allows radices in [2, 2^16], there is a practical limit to 36 (alphanumeric)
        # because python int only supports up to base 36.
        if (radix < 2) or (radix > MAX_RADIX):
            raise ValueError("radix must be between 2 and 36, inclusive")

        # Make sure 2 <= minLength <= maxLength
        if (self.minLen < 1) or (self.maxLen < self.minLen):
            raise ValueError("minLen or maxLen invalid, adjust your radix")

        # AES block cipher in ECB mode with the block size derived based on the length of the key
        # Always use the reversed key since Encrypt and Decrypt call ciph expecting that

        self.aesCipher = AES.new(reverse_string(keyBytes), AES.MODE_ECB)

    @staticmethod
    def calculateP(i, radix, W, B):
        # P is always 16 bytes
        P = bytearray(BLOCK_SIZE)

        # Calculate P by XORing W, i into the first 4 bytes of P
        # i only requires 1 byte, rest are 0 padding bytes
        # Anything XOR 0 is itself, so only need to XOR the last byte

        P[0] = W[0]
        P[1] = W[1]
        P[2] = W[2]
        P[3] = W[3] ^ int(i)

        # The remaining 12 bytes of P are for rev(B) with padding

        numB = reverse_string(B)
        numBBytes = int2(numB, radix).to_bytes(12, "big")
        # logging.debug(f"B: {B} numB: {numB} numBBytes: {numBBytes.hex()}")

        P[BLOCK_SIZE - len(numBBytes):] = numBBytes
        return P

    def encrypt(self, plaintext):
        """Encrypts the plaintext string and returns a ciphertext of the same length and format"""
        return self.encrypt_with_tweak(plaintext, self.tweak)

    """
    Feistel structure

            u length |  v length
            A block  |  B block

                C <- modulo function

            B' <- C  |  A' <- B


    Steps:

    Let u = [n/2]
    Let v = n - u
    Let A = X[1..u]
    Let B = X[u+1,n]
    Let T(L) = T[0..31] and T(R) = T[32..63]
    for i <- 0..7 do
        If is even, let m = u and W = T(R) Else let m = v and W = T(L)
        Let P = REV([NUM<radix>(Rev(B))]^12 || W ⊗ REV(i^4)
        Let Y = CIPH(P)
        Let y = NUM<2>(REV(Y))
        Let c = (NUM<radix>(REV(A)) + y) mod radix^m
        Let C = REV(STR<radix>^m(c))
        Let A = B
        Let B = C
    end for
    Return A || B

    * Where REV(X) reverses the order of characters in the character string X

    See spec and examples:

    https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-38Gr1-draft.pdf
    https://csrc.nist.gov/CSRC/media/Projects/Cryptographic-Standards-and-Guidelines/documents/examples/FF3samples.pdf
    """

    # EncryptWithTweak allows a parameter tweak instead of the current Cipher's tweak

    def encrypt_with_tweak(self, plaintext, tweak):
        """Encrypts the plaintext string and returns a ciphertext of the same length and format"""

        n = len(plaintext)
        if n > self.maxLen:
            r = "".join(self.encrypt_with_tweak(t,tweak) for t in self.chunk(plaintext))
            return r

        tweakBytes = bytes.fromhex(tweak)

        # Check if message length is within minLength and maxLength bounds
        if (n < self.minLen) or (n > self.maxLen):
            raise ValueError(f"message length {n} is not within min {self.minLen} and max {self.maxLen} bounds")

        # Make sure the given the length of tweak in bits is 56 or 64
        if len(tweakBytes) not in [TWEAK_LEN, TWEAK_LEN_NEW]:
            raise ValueError(f"tweak length {len(tweakBytes)} invalid: tweak must be 56 or 64 bits")

        # Check if the plaintext message is formatted in the current radix
        x = int2(plaintext, self.radix)
        if x == 0:
            raise ValueError("plaintext string is not within base/radix {self.radix}")

        # Calculate split point
        u = math.ceil(n / 2)
        v = n - u

        # Split the message
        A = plaintext[:u]
        B = plaintext[u:]

        if len(tweakBytes) == TWEAK_LEN:
            # Split the tweak
            Tl = tweakBytes[:HALF_TWEAK_LEN]
            Tr = tweakBytes[HALF_TWEAK_LEN:]
        elif len(tweakBytes) == TWEAK_LEN_NEW:
            # Tl is T[0..27] + 0000
            Tl = bytearray(tweakBytes[:4])
            Tl[3] &= 0xF0

            # Tr is T[32..55] + T[28..31] + 0000
            Tr = bytearray((int(tweakBytes[4:].hex(), 16) << 4).to_bytes(4, 'big'))
            Tr[3] = tweakBytes[6] << 4 & 0xF0
        else:
            raise ValueError(f"tweak length {len(tweakBytes)} invalid: tweak must be 56 or 64 bits")

        logging.debug(f"Tweak: {tweak}, tweakBytes:{tweakBytes.hex()}")

        # P is always 16 bytes
        # P = bytearray(BLOCK_SIZE)

        # Pre-calculate the modulus since it's only one of 2 values,
        # depending on whether i is even or odd

        modU = self.radix ** u
        modV = self.radix ** v
        logging.debug(f"modU: {modU} modV: {modV}")

        # Main Feistel Round, 8 times
        #
        # AES ECB requires the number of bits in the plaintext to be a multiple of
        # the block size. Thus, we pad the input to 16 bytes

        for i in range(NUM_ROUNDS):
            # logging.debug(f"-------- Round {i}")
            # Determine alternating Feistel round side
            if i % 2 == 0:
                m = u
                W = Tr
            else:
                m = v
                W = Tl

            # P is fixed-length 16 bytes
            P = FF3Cipher.calculateP(i, self.radix, W, B)
            revP = reverse_string(P)

            S = self.aesCipher.encrypt(bytes(revP))

            S = reverse_string(S)
            # logging.debug("S:    ", S.hex())

            y = int.from_bytes(S, byteorder='big')

            # Calculate c
            c = int2(reverse_string(A), self.radix)

            if c == 0:
                raise ValueError(f"string {A} is not within base/radix")

            c = c + y

            if i % 2 == 0:
                c = c % modU
            else:
                c = c % modV

            # logging.debug(f"m: {m} A: {A} c: {c} y: {y}")
            C = base_conv_r(c, self.radix, int(m))

            # Final steps
            A = B
            B = C

            # logging.debug(f"A: {A} B: {B}")

        return A + B

    def decrypt(self, ciphertext):
        """
        Decrypts the ciphertext string and returns a plaintext of the same length and format.

        The process of decryption is essentially the same as the encryption process. The  differences
        are  (1)  the  addition  function  is  replaced  by  a  subtraction function that is its
        inverse, and (2) the order of the round indices (i) is reversed.
        """
        return self.decrypt_with_tweak(ciphertext, self.tweak)

    def decrypt_with_tweak(self, ciphertext, tweak):
        """Decrypts the ciphertext string and returns a plaintext of the same length and format"""

        n = len(ciphertext)

        if n > self.maxLen:
            r = "".join(self.decrypt_with_tweak(t,tweak) for t in self.chunk(ciphertext))
            return r

        tweakBytes = bytes.fromhex(tweak)

        # Check if message length is within minLength and maxLength bounds
        if (n < self.minLen) or (n > self.maxLen):
            raise ValueError(f"message length {n} is not within min {self.minLen} and max {self.maxLen} bounds")

        # Make sure the given the length of tweak in bits is 56 or 64
        if len(tweakBytes) not in [TWEAK_LEN, TWEAK_LEN_NEW]:
            raise ValueError(f"tweak length {len(tweakBytes)} invalid: tweak must be 8 bytes, or 64 bits")

        # Check if the ciphertext message is formatted in the current radix
        x = int2(ciphertext, self.radix)
        if x == 0:
            raise ValueError("ciphertext string is not within base/radix {self.radix}")

        # Calculate split point
        u = math.ceil(n/2)
        v = n - u

        # Split the message
        A = ciphertext[:u]
        B = ciphertext[u:]

        # Split the tweak
        if len(tweakBytes) == TWEAK_LEN:
            # Split the tweak
            Tl = tweakBytes[:HALF_TWEAK_LEN]
            Tr = tweakBytes[HALF_TWEAK_LEN:]
        elif len(tweakBytes) == TWEAK_LEN_NEW:
            # Tl is T[0..27] + 0000
            Tl = bytearray(tweakBytes[:4])
            Tl[3] &= 0xF0

            # Tr is T[32..55] + T[28..31] + 0000
            Tr = bytearray((int(tweakBytes[4:].hex(), 16) << 4).to_bytes(4, 'big'))
            Tr[3] = tweakBytes[6] << 4 & 0xF0
        else:
            raise ValueError(f"tweak length {len(tweakBytes)} invalid: tweak must be 56 or 64 bits")

        logging.debug(f"Tweak: {tweak}, tweakBytes:{tweakBytes.hex()}")

        # P is always 16 bytes
        # P = bytearray(BLOCK_SIZE)

        # Pre-calculate the modulus since it's only one of 2 values,
        # depending on whether i is even or odd

        modU = self.radix ** u
        modV = self.radix ** v
        logging.debug(f"modU: {modU} modV: {modV}")

        # Main Feistel Round, 8 times

        for i in reversed(range(NUM_ROUNDS)):

            # logging.debug(f"-------- Round {i}")
            # Determine alternating Feistel round side
            if i % 2 == 0:
                m = u
                W = Tr
            else:
                m = v
                W = Tl

            # P is fixed-length 16 bytes
            P = FF3Cipher.calculateP(i, self.radix, W, A)
            revP = reverse_string(P)

            S = self.aesCipher.encrypt(bytes(revP))
            S = reverse_string(S)

            # logging.debug("S:    ", S.hex())

            y = int.from_bytes(S, byteorder='big')

            # Calculate c
            c = int2(reverse_string(B), self.radix)

            if c == 0:
                raise ValueError("string A is not within base/radix")

            c = c - y

            if i % 2 == 0:
                c = c % modU
            else:
                c = c % modV

            # logging.debug(f"m: {m} B: {B} c: {c} y: {y}")
            C = base_conv_r(c, self.radix, int(m))

            # Final steps
            B = A
            A = C

            # logging.debug(f"A: {A} B: {B}")

        return A + B

    def chunk(self, plain_text) -> list:
        l = len(plain_text)
        if l > self.maxLen:
            # chunk plain_text
            split_plain_text = [plain_text[index: index + self.maxLen] for index in range(0, l, self.maxLen)]
            # check if last part of split has length less than cipher's minLen, if so, resize
            gap = (self.minLen +1) - len(split_plain_text[-1])
            if gap > 0:
                split_plain_text[-1] = split_plain_text[-2][-gap:] + split_plain_text[-1]
                split_plain_text[-2] = split_plain_text[-2][:-gap]
            return split_plain_text

    def chunk_decrypt(self, cipher_text) -> str:
        l = len(cipher_text)
        if l > self.maxLen:
            # chunk plain_text
            split_cipher_text = [cipher_text[index: index + self.maxLen] for index in range(0, l, self.maxLen)]
            # check if last part of split has length less than cipher's minLen, if so, resize
            gap = (self.minLen +1) - len(split_cipher_text[-1])
            if gap > 0:
                split_cipher_text[-1] = split_cipher_text[-2][-gap:] + split_cipher_text[-1]
                split_cipher_text[-2] = split_cipher_text[-2][:-gap]
            r = "".join(self.decrypt(t) for t in split_cipher_text)
            return r


DIGITS = string.digits + string.ascii_lowercase + string.ascii_uppercase + "'-"
LEN_DIGITS = len(DIGITS)


def base_conv_r(n, base=2, length=0):    
    """
    Return a string representation of a number in the given base system for 2..36

    The string is left in a reversed order expected by the calling cryptographic function
    """

    x = ''
    while n >= base:
        n, b = divmod(n, base)
        x += DIGITS[b]
    x += DIGITS[n]

    if len(x) < length:
        x = x.ljust(length, '0')

    return x


def int2(plaintext,radix):
    y:int=0
    for i,j in enumerate(reverse_string(plaintext)):
        y = y+ DIGITS.find(j)*pow(radix,i)
    return y


