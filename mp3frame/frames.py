# Copyright (c) 2008 Michael Gold
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

from __future__ import division, absolute_import
import array
import struct
from . import mp3bits, errors



def _enc(text): return tuple([ ord(x) for x in text ])
_Xing = _enc('Xing')
_Info = _enc('Info')
_VBRI = _enc('VBRI')

class MP3Frame(object):
	"""MP3Frame() -> object

Creates an object to store a physical MPEG audio frame.
Standard fields:
  header - a FrameHeader instance
  side_info - set for layer 3 only (see side_info.py)
  raw_body - a byte array
  crc16 - an integer, or None
  resynced - True if sync was lost before reading this frame,
             False if the frame was found as expected
  frame_number - a generated sequence number for the frame (0-based)
  byte_position - the number of bytes that preceded the header
"""
	
	def __len__(self):
		sz = 4
		if self.header.protection_bit == 0:
			sz += 2
		if self.header.layer_index == 1:  # layer 3
			sz += len(self.side_info.raw_data)
		
		sz += len(self.raw_body)
		return sz
	
	def encode(self, validate=True):
		"""encode() -> byte array

Encode the frame and return the raw data as a byte array.
This will automatically encode and checksum the header and side info."""
		
		head = self.header
		head.encode()
		data = head.raw_data[:4]  # copy array
		
		need_crc = (head.protection_bit == 0)
		if need_crc:
			data.append(0)
			data.append(0)
		
		if head.layer_index == 1:  # layer 3
			raw_si = self.side_info.raw_data
			sidesz = mp3bits.side_info_size(
					head.version_index, head.channel_mode)
			if len(raw_si) != sidesz and validate:
				raise errors.MP3UsageError("side info is the wrong length")
			
			if self.side_info.part2_3_end > len(self.raw_body) \
					and validate:
				raise errors.MP3UsageError("logical body extends past frame")
			
			data.extend(raw_si)
		
		data.extend(self.raw_body)
		
		if validate:
			sz = mp3bits.frame_size(head.version_index,
					head.layer_index, head.bitrate_index,
					head.samplerate_index, head.padded)
			if (len(data) != sz) and sz:
				raise errors.MP3UsageError("raw_body is the wrong length")
		
		if need_crc:
			crc = self.calc_crc()
			data[4] = crc >> 8
			data[5] = crc & 0xff
		
		return data
	
	def calc_crc(self):
		"""calc_crc() -> int

Calculate and return the CRC of the raw data fields; this doesn't
automatically update/encode anything."""
		
		head = self.header
		val = crc16(head.raw_data[2:4])
		
		layer_index = head.layer_index
		if layer_index == 1:  # layer 3
			val = crc16(self.side_info.raw_data, val)
		elif layer_index == 3:  # layer 1
			bytes = mp3bits.protected_byte_count(
					layer_index, self.head.channel_mode)
			val = crc16(self.raw_body[:bytes], val)
		elif layer_index == 2:  # layer 2
			#TODO: test this
			bits = mp3bits.protected_bit_count(
					layer_index, head.bitrate_index,
					head.samplerate_index, head.channel_mode)
			
			last_byte = bits // 8
			bits %= 8
			
			val = crc16(self.raw_body[:last_byte], val)
			if bits:
				last_part = self.raw_body[last_byte] >> (8-bits)
				val = crc16_bits(last_part, bits, val)
		
		return val
	
	def identify_vbr_header(self):
		"""identify_vbr_header() -> (str, int)

Identify the type of VBR header contained in this frame, if any.
Returns a (type, offset) tuple; or None if this isn't a VBR header frame.

'type' is "Xing" or "VBRI". 'offset' specifies the position of the tag
relative to raw_body (which will be negative if the tag starts within
the side info)."""
		
		raw_si = self.side_info.raw_data
		
		# the side info should be clear (except that the VBR header may
		# start in the last 2 bytes; see below)
		for i in range(len(raw_si) - 2):
			if raw_si[i] != 0: return None
		
		have_crc = (self.header.protection_bit == 0)
		body_pos = (2 * have_crc) + len(raw_si)
		
		# a VBRI header always starts 32 bytes from the beginning of
		# the side info
		vbri_offset = 32 - body_pos  # may be negative (-2)
		
		body4 = tuple(self.raw_body[:4])
		if body4 in (_Xing, _Info):
			return ('Xing', 0)
		elif body4 == _VBRI and vbri_offset == 0:
			return ('VBRI', 0)
		
		if vbri_offset > 0:
			ident = tuple(self.raw_body[vbri_offset:vbri_offset+4])
			if ident == _VBRI:
				return ('VBRI', vbri_offset)
		
		if have_crc:
			# apparently some encoders start a VBR header inside
			# the side info if a CRC is present
			
			ident = tuple(raw_si[-2:]) + body4[:2]
			if ident in (_Xing, _Info):
				return ('Xing', -2)
			elif ident == _VBRI and vbri_offset == -2:
				return ('VBRI', -2)
		
		return None
	
	def get_body_at_offset(self, offset):
		if offset >= 0:
			return self.raw_body[offset:]
		
		# negative offset (must point within side_info)
		
		if self.header.layer_index != 1:  # layer 3
			raise errors.MP3UsageError(
					"negative body offset only allowed for layer 3")
		
		raw_si = self.side_info.raw_data
		if -offset > len(raw_si):
			raise errors.MP3UsageError("body offset points before side_info")
		
		return raw_si[offset:] + self.raw_body
	
	def set_body_at_offset(self, offset, data):
		if offset >= 0:
			self.raw_body[offset:] = data
			return
		
		# negative offset (must point within side_info)
		
		if self.header.layer_index != 1:  # layer 3
			raise errors.MP3UsageError(
					"negative body offset only allowed for layer 3")
		
		raw_si = self.side_info.raw_data
		if -offset > len(raw_si):
			raise errors.MP3UsageError("body offset points before side_info")
		
		raw_si[offset:] = data[:-offset]
		self.raw_body[:] = data[-offset:]


