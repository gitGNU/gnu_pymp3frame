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
import struct
import mp3bits

bufsize = 65536

# create a read/write bitfield property (used by FrameHeader)
def _bitfield(pos, mask):
	def getbits(self):
		return (self._header_bits >> pos) & mask
	
	def setbits(self, val):
		if hasattr(self, '_immutable'):
			raise TypeError("object is immutable")
		if (val & mask) != val:
			raise ValueError("value out of range")
		
		h = self._header_bits
		self._header_bits = (h & ~(mask << pos)) | (val << pos)
		try: self._validate()
		except:  # undo the change
			self._header_bits = h
			raise
	
	return property(getbits, setbits, None,
			"bit position %d, mask 0x%x" % (pos, mask))

class Header(object):
	# raises ValueError for a bad header (never IndexError)
	def __init__(self, header=None, mutable=0):
		if header == None:
			# set a default header, to start this object with a valid
			# state: MPEG 1 layer 3, 32 kbps, 44100 Hz, stereo, original
			self._header_bits = 0xfffb1004
		else:
			if isinstance(header, basestring):
				self._header_bits = struct.unpack('!I', header)[0]
			else:
				self._header_bits = int(header)
			
			if not mutable: self._immutable = 1
		
		self._validate()
	
	def __int__(self): return self._header_bits
	def __hash__(self):
		if not hasattr(self, '_immutable'):
			raise TypeError("mutable Header is unhashable")
		return self._header_bits
	
	# returns total frame size (header+body)
	def _get_size(self):
		cached = getattr(self, '_cached_len', None)
		if cached != None and cached[0] == self._header_bits:
			return cached[1]
		
		sz = mp3bits.frame_size(self.version_index, self.layer_index,
				self.bitrate_index, self.samplerate_index, self.padded)
		self._cached_len = (self._header_bits, sz)
		return sz
	
	# throw ValueError if this object has an invalid state
	def _validate(self):
		if (self._header_bits & 0xFFE00000) != 0xFFE00000:
			raise ValueError("invalid sync bits in header")
		self._get_size()
	
	def __unwritable(*a): raise TypeError("unwritable field")
	frame_size = property(_get_size, __unwritable)
	side_info_size = property(lambda self: mp3bits.side_info_size(
			self.version_index, self.channel_mode), __unwritable)
	
	binary = _bitfield(0, (1<<32)-1) # entire field
	version_index = _bitfield(19, 0x3)
	layer_index = _bitfield(17, 0x3)
	protection_bit = _bitfield(16, 0x1)
	bitrate_index = _bitfield(12, 0xf)
	samplerate_index = _bitfield(10, 0x3)
	padded = _bitfield(9, 0x1)
	private = _bitfield(8, 0x1)
	channel_mode = _bitfield(6, 0x3)
	mode_extension = _bitfield(4, 0x3)
	copy_prevent = _bitfield(3, 0x1)
	original = _bitfield(2, 0x1)
	emphasis = _bitfield(0, 0x3)
	
	def _set_binary_str(self, val):
		self.binary = struct.unpack('!I', self._header_bits)[0]
	binary_str = property(lambda self: struct.pack('!I', self.binary),
			_set_binary_str)
	
	# the 'protected' property is the inverse of 'protection_bit'
	def _set_protected(self, val): self.protection_bit = (1 - val)
	protected = property(lambda self: 1 - self.protection_bit,
			_set_protected)
	
	# TODO: make writable
	bitrate = property(lambda self: mp3bits.bitrate(self.version_index,
			self.layer_index, self.bitrate_index), __unwritable)
	
	# TODO: add samplerate
		
	def _set_version(self, val):
		self.version_index = ["2.5", None, "2", "1"].index(val)
	version = property(lambda self: ("2.5", None, "2", "1"
			)[self.version_index], _set_version)
	
	def _set_layer(self, val): self.layer_index = 4 - val
	layer = property(lambda self: 4 - self.layer_index, _set_layer)

del _bitfield

#class FrameBody(object):
#	def __init__(self, data):
#		self._data = data
	
