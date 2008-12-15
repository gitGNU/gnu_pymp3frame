# Copyright (c) 2005,2008 Michael Gold
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
# CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""\
Various constants and utility functions for working with MPEG audio data
that don't depend on specific data structures like FrameHeader."""


from __future__ import division, absolute_import
from . import errors


# MPEG audio header:
# AAAAAAAA AAABBCCD EEEEFFGH IIJJKLMM
#
# (based on information from
# http://www.mp3-tech.org/programmer/frame_header.html)
#
# A 11 (21-31) Sync (all bits 1)
# B  2 (19-20) MPEG version (11=V1, 10=V2, 01=res, 00=V2.5)
# C  2 (17-18) Layer (11=L1, 10=L2, 01=L3, 00=res)
# D  1 (16)    ~CRC (0=protected)
# E  4 (12-15) Bitrate (kbps):
# F  2 (10-11) Sampling rate (Hz):
# G  1 (9)     Padding (4 bytes in L1, 1 byte in others)
# H  1 (8)     Private
# I  2 (6-7)   Channel mode (00=stereo, 01=joint, 10=dual, 11=mono)
# J  2 (4-5)   Mode ext. (layers 1-2, joint stereo)
#  j1 1 (5)    Mid/side stereo (layer 3, joint stereo)
#  j2 1 (4)    Intensity stereo (layer 3, joint stereo)
# K  1 (3)     Copy-prevent
# L  1 (2)     Original
# M  2 (0-1)   Emphasis (00=none, 01=50/15 ms, 10=res, 11=CCIT J.17)

def _brs(*kbrs): return tuple([None] + [x*1000 for x in kbrs])

_br_v1L1 = _brs(32,64,96, 128,160,192,224, 256,288,320,352, 384,416,448)
_br_v1L2 = _brs(32,48,56,  64, 80, 96,112, 128,160,192,224, 256,320,384)
_br_v1L3 = _brs(32,40,48,  56, 64, 80, 96, 112,128,160,192, 224,256,320)
_br_v2L1 = _brs(32,48,56,  64, 80, 96,112, 128,144,160,176, 192,224,256)
_br_v2L2 = _brs( 8,16,24,  32, 40, 48, 56,  64, 80, 96,112, 128,144,160)
_br_v2L3 = _br_v2L2
del _brs

_br_tables = (  # indexed by B,C,E (version,layer,bitrate)
	(None, _br_v2L3, _br_v2L2, _br_v2L1),  # B=00 (V2.5)
	None,                                  # B=01 (reserved)
	(None, _br_v2L3, _br_v2L2, _br_v2L1),  # B=10 (V2)
	(None, _br_v1L3, _br_v1L2, _br_v1L1),  # B=11 (V1)
)

_sr_table = (  # indexed by B,F (version,samplerate)
	( 11025, 12000,  8000, None ),
	(  None,  None,  None, None ),
	( 22050, 24000, 16000, None ),
	( 44100, 48000, 32000, None ),
)

# samples per frame
_spf_table = (  # indexed by B,C (version,layer)
	( None,  576, 1152,  384 ),  # B = 00 (V2.5)
	( None, None, None, None ),  # B = 01 (reserved)
	( None,  576, 1152,  384 ),  # B = 02 (V1)
	( None, 1152, 1152,  384 ),  # B = 03 (V2)
)


def samples_per_frame(version_index, layer_index):
	"""samples_per_frame(version_index, layer_index) -> int

Return the number of audio samples in each frame."""
	
	if version_index < 0 or version_index > 3:
		raise ValueError("Invalid MPEG version")
	if layer_index < 0 or layer_index > 3:
		raise ValueError("Invalid MPEG layer")
	
	ret = _spf_table[version_index][layer_index]
	if ret == None:
		raise errors.MP3ReservedError("Reserved MPEG version or layer")
	
	return ret


def samplerate(version_index, samplerate_index):
	"""samplerate(version_index, samplerate_index) -> int

Return the number of audio samples per second (per channel)."""
	
	if samplerate_index < 0 or samplerate_index > 3:
		raise ValueError("Invalid samplerate")
	if version_index < 0 or version_index > 3:
		raise ValueError("Invalid MPEG version")
	
	ret = _sr_table[version_index][samplerate_index]
	if ret == None:
		raise errors.MP3ReservedError("Reserved MPEG version or samplerate")
	
	return ret


def bitrate(version_index, layer_index, bitrate_index):
	"""bitrate(version_index, layer_index, bitrate_index) -> int or None

Return the bitrate, in kbps; or None for a freeform frame."""
	
	if (version_index == 1) or (layer_index == 0) or (bitrate_index == 15):
		raise errors.MP3ReservedError("Reserved version, layer, or bitrate")
	
	return _br_tables[version_index][layer_index][bitrate_index]


def sample_size(layer_index):
	"""sample_size(layer_index) -> int

Return the number of bytes per audio sample."""
	
	if layer_index == 1: return 1 # layer 3
	elif layer_index == 2: return 1 # layer 2
	elif layer_index == 3: return 4 # layer 1 (4 bytes per sample)
	elif layer_index == 0:
		raise errors.MP3ReservedError("Reserved MPEG layer")
	else:
		raise ValueError("MPEG layer out of range")