class FrameHeader(object):
	__slots__ = ('version_index', 'layer_index', 'protection_bit',
			'bitrate_index', 'samplerate_index', 'padded', 'private',
			'channel_mode', 'mode_extension', 'copy_control',
			'original', 'emphasis', 'raw_data')
	
	def __init__(self, raw_data=None, **kwargs):
		if not raw_data:
			raw_data = array.array('B', '\xff\xfa\x60\x00')
		elif len(raw_data) < 4:
			raise ValueError("raw_data too short")
		
		self.raw_data = raw_data
		self._decode(raw_data)
		for (k,v) in kwargs.items():
			setattr(self, k, v)
	
	def _fieldstrs(self):
		ret = []
		for key in self.__slots__:
			val = getattr(self, key)
			if val != 0:
				ret.append('%s=%d' % (key,val))
			if key == 'emphasis': break  # last field
		return ret
	
	def __repr__(self):
		return 'FrameHeader(' + ', '.join(self._fieldstrs()) + ')'
	
	def _decode(self, data):
		"Update all fields based on raw_data."
		self.raw_data = data[:4]
		
		d1 = data[1]
		self.version_index = ((d1 >> 3) & 3)
		self.layer_index = ((d1 >> 1) & 3)
		self.protection_bit = (d1 & 1)
		
		d2 = data[2]
		self.bitrate_index = (d2 >> 4)
		self.samplerate_index = ((d2 >> 2) & 3)
		self.padded = ((d2 >> 1) & 1)
		self.private = (d2 & 1)
		
		d3 = data[3]
		self.channel_mode = (d3 >> 6)
		self.mode_extension = ((d3 >> 4) & 3)
		self.copy_control = ((d3 >> 3) & 1)
		self.original = ((d3 >> 2) & 1)
		self.emphasis = (d3 & 3)
	
	def encode(self):
		"Update raw_data based on the other fields."
		def mask(field, mask):
			val = getattr(self, field)
			if val < 0 or val > mask:
				raise ValueError("%s value out of range" % field)
			return val
		
		d = self.raw_data
		d[0] = 0xff
		d[1] = ( 0xe0 | (mask('version_index', 3) << 3)
				| (mask('layer_index', 3) << 1)
				| mask('protection_bit', 1) )
		d[2] = ( (mask('bitrate_index', 15) << 4)
				| (mask('samplerate_index', 3) << 2)
				| (mask('padded', 1) << 1)
				| mask('private', 1) )
		d[3] = ( (mask('channel_mode', 3) << 6)
				| (mask('mode_extension', 3) << 4)
				| (mask('copy_control', 1) << 3)
				| (mask('original', 1) << 2)
				| mask('emphasis', 3) )