class Frame(object):
	def __init__(self, header, pos):
		self._header = header
		self._data = None
		self._pos = pos
	
	def __len__(self):
		sz = self._header._get_size()
		if sz == None:
			#TODO: if self._data: return len(self._data) ?? + 4?
			raise ValueError("free format frame has unknown size")
		
		return sz
	
	def _set_data(self, data):
		sz = self._header._get_size()
		if sz != None and sz != len(data):
			raise ValueError("incorrect data size")
		
		self._data = data
	
	data = property(lambda self: self._data, _set_data)
	
	def _get_crc(self):
		if not self._header.protected: return None
		if not self._data: raise ValueError("frame has no data")
		return struct.unpack('!H', self._data[:2])[0]
	
	def __unwritable(*a): raise TypeError("unwritable field")
	header = property(lambda self: self._header, __unwritable)
	
	pos = property(lambda self: self._pos)
	
	def is_vbr_header(self):
		head = self._header
		data = self._data
		if not data: raise ValueError("frame has no data")
		
		if head.protected: offset = 6
		else: offset = 4
		
		if data[offset:offset+36] == ('\0'*32 + 'VBRI'):
			# TODO: check if offset is correct with and without CRC
			return True   # VBRI header
		
		nullcount = head.side_info_size
		frame_nulls = data[offset:offset+nullcount]
		if frame_nulls != ('\0' * nullcount):
			return False   # not a Xing header
		
		frame_tag = data[offset+nullcount:offset+nullcount+4]
		if frame_tag == 'Xing' or frame_tag == 'Info': return True
		
		return None

class Scanner(object):
	def __init__(self, mp3file):
		self._mp3file = mp3file
		self._buffer = ''
		self._bufsize = bufsize  # global var
		self._bufstart = 0
	
	def replace_buffer(self, start_pos, data):
		self._buffer = data
		self._bufstart = start_pos
	
	buffer = property(lambda self: self._buffer)
	buffer_start = property(lambda self: self._bufstart)
	
	def next_frame(self):
		while 1:  # look for a frame
			if len(self._buffer) < 4:
				newdata = self._mp3file.read(self._bufsize)
				if not newdata: return None  # EOF
				
				self._buffer += newdata
				continue
			
			# look for the first 8 sync bits
			framestart = self._buffer.find('\xff')
			if framestart < 0:
				# no frame header found
				#  -- discard data and read some more
				self._bufstart += len(self._buffer)
				self._buffer = ''
				continue
			elif framestart > 0:
				# found a possible frame header
				#  -- discard any data before the header
				self._bufstart += framestart
				self._buffer = self._buffer[framestart:]
				if len(self._buffer) < 4:
					continue  # loop to read some more data
			
			# check for the other 3 sync bits
			if not (ord(self._buffer[0]) >> 5) == 7:
				# this is not a frame, skip 1 byte and try again
				self._bufstart += 1
				self._buffer = self._buffer[1:]
				continue
			
			# parse the frame header and create a Frame object
			try: header = Header(self._buffer[:4])
			except ValueError:
				# not a valid frame, skip it
				self._bufstart += 1
				self._buffer = self._buffer[1:]
				continue
			
			framestart = self._bufstart
			size = header.frame_size
			if size == None: # freeform
				# TODO: find the next frame some other way
				raise ValueError("free format frames are not supported")
			
			# read the frame - if this fails, it can be retried later
			# because the buffer remains valid
			while len(self._buffer) < size:
				newdata = self._mp3file.read(self._bufsize)
				if not newdata: return None  # EOF
				
				self._buffer += newdata
			
			# only split the buffer after reading the whole frame
			framedata = self._buffer[:size]
			self._buffer = self._buffer[size:]
			self._bufstart += size
			
			# create a Frame based on this header
			fr = Frame(header, framestart)
			fr.data = framedata
			return fr

	def __iter__(self): return self
	def next(self):
		# call next_frame, following iterator protocol
		# (EOF condition is permanent)
		if hasattr(self, '_iter_done'):
			raise StopIteration("already finished iterating")
		
		fr = self.next_frame()
		if fr == None:
			self._iter_done = 1
			raise StopIteration("end of file")
		return fr
