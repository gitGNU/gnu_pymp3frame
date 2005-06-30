#!/usr/bin/python
#
# Copyright (c) 2005 Michael Gold
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

from __future__ import division

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
_br_table = (
	# V1   V1   V1   V2+  V2+  (MPEG version)     
	# L1   L2   L3   L1   L2+  (MPEG layer)
	#------ free format ------  # E = 0000
	( 32,  32,  32,  32,   8),  # E = 0001
	( 64,  48,  40,  48,  16),  # E = 0010
	( 96,  56,  48,  56,  24),  # E = 0011
	(128,  64,  56,  64,  32),  # E = 0100
	(160,  80,  64,  80,  40),  # E = 0101
	(192,  96,  80,  96,  48),  # E = 0110
	(224, 112,  96, 112,  56),  # E = 0111
	(256, 128, 112, 128,  64),  # E = 1000
	(288, 160, 128, 144,  80),  # E = 1001
	(320, 192, 160, 160,  96),  # E = 1010
	(352, 224, 192, 176, 112),  # E = 1011
	(384, 256, 224, 192, 128),  # E = 1100
	(416, 320, 256, 224, 144),  # E = 1101
	(448, 384, 320, 256, 160),  # E = 1110
	#---------- bad ----------  # E = 1111
)
# F  2 (10-11) Sampling rate (Hz):
_sr_table = (
	# MPEG2.5 ---- MPEG2 MPEG1
	( 11025, None, 22050, 44100, ),  # F = 00
	( 12000, None, 24000, 48000, ),  # F = 01
	(  8000, None, 16000, 32000, ),  # F = 10
	(  None, None,  None,  None, ),  # F = 11 (reserved)
)
# G  1 (9)     Padding (4 bytes in L1, 1 byte in others)
# H  1 (8)     Private
# I  2 (6-7)   Channel mode (00=stereo, 01=joint, 10=dual, 11=mono)
# J  2 (4-5)   Mode ext. (layers 1-2, joint stereo)
#  j1 1 (5)    Mid/side stereo (layer 3, joint stereo)
#  j2 1 (4)    Intensity stereo (layer 3, joint stereo)
# K  1 (3)     Copy-protect
# L  1 (2)     Original
# M  2 (0-1)   Emphasis (00=none, 01=50/15 ms, 10=res, 11=CCIT J.17)

# samples per frame
_spf_table = (
	# MPEG2.5 --- MPEG2 MPEG1  (B value)
	( None, None, None, None, ),  # C = 00 (reserved)
	(  576, None,  576, 1152, ),  # C = 01 (layer 3)
	( 1152, None, 1152, 1152, ),  # C = 10 (layer 2)
	(  384, None,  384,  384, ),  # C = 11 (layer 1)
)

def samples_per_frame(version_index, layer_index):
	if version_index < 0: raise IndexError("Invalid MPEG version")
	if layer_index < 0: raise IndexError("Invalid MPEG layer")
	
	ret = _spf_table[layer_index][version_index]  # can raise IndexError
	if ret == None:
		raise ValueError("Reserved MPEG version or layer")
	
	return ret

def samplerate(version_index, samplerate_index):
	if samplerate_index < 0: raise IndexError("Invalid samplerate")
	
	ret = _sr_table[samplerate_index][version_index]  # can raise IndexError
	if ret == None:
		raise ValueError("Reserved MPEG version or samplerate")
	
	return ret

def bitrate(version_index, layer_index, bitrate_index):
	if bitrate_index < 1:
		if bitrate_index == 0: return None  # freeform
		else: raise IndexError("Invalid bitrate")
	elif bitrate_index == 15: raise ValueError("Reserved bitrate")
	
	if version_index == 1: raise ValueError("Reserved MPEG version")
	elif (version_index < 0) or (version_index > 3):
		raise IndexError("MPEG version out of range")
	
	if (layer_index < 1) or (layer_index > 3):
		if layer_index == 0: raise ValueError("Reserved MPEG layer")
		else: raise IndexError("MPEG layer out of range")
	
	# find the correct column for _br_table
	layer_id = 4 - layer_index
	if version_index == 3: # MPEG1
		col = layer_id - 1
	else: # MPEG2 or MPEG2.5
		if layer_id == 1: col = 3
		else: col = 4  # layers 2 or 3
	
	return _br_table[bitrate_index-1][col] * 1000  # can raise IndexError

def sample_size(layer_index):
	if layer_index == 1: return 1 # layer 3
	elif layer_index == 2: return 1 # layer 2
	elif layer_index == 3: return 4 # layer 1 (4 bytes per sample)
	elif layer_index == 0: raise ValueError("Reserved MPEG layer")
	else: raise IndexError("MPEG layer out of range")

def frame_size(version_index, layer_index,
		bitrate_index, samplerate_index, padding):
	br = bitrate(version_index, layer_index, bitrate_index)
	if br == None: return None
	
	spf = samples_per_frame(version_index, layer_index)
	sr = samplerate(version_index, samplerate_index)
	ss = sample_size(layer_index)
	
	return ((spf // (ss * 8)) * br // sr) + ((padding != 0) * ss)

def side_info_size(version_index, channel_mode):
	# Calculate the offset of the Xing header in the frame
	# (excluding the 4-byte header and any CRC offset)
	
	mono = (channel_mode == 3)
	if version_index == 3:  # MPEG1
		if mono: return 17
		else: return 32
	else:
		if mono: return 9
		else: return 17