class XingHeader(object):
	"""XingHeader(frame=None) -> object

Creates a XingHeader instance to represent a Xing/Info header frame.
Calls decode(frame) if a frame is given.
Standard fields:
  cbr_mode - True for an 'Info' header, False for 'Xing'
  frame_count - the number of frames in the file; or None
  byte_count - the number of bytes in the file; or None
  seek_table - a byte array of length 100; or None
  quality - an unsigned integer indicating the file's quality; or None
  extended_data - a byte array to fill any extra space in the frame
"""
	def __init__(self, frame=None, offset=None):
		if frame is not None:
			if offset is None:
				raise ValueError('offset needed when frame given')
			self.decode(frame, offset)
	
	def encode(self, frame, offset):
		data = array.array('B')
		def write_uint(val):
			data.fromstring(struct.pack('!I', val))
		
		if self.cbr_mode:
			data = _Info[:]
		else:
			data = _Xing[:]
		
		flags = self.flags & ~0xf
		flags |= 1 if self.frame_count is not None else 0
		flags |= 2 if self.byte_count is not None else 0
		flags |= 4 if self.seek_table is not None else 0
		flags |= 8 if self.quality is not None else 0
		self.flags = flags
		
		write_uint(flags)
		if flags & 1: write_uint(self.frame_count)
		if flags & 2: write_uint(self.byte_count)
		if flags & 4:
			if len(self.seek_table) != 100:
				raise errors.MP3UsageError("seek table must be 100 bytes long")
			data.extend(self.seek_table)
		if flags & 8: write_uint(self.quality)
		
		end_pos = len(data) + offset
		if self.extended_data:
			data.extend(self.extended_data)
		
		frame.set_body_at_offset(offset, data)
		return end_pos  # position of extended_data in frame.raw_body
	
	def decode(self, frame, offset):
		data = frame.get_body_at_offset(offset)
		def read_bytes(sz):
			if sz > len(data):
				raise errors.MP3DataError("Xing header out of data")
			ret = data[:sz]
			data[:sz] = data[:0]
			return ret
		def read_uint():
			return struct.unpack('!I', read_bytes(4).tostring())[0]
		
		tag = tuple(read_bytes(4)) if len(data) >= 4 else None
		if not tag in (_Xing, _Info):
			raise errors.MP3UsageError("not a Xing header")
		self.cbr_mode = (tag == _Info)
		
		self.flags = flags = read_uint()
		self.frame_count = read_uint() if (flags & 1) else None
		self.byte_count = read_uint() if (flags & 2) else None
		self.seek_table = read_bytes(100) if (flags & 4) else None
		self.quality = read_uint() if (flags & 8) else None
		self.extended_data = data[:]



class CommentTag(object):
	def __init__(self, type, data):
		self.tag_type = type
		self.raw_data = data
	
	def __len__(self):
		return len(self.raw_data)
	
	def __str__(self):
		return self.raw_data


# CRC functions

_crc_poly = 0x8005
def crc16_bits(val, bits, start=0xffff):
	"""crc16_bits(val, bits, start=0xffff) -> int

Return the crc of 'val' (an integer), MSB first.
The specified number of bits are used, and higher bits are ignored.
crc16 is more efficient but only works on whole bytes."""
	
	crc = start
	mask = 1 << bits
	while bits > 0:
		bits -= 1
		mask >>= 1
		
		if ((val & mask) >> bits) ^ (crc >> 15):
			crc = ((crc & 0x7fff) << 1) ^ _crc_poly
		else:
			crc = (crc & 0x7fff) << 1
	
	return crc

_crc_table = tuple([ crc16_bits(x, 8, 0) for x in range(256) ])
def crc16(data, start=0xffff):
	"""crc16(data, start=0xffff) -> int

Return the crc of 'data' (a sequence of unsigned 8-bit integers).
This is a faster version of crc16_bits that only works on whole bytes."""
	
	crc = start
	for ch in data:
		crc = ((crc & 0xff) << 8) ^ _crc_table[(crc >> 8) ^ ch]
	return crc