def frame_size(version_index, layer_index,
		bitrate_index, samplerate_index, padding):
	"""frame_size(version_index, layer_index, bitrate_index,
           samplerate_index, padding) -> int or None

Return the size of a frame, in bytes; or None for a freeform frame."""
	
	br = bitrate(version_index, layer_index, bitrate_index)
	if br == None: return None

	spf = samples_per_frame(version_index, layer_index)
	sr = samplerate(version_index, samplerate_index)
	ss = sample_size(layer_index)
	
	ss = 1
	if layer_index == 3:  # layer 1
		mult = 12
		ss = 4
	elif layer_index == 1 and (version_index != 3):  # layer 3, lsf
		mult = 72
	else:
		mult = 144
	
	return ( (spf // (ss * 8)) * br // sr ) + ((padding != 0) * ss)


def min_bitrate_index(version_index, layer_index, samplerate_index, bytes):
	"""min_bitrate_index(version_index, layer_index, samplerate_index, bytes)
 -> (int, bool, int, int) or None

Determine the minimum bitrate_index needed to get a frame with at least
the specified number of bytes (some of which will be used for the header,
CRC, and side info).

The return value is a tuple: (bitrate_index, padding, size, bitrate);
or None if no bitrate is sufficient.
"""
	
	sr = samplerate(version_index, samplerate_index)
	bitrates = _br_tables[version_index][layer_index]
	
	ss = 1
	if layer_index == 3:  # layer 1
		mult = 12
		ss = 4
	elif layer_index == 1 and (version_index != 3):  # layer 3, lsf
		mult = 72
	else:
		mult = 144
	
	for (idx, br) in enumerate(bitrates):
		if br is None: continue
		
		n = ((mult * br) // sr) + 1  # include padding
		size = (n * ss)
		
		if (size >= bytes):
			base_size = size - ss
			if base_size >= bytes:
				padding = False
				size = base_size
			else:
				padding = True
			
			return (idx, padding, size, br)
	
	return None


_side_info_size = ((32, 17), (17, 9))

def side_info_size(version_index, channel_mode):
	"""side_info_size(version_index, channel_mode) -> int

Return the size of the layer 3 side_info structure, in bytes.
The value returned is also the offset of the Xing header in a frame
(excluding the 4-byte header and any CRC offset)."""
	
	lsf = (version_index != 3)
	mono = (channel_mode == 3)
	return _side_info_size[lsf][mono]


_side_info_bit_offsets = (
		((20, 79, 138, 197), (18, 77)),   # mpeg1 stereo, mono
		((10,73), (9,)) )                 # mpeg2

def side_info_bit_offsets(version_index, channel_mode):
	"""side_info_bit_offsets(version_index, channel_mode) -> tuple

Return a tuple listing the bit offset of each part2_3_length value
within the side_info structure."""
	
	lsf = (version_index != 3)
	mono = (channel_mode == 3)
	return _side_info_bit_offsets[lsf][mono]


# this table is used to determine the layer 2 bit allocation table
# (indexed by samplerate_index and bitrate_index; only verified for MPEG1)
_l2_alloc_table_sel = (
	# free,32,48,56, 64,80,96,112, 128,160,192 kbps
	(    1, 2, 2, 0,  0, 0, 1,  1,   1,  1,  1), # 44100/22050/11025 Hz
	(    0, 2, 2, 0,  0, 0, 0,  0,   0,  0,  0), # 48000/24000/12000 Hz
	(    1, 3, 3, 0,  0, 0, 1,  1,   1,  1,  1), # 32000/16000/ 8000 Hz
)
_protected_bits = (
	None,
	((256, 136), (136, 72)), # layer 3
	
	# TODO: get protected bit counts for layer 1 and 2 lsf modes
	
	# the L2 subvectors are indexed by the allocation table index
	# (determined using _l2_alloc_table_sel)
	(
		((284,308,84,124), (142,154,42,62)),
		((None,)*4,)*2
	),
	
	((256, 128), (None, None)), # layer 1
)

def protected_bit_count(version_index, layer_index, bitrate_index,
		samplerate_index, channel_mode):
	"""protected_bit_count(version_index, layer_index, bitrate_index,
                    samplerate_index, channel_mode) -> int

Return the number of audio_data bits that would be protected by a CRC.
protected_byte_count is a simpler interface if layer 2 support isn't needed."""
	
	mono = (channel_mode == 3)
	bits = _protected_bits[layer_index][mono]
	
	if layer_index == 2:
		i = _l2_alloc_table_sel[samplerate_index][bitrate_index]
		bits = bits[i]
	
	if bits is None:
		raise NotImplementedError(
				"protected bit count unknown for L1/L2 lsf modes")
	
	return bits


def protected_byte_count(version_index, layer_index, channel_mode):
	"""protected_byte_count(version_index, layer_index, channel_mode) -> int

Return the number audio_data bytes (an integer) that would be protected
by a CRC, for layer 1 or 3 only.  Use protected_bit_count for layer 2.
For layer 3, no audio data outside the side_info structure is protected."""
	
	if layer_index == 2:
		# for layer 2, we'd need more information, and the number
		# of protected bytes isn't an integer
		raise errors.MP3UsageError(
				"can't use protected_byte_count for layer 2")
	
	mono = (channel_mode == 3)
	bits = _protected_bits[lsf][layer_index][mono]
	if bits is None:
		raise NotImplementedError(
				"protected byte count unknown for L1/L2 lsf modes")
	
	return bits // 8
